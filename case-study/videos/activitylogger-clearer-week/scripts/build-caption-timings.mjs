#!/usr/bin/env node

import { readFileSync, writeFileSync } from "node:fs";

const readJson = (path) => JSON.parse(readFileSync(path, "utf8"));
const round = (value) => Number(value.toFixed(3));
const punctuationPause = (word) =>
  /[.!?]$/.test(word) ? 0.55 : /[,;:]$/.test(word) ? 0.28 : 0.08;

function timeWords(text, duration) {
  const tokens = text.trim().split(/\s+/);
  const lead = 0.1;
  const tail = 0.1;
  const parts = tokens.map((text) => ({
    text,
    speech: Math.max(0.8, text.replace(/[^\p{L}\p{N}']/gu, "").length * 0.16),
    pause: punctuationPause(text),
  }));
  const scale = (duration - lead - tail) / parts.reduce((sum, part) => sum + part.speech + part.pause, 0);
  let cursor = lead;
  return parts.map((part, index) => {
    const start = cursor;
    const end = Math.min(duration - tail, start + part.speech * scale);
    cursor += (part.speech + part.pause) * scale;
    return { id: `word-${index + 1}`, text: part.text, start: round(start), end: round(end) };
  });
}

function srtTime(seconds) {
  const ms = Math.round(seconds * 1000);
  const hours = Math.floor(ms / 3600000);
  const minutes = Math.floor((ms % 3600000) / 60000);
  const secs = Math.floor((ms % 60000) / 1000);
  const millis = ms % 1000;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")},${String(millis).padStart(3, "0")}`;
}

function srtCues(voices, starts) {
  const cues = [];
  for (const voice of voices) {
    let words = [];
    for (const word of voice.words) {
      words.push(word);
      const text = words.map((item) => item.text).join(" ");
      if (/[.!?]$/.test(word.text) || words.length >= 8 || text.length >= 54) {
        cues.push({
          start: starts[voice.frame - 1] + words[0].start,
          end: starts[voice.frame - 1] + words.at(-1).end + 0.12,
          text,
        });
        words = [];
      }
    }
    if (words.length) {
      cues.push({
        start: starts[voice.frame - 1] + words[0].start,
        end: starts[voice.frame - 1] + words.at(-1).end + 0.12,
        text: words.map((item) => item.text).join(" "),
      });
    }
  }
  return cues;
}

const request = readJson("audio_request.json");
const meta = readJson("audio_meta.json");
const engineMeta = readJson("audio_engine_meta.json");
const storyboard = readFileSync("STORYBOARD.md", "utf8");
const durations = storyboard
  .split(/^## Frame /m)
  .slice(1)
  .map((section) => Number(section.match(/^- duration: ([\d.]+)s$/m)?.[1]));

if (request.lines.length !== meta.voices.length || durations.some((value) => !Number.isFinite(value))) {
  throw new Error("Narration lines, voice files, and storyboard frames must match");
}

for (const [index, voice] of meta.voices.entries()) {
  voice.words = timeWords(request.lines[index].text, voice.duration_s);
  engineMeta.voices[index].words = voice.words;
}

const starts = durations.map((_, index) => durations.slice(0, index).reduce((sum, value) => sum + value, 0));
const cues = srtCues(meta.voices, starts);
for (let index = 0; index < cues.length - 1; index += 1) {
  cues[index].end = Math.min(cues[index].end, cues[index + 1].start);
}
const srt = cues
  .map((cue, index) => `${index + 1}\n${srtTime(cue.start)} --> ${srtTime(cue.end)}\n${cue.text}`)
  .join("\n\n");

const totalWords = request.lines.reduce((sum, line) => sum + line.text.trim().split(/\s+/).length, 0);
if (meta.voices.flatMap((voice) => voice.words).length !== totalWords || cues.at(-1).end >= 86) {
  throw new Error("Caption timing self-check failed");
}

writeFileSync("audio_meta.json", `${JSON.stringify(meta, null, 2)}\n`);
writeFileSync("audio_engine_meta.json", `${JSON.stringify(engineMeta, null, 2)}\n`);
writeFileSync("captions.srt", `${srt}\n`);
console.log(`Built ${totalWords} timed words and ${cues.length} SRT cues`);
