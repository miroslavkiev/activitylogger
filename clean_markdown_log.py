#!/usr/bin/env python3
"""Markdown activity-log compactor.

Goal: shrink auto-generated daily Markdown logs while preserving timeline context.

This tool does not redact secrets. Its output remains sensitive plaintext.

Main features:
  - compress consecutive duplicate UI/event lines (ignoring blank lines)
  - truncate oversized fenced code blocks (head/tail + marker)
  - compress repeated identical lines inside code blocks
  - truncate very long plaintext lines (head/tail + marker)
  - compress long consecutive runs of patterned spam lines (regex-based)
  - remove known-irrelevant noisy lines (regex-based) with a per-section summary

Only standard library.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Callable, Iterable, Iterator, List, Optional, Tuple

from markdown_format import (
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

# CommonMark-style backtick and tilde fences. Generated capture uses backticks,
# but accepting both here keeps compaction from changing ordinary Markdown.
RE_FENCE_OPEN = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})(.*)$")

PLAINTEXT_WARNING = (
    "WARNING: Compaction does not redact secrets. "
    "The output remains sensitive plaintext."
)

# Full compaction keeps several transformed lists alive at once. Spool every
# section, then use that richer path only below both limits. Larger sections
# are copied unchanged so memory stays bounded and no captured content vanishes.
SECTION_FULL_MODE_MAX_BYTES = 1 * 1024 * 1024
SECTION_FULL_MODE_MAX_LINES = 10_000
SECTION_SPOOL_MEMORY_BYTES = 256 * 1024
LARGE_SECTION_WARNING = (
    "WARNING: Section {index} body is {bytes} bytes across {lines} lines; "
    "streaming it unchanged through bounded safe mode. "
    "Noise, repeat, traceback, and line-truncation transforms were skipped."
)

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


FenceSpec = tuple[str, int]


def fence_open_spec(line: str) -> FenceSpec | None:
    """Return the marker and length for a valid opening fence."""
    match = RE_FENCE_OPEN.match(line.rstrip("\r\n"))
    if not match:
        return None
    marker, info = match.groups()
    if marker[0] == "`" and "`" in info:
        return None
    return marker[0], len(marker)


def is_fence_open(line: str) -> bool:
    return fence_open_spec(line) is not None


def is_fence_close(line: str, opener: FenceSpec | None = None) -> bool:
    """Return true for a bare closing fence compatible with ``opener``."""
    core = line.rstrip("\r\n")
    match = re.fullmatch(r"[ \t]{0,3}(`{3,}|~{3,})[ \t]*", core)
    if not match:
        return False
    marker = match.group(1)
    return opener is None or (marker[0] == opener[0] and len(marker) >= opener[1])


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
            out.append(INTRA_BLOCK_REPEAT_TEMPLATE.format(count=run - 1) + "\n")
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
    fence_spec: FenceSpec | None = None
    block_lines: List[str] = []

    compiled_noise = [(label, re.compile(pat)) for (label, pat) in CODEBLOCK_NOISE_PATTERNS]

    def filter_noise_in_block(content: List[str], fence: str) -> List[str]:
        match = RE_FENCE_OPEN.match(fence)
        lang = match.group(2).strip().lower() if match else ""
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
            opener = fence_open_spec(ln)
            if opener is not None:
                in_block = True
                fence_line = ln.rstrip("\n")
                fence_spec = opener
                block_lines = []
            else:
                out.append(ln)
            continue

        # inside block
        if is_fence_close(ln, fence_spec):
            assert fence_line is not None and fence_spec is not None
            processed = [truncate_long_line(x, MAX_PLAINTEXT_LINE_CHARS, PLAINTEXT_LINE_TRUNC_TEMPLATE) for x in block_lines]
            processed = filter_noise_in_block(processed, fence_line)
            processed = compress_repeated_lines_in_code_block(processed)
            processed = truncate_code_block_content(processed)

            out.append(fence_line + "\n")
            out.extend([x if x.endswith("\n") else x + "\n" for x in processed])
            out.append(ln)

            in_block = False
            fence_line = None
            fence_spec = None
            block_lines = []
        else:
            block_lines.append(ln)

    # Unclosed block: still noise-filter / truncate / compress like closed blocks
    if in_block and fence_line is not None and fence_spec is not None:
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
    fence_spec: FenceSpec | None = None

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
        if fence_spec is not None:
            flush()
            out.append(ln)
            if is_fence_close(ln, fence_spec):
                fence_spec = None
            continue

        opener = fence_open_spec(ln)
        if opener is not None:
            flush()
            out.append(ln)
            fence_spec = opener
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
    fence_spec: FenceSpec | None = None

    tb_start = re.compile(r"^\s*Traceback \(most recent call last\):\s*$")
    tb_chain = re.compile(
        r"^\s*(During handling of the above exception|"
        r"The above exception was the direct cause).*"
    )
    tb_terminal = re.compile(
        r"^\s*[A-Za-z_][\w.]*(?:Error|Exception):.*$"
    )
    # A permissive set of traceback-like lines. Stop when normal log flow resumes.
    # Continuations only. Broad path/error matchers can swallow real log lines.
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

        if fence_spec is not None:
            out.append(ln)
            if is_fence_close(ln, fence_spec):
                fence_spec = None
            i += 1
            continue
        opener = fence_open_spec(ln)
        if opener is not None:
            out.append(ln)
            fence_spec = opener
            i += 1
            continue

        if not tb_start.match(ln.rstrip("\n")):
            out.append(ln)
            i += 1
            continue

        # Gather traceback block
        block: List[str] = [ln]
        i += 1
        terminal_seen = False
        while i < len(lines):
            nxt = lines[i] if lines[i].endswith("\n") else lines[i] + "\n"
            if (
                fence_open_spec(nxt) is not None
                or is_section_header(nxt)
                or is_timestamp_line(nxt)
                or is_separator_line(nxt)
            ):
                break
            core = nxt.rstrip("\n")

            if terminal_seen:
                if is_blank(nxt):
                    following = i + 1
                    while following < len(lines) and is_blank(lines[following]):
                        following += 1
                    if following >= len(lines):
                        break
                    following_core = lines[following].rstrip("\r\n")
                    if not (
                        tb_chain.match(following_core)
                        or tb_start.match(following_core)
                    ):
                        break
                elif not (tb_chain.match(core) or tb_start.match(core)):
                    break
                terminal_seen = False

            if (
                tb_start.match(core)
                or tb_line.match(core)
                or is_blank(nxt)
                or (core[:1].isspace() and bool(core.strip()))
            ):
                block.append(nxt)
                i += 1
                if tb_terminal.match(core):
                    terminal_seen = True
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
    fence_spec: FenceSpec | None = None

    for line in lines:
        ln = line if line.endswith("\n") else line + "\n"

        if fence_spec is not None:
            out.append(ln)
            if is_fence_close(ln, fence_spec):
                fence_spec = None
            continue
        opener = fence_open_spec(ln)
        if opener is not None:
            out.append(ln)
            fence_spec = opener
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
    fence_spec: FenceSpec | None = None

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

        if fence_spec is not None:
            flush()
            out.append(ln)
            if is_fence_close(ln, fence_spec):
                fence_spec = None
            continue

        opener = fence_open_spec(ln)
        if opener is not None:
            flush()
            out.append(ln)
            fence_spec = opener
            continue

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


@dataclass
class _SpooledSection:
    header: str
    timestamp: str
    body: IO[str]
    byte_count: int = 0
    line_count: int = 0
    meaningful: bool = False

    def append(self, line: str) -> None:
        self.body.write(line)
        self.byte_count = self.body.tell()
        self.line_count += 1
        if not is_blank(line) and not is_separator_line(line):
            self.meaningful = True

    @property
    def use_safe_mode(self) -> bool:
        return (
            self.byte_count > SECTION_FULL_MODE_MAX_BYTES
            or self.line_count > SECTION_FULL_MODE_MAX_LINES
        )


def _with_newline(line: str) -> str:
    return line if line.endswith("\n") else line + "\n"


def _new_spooled_section(header: str, timestamp: str) -> _SpooledSection:
    body = tempfile.SpooledTemporaryFile(
        max_size=SECTION_SPOOL_MEMORY_BYTES,
        mode="w+t",
        encoding="utf-8",
        newline="",
    )
    return _SpooledSection(header=header, timestamp=timestamp, body=body)


def _iter_spooled_log_parts(
    lines: Iterable[str],
) -> Iterator[tuple[str, str | _SpooledSection]]:
    """Yield preamble lines and sections backed by a bounded memory spool."""
    stream = iter(lines)
    pending: str | None = None
    current: _SpooledSection | None = None
    fence_spec: FenceSpec | None = None

    try:
        while True:
            try:
                raw = pending if pending is not None else next(stream)
            except StopIteration:
                break
            pending = None
            line = _with_newline(raw)

            if fence_spec is not None:
                if current is None:
                    yield "preamble", line
                else:
                    current.append(line)
                if is_fence_close(line, fence_spec):
                    fence_spec = None
                continue

            opener = fence_open_spec(line)
            if opener is not None:
                if current is None:
                    yield "preamble", line
                else:
                    current.append(line)
                fence_spec = opener
                continue

            if is_section_header(line):
                candidate = next(stream, None)
                if candidate is not None and is_timestamp_line(candidate):
                    if current is not None:
                        ready = current
                        current = None
                        try:
                            yield "section", ready
                        finally:
                            ready.body.close()
                    current = _new_spooled_section(line, _with_newline(candidate))
                    continue
                if current is None:
                    yield "preamble", line
                else:
                    current.append(line)
                pending = candidate
                continue

            if current is None:
                yield "preamble", line
            else:
                current.append(line)

        if current is not None:
            ready = current
            current = None
            try:
                yield "section", ready
            finally:
                ready.body.close()
    finally:
        if current is not None:
            current.body.close()


def iter_log_parts(lines: Iterable[str]) -> Iterator[tuple[str, str | Section]]:
    """Compatibility iterator that materializes each spooled section body."""
    for kind, value in _iter_spooled_log_parts(lines):
        if kind == "preamble":
            assert isinstance(value, str)
            yield kind, value
            continue
        assert isinstance(value, _SpooledSection)
        value.body.seek(0)
        yield kind, Section(value.header, value.timestamp, value.body.readlines())


def split_into_preamble_and_sections(lines: List[str]) -> Tuple[List[str], List[Section]]:
    """Compatibility list API backed by the fence-aware streaming parser."""
    preamble: List[str] = []
    sections: List[Section] = []
    for kind, value in iter_log_parts(lines):
        if kind == "preamble":
            assert isinstance(value, str)
            preamble.append(value)
        else:
            assert isinstance(value, Section)
            sections.append(value)
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


def compacted_output_path(input_path: str) -> str:
    base, ext = os.path.splitext(input_path)
    if not ext:
        ext = ".md"
    return f"{base}_compacted{ext}"


def cleaned_output_path(input_path: str) -> str:
    """Return the legacy output name for import compatibility."""
    base, ext = os.path.splitext(input_path)
    if not ext:
        ext = ".md"
    return f"{base}_cleaned{ext}"


def read_text_file(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.readlines()


def write_text_file(path: str, lines: Iterable[str]) -> None:
    """Atomically replace ``path`` with mode 0600 after a complete write."""
    destination = Path(path)
    fd, temporary = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            fd = -1
            for line in lines:
                output.write(line)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def iter_compacted_lines(
    lines: Iterable[str],
    *,
    warn: Callable[[str], None] | None = None,
) -> Iterator[str]:
    """Compact a stream with full semantics below the section safety limits."""
    warn_fn = warn if warn is not None else lambda message: print(message, file=sys.stderr)
    section_index = 0
    for kind, value in _iter_spooled_log_parts(lines):
        if kind == "preamble":
            assert isinstance(value, str)
            yield value
            continue
        assert isinstance(value, _SpooledSection)
        section_index += 1
        value.body.seek(0)
        if value.use_safe_mode:
            warn_fn(
                LARGE_SECTION_WARNING.format(
                    index=section_index,
                    bytes=value.byte_count,
                    lines=value.line_count,
                )
            )
            if not value.meaningful:
                continue
            yield value.header
            yield value.timestamp
            yield from value.body
            continue

        compacted_body = sanitize_section_body(value.body.readlines())
        if not section_has_meaningful_content(compacted_body):
            continue
        yield value.header
        yield value.timestamp
        yield from compacted_body


def compact_file(input_path: str, output_path: str | None = None) -> str:
    """Compact one Markdown log into an atomic, private plaintext output."""
    destination = output_path or compacted_output_path(input_path)
    with open(input_path, "r", encoding="utf-8", errors="replace") as source:
        for line in source:
            if line.startswith("## "):
                break
            if line.rstrip("\r\n").startswith(
                "> format: activitylogger-analysis-"
            ):
                raise ValueError("analysis logs are already compact; refusing compaction")
        source.seek(0)
        write_text_file(destination, iter_compacted_lines(source))
    return destination


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compact an ActivityLogger Markdown log without redacting it."
    )
    parser.add_argument("path", help="Path to the Markdown log file to compact")
    args = parser.parse_args(argv)

    print(PLAINTEXT_WARNING, file=sys.stderr)

    in_path = args.path
    if not os.path.exists(in_path):
        print(f"Error: file not found: {in_path}", file=sys.stderr)
        return 2
    if not os.path.isfile(in_path):
        print(f"Error: not a file: {in_path}", file=sys.stderr)
        return 2

    out_path = compact_file(in_path)
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
