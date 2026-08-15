#!/usr/bin/env python3
"""
Markdown activity-log cleaner.

Goal: shrink auto-generated daily Markdown logs while preserving timeline context.

Main features:
  - compress consecutive duplicate UI/event lines (ignoring blank lines)
  - truncate oversized fenced code blocks (head/tail + marker)
  - compress repeated identical lines inside code blocks
  - truncate very long plaintext lines (head/tail + marker)
  - compress long consecutive runs of patterned “spam” lines (regex-based)
  - remove known-irrelevant noisy lines (regex-based) with a per-section summary

Only standard library.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from markdown_format import (
    RE_TIMESTAMP_LINE,
    URL_EVENT_PREFIX,
    is_timestamp_line,
)

# ----------------------------
# Tunables (edit to taste)
# ----------------------------

# Code fence truncation (content lines, excluding the ``` fences themselves)
CODE_BLOCK_MAX_LINES = 50
CODE_BLOCK_KEEP_HEAD = 25
CODE_BLOCK_KEEP_TAIL = 24  # marker consumes 1 line
CODE_BLOCK_TRUNC_TEMPLATE = "... [Truncated {removed} lines of logs/dumps to save space] ..."

# Intra-block repetition compression (inside fenced blocks)
INTRA_BLOCK_REPEAT_THRESHOLD = 3
INTRA_BLOCK_REPEAT_TEMPLATE = "... [Previous line repeated {count} times]"

# Plaintext line truncation (outside & inside fences)
MAX_PLAINTEXT_LINE_CHARS = 400
PLAINTEXT_LINE_TRUNC_TEMPLATE = "... [Truncated {removed} chars to save space] ..."

# Consecutive identical event dedupe (outside fences)
UI_DUP_SUFFIX_TEMPLATE = " (x{count})"

# Patterned spam runs (outside fences): keep head/tail and collapse middle
SPAM_RUN_MAX_LINES = 30
SPAM_RUN_KEEP_HEAD = 4
SPAM_RUN_KEEP_TAIL = 4
SPAM_RUN_TRUNC_TEMPLATE = "... [Truncated {removed} noisy log lines matching {label}] ..."

# Traceback / error block compaction (outside fences)
TRACEBACK_MAX_LINES = 80
TRACEBACK_KEEP_HEAD = 20
TRACEBACK_KEEP_TAIL = 10
TRACEBACK_TRUNC_TEMPLATE = "... [Truncated {removed} traceback/error lines to save space] ..."

# ----------------------------
# Patterns
# ----------------------------

RE_SECTION_HEADER = re.compile(r"^##\s+.+\S.*$")

# Fences: open is any ```..., close must be bare ```
RE_FENCE_OPEN = re.compile(r"^```.*$")
RE_FENCE_CLOSE = re.compile(r"^```[\t ]*$")

# Shared noise rows reused by section filter + fenced-block filter
_SHARED_NOISE: List[Tuple[str, str]] = [
    ("DETECTOR/BRIDGE logs", r"^\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+(DETECTOR|BRIDGE)\b.*"),
    ("transcription pipeline status", r"^\s*\[(status|state|pipeline|recorder)\].*"),
    ("objc duplicate class warnings", r"^\s*objc\[\d+\]:\s+Class\s+.*\s+is implemented in both\b.*"),
]

# One pattern shared by spam-run compaction and fenced-block noise removal
_REMOTE_RAW_NOISE: Tuple[str, str] = (
    "remote.raw stream",
    r"^\[\d{2}:\d{2}:\d{2}\.\d{3}\]\[I\]\[remote\.raw:\d+\]:\s+Received Raw:\s+\d+",
)

# Runs of lines matching these regexes will be compacted when very long (consecutive runs only).
SPAM_RUN_PATTERNS: List[Tuple[str, str]] = [
    _REMOTE_RAW_NOISE,
]

# Non-consecutive noise lines to REMOVE (outside fences) with per-section summary.
NOISE_LINE_PATTERNS: List[Tuple[str, str]] = _SHARED_NOISE + [
    ("shell prompt (macOS-Native-Transcription)", r"^\w+@[^ ]+\s+macOS-Native-Transcription\s+%.*"),
    ("python site-packages stacktrace noise", r"^\s*File\s+\".*?/site-packages/.*\".*$"),
    ("warnings.warn", r"^\s*warnings\.warn\(.*$"),
    ("json-ish punctuation", r"^\s*[\{\}]\,?\s*$"),
    ("closing paren only", r"^\s*\)\s*$"),
    ("stray fence line", r"^\s*```[a-zA-Z0-9_-]*\s*$"),
    ("terminal caret artifacts", r"^\s*(\^C.*|\^\s*)$"),
]

# Noise lines to remove *inside* fenced log-dumps (only for ```text / ```log / ```txt blocks)
CODEBLOCK_NOISE_PATTERNS: List[Tuple[str, str]] = _SHARED_NOISE + [
    _REMOTE_RAW_NOISE,
]


def is_blank(line: str) -> bool:
    return line.strip() == ""


def is_section_header(line: str) -> bool:
    return bool(RE_SECTION_HEADER.match(line))


def is_separator_line(line: str) -> bool:
    return line.strip() == "---"


def is_fence_open(line: str) -> bool:
    return bool(RE_FENCE_OPEN.match(line.rstrip("\n")))


def is_fence_close(line: str) -> bool:
    return bool(RE_FENCE_CLOSE.match(line.rstrip("\n")))


def is_event_candidate_line(line: str) -> bool:
    if is_blank(line):
        return False
    if is_section_header(line):
        return False
    if is_timestamp_line(line):
        return False
    if is_separator_line(line):
        return False
    if is_fence_open(line):
        return False
    return True


def is_url_event_line(line: str) -> bool:
    """F4 stable token: leave ``> [URL]: …`` intact (no plaintext truncation)."""
    core = line[:-1] if line.endswith("\n") else line
    return core.startswith(URL_EVENT_PREFIX)


def truncate_plaintext_line(line: str) -> str:
    """Truncate long plaintext; preserve F4 URL event lines unchanged."""
    if is_url_event_line(line):
        return line if line.endswith("\n") else line + "\n"
    return truncate_long_line(line, MAX_PLAINTEXT_LINE_CHARS, PLAINTEXT_LINE_TRUNC_TEMPLATE)


def truncate_long_line(line: str, max_chars: int, marker_template: str) -> str:
    has_nl = line.endswith("\n")
    core = line[:-1] if has_nl else line
    if len(core) <= max_chars:
        return line

    marker = marker_template.format(removed=max(0, len(core) - max_chars))
    room = max_chars - len(marker)
    if room < 10:
        out = marker[:max_chars]
        return out + ("\n" if has_nl else "")

    head = room // 2
    tail = room - head
    removed = len(core) - (head + tail)
    marker = marker_template.format(removed=removed)
    out = core[:head] + marker + core[-tail:]
    if len(out) > max_chars:
        out = out[:max_chars]
    return out + ("\n" if has_nl else "")


def compress_repeated_lines_in_code_block(lines: List[str]) -> List[str]:
    if not lines:
        return []
    out: List[str] = []
    prev: Optional[str] = None
    run = 0

    def flush() -> None:
        nonlocal prev, run
        if prev is None:
            return
        if run > INTRA_BLOCK_REPEAT_THRESHOLD:
            out.append(prev)
            out.append(INTRA_BLOCK_REPEAT_TEMPLATE.format(count=run) + "\n")
        else:
            out.extend([prev] * run)
        prev = None
        run = 0

    for ln in lines:
        if prev is None:
            prev = ln
            run = 1
            continue
        if ln == prev:
            run += 1
            continue
        flush()
        prev = ln
        run = 1
    flush()
    return out


def truncate_code_block_content(lines: List[str]) -> List[str]:
    if len(lines) <= CODE_BLOCK_MAX_LINES:
        return lines
    head = lines[:CODE_BLOCK_KEEP_HEAD]
    tail = lines[-CODE_BLOCK_KEEP_TAIL:] if CODE_BLOCK_KEEP_TAIL > 0 else []
    removed = len(lines) - (len(head) + len(tail))
    return head + [CODE_BLOCK_TRUNC_TEMPLATE.format(removed=removed) + "\n"] + tail


def process_fenced_code_blocks(lines: List[str]) -> List[str]:
    out: List[str] = []
    in_block = False
    fence_line: Optional[str] = None
    block_lines: List[str] = []

    compiled_noise = [(label, re.compile(pat)) for (label, pat) in CODEBLOCK_NOISE_PATTERNS]

    def filter_noise_in_block(content: List[str], fence: str) -> List[str]:
        lang = fence[3:].strip().lower()
        if lang and lang not in ("text", "log", "txt"):
            return content
        removed: dict[str, int] = {}
        kept: List[str] = []
        for ln in content:
            core = ln.rstrip("\n")
            matched = False
            for label, pat in compiled_noise:
                if pat.match(core):
                    removed[label] = removed.get(label, 0) + 1
                    matched = True
                    break
            if not matched:
                kept.append(ln)
        if removed:
            parts = [f"{k}={v}" for k, v in sorted(removed.items())]
            kept.append(f"... [Removed noisy lines inside block: {'; '.join(parts)}] ...\n")
        return kept

    for line in lines:
        ln = line if line.endswith("\n") else line + "\n"

        if not in_block:
            if is_fence_open(ln):
                in_block = True
                fence_line = ln.rstrip("\n")
                block_lines = []
            else:
                out.append(ln)
            continue

        # inside block
        if is_fence_close(ln):
            assert fence_line is not None
            processed = [truncate_long_line(x, MAX_PLAINTEXT_LINE_CHARS, PLAINTEXT_LINE_TRUNC_TEMPLATE) for x in block_lines]
            processed = filter_noise_in_block(processed, fence_line)
            processed = compress_repeated_lines_in_code_block(processed)
            processed = truncate_code_block_content(processed)

            out.append(fence_line + "\n")
            out.extend([x if x.endswith("\n") else x + "\n" for x in processed])
            out.append(ln)

            in_block = False
            fence_line = None
            block_lines = []
        else:
            block_lines.append(ln)

    # Unclosed block: still noise-filter / truncate / compress like closed blocks
    if in_block and fence_line is not None:
        processed = [truncate_long_line(x, MAX_PLAINTEXT_LINE_CHARS, PLAINTEXT_LINE_TRUNC_TEMPLATE) for x in block_lines]
        processed = filter_noise_in_block(processed, fence_line)
        processed = compress_repeated_lines_in_code_block(processed)
        processed = truncate_code_block_content(processed)
        out.append(fence_line + "\n")
        out.extend([x if x.endswith("\n") else x + "\n" for x in processed])

    return out


def compress_spam_runs(lines: List[str]) -> List[str]:
    compiled = [(label, re.compile(pat)) for (label, pat) in SPAM_RUN_PATTERNS]
    if not compiled:
        return lines

    out: List[str] = []
    run_label: Optional[str] = None
    run_lines: List[str] = []

    def match_label(s: str) -> Optional[str]:
        for label, pat in compiled:
            if pat.match(s):
                return label
        return None

    def flush() -> None:
        nonlocal run_label, run_lines
        if not run_lines:
            return
        if run_label is None or len(run_lines) <= SPAM_RUN_MAX_LINES:
            out.extend(run_lines)
        else:
            available = SPAM_RUN_MAX_LINES - 1
            keep_head = SPAM_RUN_KEEP_HEAD
            keep_tail = SPAM_RUN_KEEP_TAIL
            if keep_head + keep_tail > available:
                keep_head = available // 2
                keep_tail = available - keep_head
            head = run_lines[:keep_head]
            tail = run_lines[-keep_tail:] if keep_tail > 0 else []
            removed = len(run_lines) - (len(head) + len(tail))
            out.extend(head)
            out.append(SPAM_RUN_TRUNC_TEMPLATE.format(removed=removed, label=run_label) + "\n")
            out.extend(tail)
        run_label = None
        run_lines = []

    for line in lines:
        ln = line if line.endswith("\n") else line + "\n"
        if is_fence_open(ln):
            flush()
            out.append(ln)
            continue

        label = match_label(ln.rstrip("\n"))
        if label is None:
            flush()
            out.append(truncate_plaintext_line(ln))
            continue

        if run_label is None:
            run_label = label
            run_lines = [truncate_plaintext_line(ln)]
        elif run_label == label:
            run_lines.append(truncate_plaintext_line(ln))
        else:
            flush()
            run_label = label
            run_lines = [truncate_plaintext_line(ln)]

    flush()
    return out


def compress_traceback_blocks(lines: List[str]) -> List[str]:
    """
    Collapse verbose multi-line Python tracebacks and similar error dumps outside fenced blocks.
    This is a big lever for days where terminal output dominates but isn’t fenced.
    """
    out: List[str] = []
    in_fence = False

    tb_start = re.compile(r"^\s*Traceback \(most recent call last\):\s*$")
    # A permissive set of “traceback-ish” lines; we stop when content clearly returns to normal log flow.
    # Continuations only — do not use ultra-broad path/Error matchers that swallow real log lines.
    tb_line = re.compile(
        r"^\s*("
        r"File\s+\".+?\"(, line \d+.*)?|"
        r"(During handling of the above exception|The above exception was the direct cause).*|"
        r"(requests|httpx)\.[A-Za-z_].*|"
        r"(HfHubHTTPError|Cannot access gated repo|Access to model .* is restricted|It might be because|For more information check:).*|"
        r"visit https?://.*|"
        r"(raise|from)\b.*|"
        r"\^C.*|"
        r"[A-Za-z_][\w\.]*Error:.*|"
        r"[A-Za-z_][\w\.]*Exception:.*"
        r")$"
    )

    i = 0
    while i < len(lines):
        ln = lines[i] if lines[i].endswith("\n") else lines[i] + "\n"

        if is_fence_open(ln):
            out.append(ln)
            in_fence = True
            i += 1
            continue
        if in_fence:
            out.append(ln)
            if is_fence_close(ln):
                in_fence = False
            i += 1
            continue

        if not tb_start.match(ln.rstrip("\n")):
            out.append(ln)
            i += 1
            continue

        # Gather traceback block
        block: List[str] = [ln]
        i += 1
        while i < len(lines):
            nxt = lines[i] if lines[i].endswith("\n") else lines[i] + "\n"
            if is_fence_open(nxt) or is_section_header(nxt) or is_timestamp_line(nxt) or is_separator_line(nxt):
                break
            core = nxt.rstrip("\n")
            if tb_line.match(core) or is_blank(nxt):
                block.append(nxt)
                i += 1
                continue
            break

        if len(block) <= TRACEBACK_MAX_LINES:
            out.extend(block)
            continue

        available = TRACEBACK_MAX_LINES - 1
        keep_head = TRACEBACK_KEEP_HEAD
        keep_tail = TRACEBACK_KEEP_TAIL
        if keep_head + keep_tail > available:
            keep_head = available // 2
            keep_tail = available - keep_head

        head = block[:keep_head]
        tail = block[-keep_tail:] if keep_tail > 0 else []
        removed = len(block) - (len(head) + len(tail))
        out.extend(head)
        out.append(TRACEBACK_TRUNC_TEMPLATE.format(removed=removed) + "\n")
        out.extend(tail)

    return out


def filter_noise_lines_for_section(lines: List[str]) -> Tuple[List[str], dict[str, int]]:
    compiled = [(label, re.compile(pat)) for (label, pat) in NOISE_LINE_PATTERNS]
    if not compiled:
        return lines, {}

    out: List[str] = []
    removed: dict[str, int] = {}
    in_block = False

    for line in lines:
        ln = line if line.endswith("\n") else line + "\n"

        if is_fence_open(ln):
            out.append(ln)
            in_block = True
            continue
        if in_block:
            out.append(ln)
            if is_fence_close(ln):
                in_block = False
            continue

        if is_blank(ln) or is_separator_line(ln):
            out.append(ln)
            continue

        core = ln.rstrip("\n")
        matched = False
        for label, pat in compiled:
            if pat.match(core):
                removed[label] = removed.get(label, 0) + 1
                matched = True
                break
        if matched:
            continue

        out.append(ln)

    return out, removed


def dedupe_consecutive_event_lines(lines: List[str]) -> List[str]:
    out: List[str] = []
    pending_line: Optional[str] = None
    pending_count = 0
    pending_blanks: List[str] = []

    def flush() -> None:
        nonlocal pending_line, pending_count, pending_blanks
        if pending_line is None:
            return
        if pending_count > 1:
            out.append(pending_line.rstrip("\n") + UI_DUP_SUFFIX_TEMPLATE.format(count=pending_count) + "\n")
        else:
            out.append(pending_line if pending_line.endswith("\n") else pending_line + "\n")
        out.extend(pending_blanks)
        pending_line = None
        pending_count = 0
        pending_blanks = []

    for line in lines:
        ln = line if line.endswith("\n") else line + "\n"
        ln = truncate_plaintext_line(ln)

        if is_blank(ln):
            if pending_line is not None:
                pending_blanks.append(ln)
            else:
                out.append(ln)
            continue

        if pending_line is not None and is_event_candidate_line(ln) and is_event_candidate_line(pending_line):
            if ln.rstrip("\n") == pending_line.rstrip("\n"):
                pending_count += 1
                pending_blanks = []
                continue

        flush()

        if is_event_candidate_line(ln):
            pending_line = ln
            pending_count = 1
            pending_blanks = []
        else:
            out.append(ln)

    flush()
    return out


@dataclass
class Section:
    header: str
    timestamp: str
    body: List[str]


def split_into_preamble_and_sections(lines: List[str]) -> Tuple[List[str], List[Section]]:
    preamble: List[str] = []
    sections: List[Section] = []

    i = 0
    n = len(lines)

    while i < n and not is_section_header(lines[i]):
        preamble.append(lines[i] if lines[i].endswith("\n") else lines[i] + "\n")
        i += 1

    while i < n:
        if not is_section_header(lines[i]):
            preamble.append(lines[i] if lines[i].endswith("\n") else lines[i] + "\n")
            i += 1
            continue

        header = lines[i] if lines[i].endswith("\n") else lines[i] + "\n"
        i += 1

        timestamp = ""
        if i < n and is_timestamp_line(lines[i]):
            timestamp = lines[i] if lines[i].endswith("\n") else lines[i] + "\n"
            i += 1

        body: List[str] = []
        while i < n and not is_section_header(lines[i]):
            body.append(lines[i] if lines[i].endswith("\n") else lines[i] + "\n")
            i += 1

        sections.append(Section(header=header, timestamp=timestamp, body=body))

    return preamble, sections


def section_has_meaningful_content(lines: List[str]) -> bool:
    for ln in lines:
        if is_blank(ln) or is_separator_line(ln):
            continue
        return True
    return False


def sanitize_section_body(body_lines: List[str]) -> List[str]:
    after_code = process_fenced_code_blocks(body_lines)
    after_tb = compress_traceback_blocks(after_code)
    after_noise, removed_counts = filter_noise_lines_for_section(after_tb)
    after_spam = compress_spam_runs(after_noise)
    after_ui = dedupe_consecutive_event_lines(after_spam)

    if removed_counts:
        parts = [f"{k}={v}" for k, v in sorted(removed_counts.items())]
        after_ui.append(f"... [Removed noisy lines: {'; '.join(parts)}] ...\n")
    return after_ui


def cleaned_output_path(input_path: str) -> str:
    base, ext = os.path.splitext(input_path)
    if not ext:
        ext = ".md"
    return f"{base}_cleaned{ext}"


def read_text_file(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.readlines()


def write_text_file(path: str, lines: Iterable[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Clean/sanitize auto-generated Markdown activity log files.")
    parser.add_argument("path", help="Path to the Markdown log file to clean")
    args = parser.parse_args(argv)

    in_path = args.path
    if not os.path.exists(in_path):
        print(f"Error: file not found: {in_path}", file=sys.stderr)
        return 2
    if not os.path.isfile(in_path):
        print(f"Error: not a file: {in_path}", file=sys.stderr)
        return 2

    raw_lines = read_text_file(in_path)
    preamble, sections = split_into_preamble_and_sections(raw_lines)

    out_lines: List[str] = []
    out_lines.extend(preamble)

    for sec in sections:
        cleaned_body = sanitize_section_body(sec.body)
        if not section_has_meaningful_content(cleaned_body):
            continue
        out_lines.append(sec.header)
        if sec.timestamp:
            out_lines.append(sec.timestamp)
        out_lines.extend(cleaned_body)

    out_path = cleaned_output_path(in_path)
    write_text_file(out_path, out_lines)
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

