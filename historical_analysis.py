#!/usr/bin/env python3
"""Create private, local-only analysis views of completed legacy logs."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import os
import re
import stat
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from analysis_log import AnalysisRecord, _ensure_private_dir, parse_records, render_records
from clean_markdown_log import (
    Section,
    fence_open_spec,
    is_blank,
    is_fence_close,
    is_section_header,
    is_separator_line,
    write_text_file,
)
from markdown_format import URL_EVENT_PREFIX, is_timestamp_line, sanitize_markdown_inline
from window_titles import FALLBACK_HEADING


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "private_historical_review"
DEFAULT_TIMEZONE = "Europe/Zagreb"
SOURCE_NAME_RE = re.compile(r"daily_log_(\d{4}-\d{2}-\d{2})\.md")
SOURCE_HEADER_RE = re.compile(r"^# Work Log [^0-9]+(\d{4}-\d{2}-\d{2})\s*$")
TIMESTAMP_RE = re.compile(
    r"^\*(\d{2}:\d{2}:\d{2})(?: \N{MIDDLE DOT} trigger:([a-z_]+))?\*\s*$"
)
LOGGER_STARTED_RE = re.compile(r"^\*Logger started at (\d{2}:\d{2}:\d{2})\*\s*$")
CLICK_PREFIX = "🖱️ **Клік:** "
SCREEN_PREFIX = "💻 **Екран:**"
CLIPBOARD_PREFIX = "> [CLIPBOARD]:"
SCROLL_PREFIX = "🖱️ **Scroll:** "
METADATA_HEADING = "[LOG METADATA]"
INCOMPLETE_NAME = "conversion_incomplete.json"
LOCK_NAME = ".conversion.lock"


@dataclass(frozen=True)
class DayMetrics:
    day: str
    source_file: str
    output_file: str
    source_sha256: str
    output_sha256: str
    source_bytes: int
    output_bytes: int
    byte_reduction: float
    source_sections: int
    output_context_groups: int
    projected_events: int
    rendered_event_lines: int
    exact_repeats_collapsed: int
    payload_bytes: int
    inferred_kinds: dict[str, int]
    ambiguous_blocks_preserved: int
    ambiguous_dst_timestamps: int
    merged_type_blocks: int


def _local_datetime(day: date, clock: str, zone: ZoneInfo) -> tuple[datetime, bool]:
    wall = datetime.combine(day, time.fromisoformat(clock))
    captured = wall.replace(tzinfo=zone, fold=0)
    if captured.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != wall:
        raise ValueError(f"legacy timestamp is outside timezone {zone.key}")
    alternate = wall.replace(tzinfo=zone, fold=1)
    return captured, captured.utcoffset() != alternate.utcoffset()


def _section_stamp(
    section: Section, day: date, zone: ZoneInfo
) -> tuple[datetime, str, bool]:
    match = TIMESTAMP_RE.fullmatch(section.timestamp.rstrip("\r\n"))
    if match is None:
        raise ValueError("legacy section has an invalid timestamp")
    captured, ambiguous = _local_datetime(day, match.group(1), zone)
    return captured, match.group(2) or "historical", ambiguous


def _parse_legacy_parts(text: str) -> tuple[tuple[str, ...], tuple[Section, ...]]:
    lines = tuple(io.StringIO(text))
    starts: list[int] = []
    wrapper_fence: tuple[str, int] | None = None
    wrapper_label_seen = False
    last_nonblank: str | None = None
    for index, line in enumerate(lines):
        if wrapper_fence is not None:
            if is_fence_close(line, wrapper_fence):
                wrapper_fence = None
            continue
        if wrapper_label_seen:
            wrapper_label_seen = False
            opener = fence_open_spec(line)
            if opener is not None:
                wrapper_fence = opener
                continue
        if line.rstrip("\r\n") in {SCREEN_PREFIX, CLIPBOARD_PREFIX}:
            wrapper_label_seen = True
        if (
            is_section_header(line)
            and index + 1 < len(lines)
            and is_timestamp_line(lines[index + 1])
        ):
            if last_nonblank is None or not is_separator_line(last_nonblank):
                raise ValueError("legacy section is not preceded by a separator")
            starts.append(index)
        if not is_blank(line):
            last_nonblank = line
    if wrapper_fence is not None:
        raise ValueError("legacy source has an unclosed generated event fence")
    if not starts:
        return lines, ()
    sections = tuple(
        Section(
            lines[start],
            lines[start + 1],
            list(lines[start + 2 : starts[index + 1] if index + 1 < len(starts) else len(lines)]),
        )
        for index, start in enumerate(starts)
    )
    return lines[: starts[0]], sections


def _without_final_separator(lines: Iterable[str]) -> tuple[str, ...]:
    body = tuple(lines)
    last = next((index for index in range(len(body) - 1, -1, -1) if not is_blank(body[index])), None)
    if last is not None and is_separator_line(body[last]):
        return body[:last]
    return body


def _split_event_blocks(lines: Iterable[str]) -> tuple[tuple[str, str], ...]:
    blocks: list[tuple[str, str]] = []
    current: list[str] = []
    opener: tuple[str, int] | None = None
    separator_before = ""
    separator_after = ""

    def flush() -> None:
        nonlocal separator_after
        if current:
            block = "".join(current)
            if block.endswith("\r\n"):
                block = block[:-2]
                separator_after = "\r\n"
            elif block.endswith("\n"):
                block = block[:-1]
                separator_after = "\n"
            blocks.append((block, separator_before))
            current.clear()

    for line in lines:
        if opener is not None:
            current.append(line)
            if is_fence_close(line, opener):
                opener = None
            continue
        candidate = fence_open_spec(line)
        if candidate is not None:
            if not current:
                separator_before = separator_after
                separator_after = ""
            current.append(line)
            opener = candidate
        elif is_blank(line):
            if current:
                flush()
            if blocks:
                separator_after += line
        else:
            if not current:
                separator_before = separator_after
                separator_after = ""
            current.append(line)
    flush()
    return tuple((block, separator) for block, separator in blocks if block)


def _fenced_payload(block: str, label: str) -> str | None:
    lines = block.splitlines(keepends=True)
    if len(lines) < 3 or lines[0].rstrip("\r\n") != label:
        return None
    opener = fence_open_spec(lines[1])
    if opener is None or not is_fence_close(lines[-1], opener):
        return None
    if any(is_fence_close(line, opener) for line in lines[2:-1]):
        return None
    payload = "".join(lines[2:-1])
    if payload.endswith("\r\n"):
        return payload[:-2]
    return payload[:-1] if payload.endswith("\n") else payload


def _classify_block(block: str) -> tuple[str, str, bool]:
    if "\n" not in block:
        line = block.rstrip("\r")
        if line.startswith(CLICK_PREFIX):
            return "click", line[len(CLICK_PREFIX) :], False
        if line.startswith(URL_EVENT_PREFIX):
            return "url", line[len(URL_EVENT_PREFIX) :], False
        if line.startswith(SCROLL_PREFIX):
            return "scroll", line, False
    for label, kind in (
        (SCREEN_PREFIX, "screen"),
        (CLIPBOARD_PREFIX, "clipboard"),
    ):
        if block.startswith(label):
            payload = _fenced_payload(block, label)
            if payload is not None:
                return kind, payload, False
            return "event", block, True
    return "type", block, False


def _section_events(
    section: Section,
) -> tuple[tuple[tuple[str, str], ...], int, int]:
    events: list[tuple[str, str]] = []
    ambiguous = 0
    merged_type_blocks = 0
    for block, separator in _split_event_blocks(_without_final_separator(section.body)):
        kind, payload, was_ambiguous = _classify_block(block)
        ambiguous += int(was_ambiguous)
        if kind == "type" and events and events[-1][0] == "type":
            events[-1] = ("type", events[-1][1] + separator + payload)
            merged_type_blocks += 1
        else:
            events.append((kind, payload))
    return tuple(events), ambiguous, merged_type_blocks


def _is_static_preamble(line: str) -> bool:
    stripped = line.strip()
    return not stripped or is_separator_line(line)


def project_legacy(
    text: str, day: date, zone: ZoneInfo
) -> tuple[tuple[AnalysisRecord, ...], int, int, int, int, str]:
    records: list[AnalysisRecord] = []
    preamble: list[str] = []
    preamble_lines, sections = _parse_legacy_parts(text)
    source_header_seen = False
    source_generator = "unknown"
    for value in preamble_lines:
        stripped = value.strip()
        if stripped.startswith("# Work Log "):
            match = SOURCE_HEADER_RE.fullmatch(stripped)
            if match is None or date.fromisoformat(match.group(1)) != day:
                raise ValueError("source header date does not match its filename")
            if source_header_seen:
                raise ValueError("source has more than one work-log header")
            source_header_seen = True
        elif stripped.startswith("> Auto-generated by Interleaved Logger"):
            source_generator = sanitize_markdown_inline(stripped, "unknown")
        elif not _is_static_preamble(value):
            preamble.append(value.rstrip("\r\n"))

    if not source_header_seen:
        raise ValueError("source work-log header is missing")

    metadata_base, metadata_ambiguous = _local_datetime(day, "00:00:00", zone)
    ambiguous_dst = int(metadata_ambiguous)
    for index, payload in enumerate(preamble):
        started = LOGGER_STARTED_RE.fullmatch(payload)
        if started:
            captured_at, ambiguous = _local_datetime(day, started.group(1), zone)
            ambiguous_dst += int(ambiguous)
        else:
            captured_at = metadata_base
        records.append(
            AnalysisRecord(
                METADATA_HEADING,
                "event",
                payload,
                captured_at,
                "historical",
                metadata_base,
                index == 0,
            )
        )

    group_key: tuple[str, str] | None = None
    group_at: datetime | None = None
    ambiguous = 0
    merged_type_blocks = 0
    for section in sections:
        section_at, trigger, timestamp_ambiguous = _section_stamp(section, day, zone)
        ambiguous_dst += int(timestamp_ambiguous)
        heading = sanitize_markdown_inline(section.header[3:].rstrip("\r\n"), FALLBACK_HEADING)
        events, section_ambiguous, section_merges = _section_events(section)
        ambiguous += section_ambiguous
        merged_type_blocks += section_merges
        if not events:
            continue
        next_key = (heading, trigger)
        starts_group = next_key != group_key
        if starts_group:
            group_key = next_key
            group_at = section_at
        assert group_at is not None
        for index, (kind, payload) in enumerate(events):
            records.append(
                AnalysisRecord(
                    heading,
                    kind,
                    payload,
                    section_at,
                    trigger,
                    group_at,
                    starts_group and index == 0,
                )
            )
    return (
        tuple(records),
        len(sections),
        ambiguous,
        ambiguous_dst,
        merged_type_blocks,
        source_generator,
    )


def _source_day(path: Path) -> date:
    match = SOURCE_NAME_RE.fullmatch(path.name)
    if match is None:
        raise ValueError(f"unsupported source name: {path.name}")
    return date.fromisoformat(match.group(1))


def _conversion_header(
    day: date, source_digest: str, source_generator: str, zone: ZoneInfo
) -> str:
    return (
        f"# Work Log - {day.isoformat()}\n\n"
        "> format: activitylogger-analysis-v1\n"
        "> generated locally by ActivityLogger historical-export-v1 "
        f"source-sha256={source_digest} timezone={zone.key} dst-fold=first "
        f"timestamps=legacy-section-seals kinds=inferred section-boundaries=inferred "
        f"legacy-generator="
        f"{json.dumps(source_generator, ensure_ascii=True)}\n\n"
    )


def _source_digest(source: Path) -> str:
    info = source.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise OSError(f"refusing unsafe source: {source.name}")
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def convert_file(
    source: Path,
    output_dir: Path,
    *,
    zone: ZoneInfo,
    expected_digest: str | None = None,
) -> DayMetrics:
    before = source.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid():
        raise OSError(f"refusing unsafe source: {source.name}")
    source_bytes = source.read_bytes()
    after = source.lstat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise OSError(f"source changed during conversion: {source.name}")
    day = _source_day(source)
    source_digest = hashlib.sha256(source_bytes).hexdigest()
    if expected_digest is not None and source_digest != expected_digest:
        raise OSError(f"source changed before conversion: {source.name}")
    (
        records,
        section_count,
        ambiguous,
        ambiguous_dst,
        merged_type_blocks,
        generator,
    ) = project_legacy(source_bytes.decode("utf-8"), day, zone)
    body, _heading = render_records(records)
    output_text = _conversion_header(day, source_digest, generator, zone) + body
    if parse_records(output_text) != records:
        raise ValueError(f"round-trip verification failed: {source.name}")

    output = output_dir / f"historical_analysis_{day.isoformat()}.md"
    write_text_file(str(output), (output_text,))
    info = output.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError(f"unsafe output permissions: {output.name}")
    output_bytes = output_text.encode("utf-8")
    rendered_lines = sum(line.startswith("- ") for line in body.splitlines())
    kinds = Counter(record.kind for record in records)
    return DayMetrics(
        day=day.isoformat(),
        source_file=source.name,
        output_file=output.name,
        source_sha256=source_digest,
        output_sha256=hashlib.sha256(output_bytes).hexdigest(),
        source_bytes=len(source_bytes),
        output_bytes=len(output_bytes),
        byte_reduction=1.0 - (len(output_bytes) / len(source_bytes)) if source_bytes else 0.0,
        source_sections=section_count,
        output_context_groups=sum(record.section_start for record in records),
        projected_events=len(records),
        rendered_event_lines=rendered_lines,
        exact_repeats_collapsed=len(records) - rendered_lines,
        payload_bytes=sum(len(record.payload.encode("utf-8")) for record in records),
        inferred_kinds=dict(sorted(kinds.items())),
        ambiguous_blocks_preserved=ambiguous,
        ambiguous_dst_timestamps=ambiguous_dst,
        merged_type_blocks=merged_type_blocks,
    )


def _prepare_output_dir(log_dir: Path, output_dir: Path) -> Path:
    log_root = log_dir.resolve()
    output_root = output_dir.resolve()
    if (
        output_root == log_root
        or log_root in output_root.parents
        or output_root in log_root.parents
    ):
        raise ValueError("output and live log directories must be separate trees")
    _ensure_private_dir(output_root)
    return output_root


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _remove_incomplete_marker(path: Path) -> None:
    _fsync_directory(path.parent)
    path.unlink()
    _fsync_directory(path.parent)


def _acquire_conversion_lock(output_root: Path) -> int:
    path = output_root / LOCK_NAME
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise OSError("refusing unsafe conversion lock")
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError as exc:
        os.close(fd)
        raise OSError("another historical conversion is running") from exc
    except Exception:
        os.close(fd)
        raise


def convert_completed_logs(
    log_dir: Path,
    output_dir: Path,
    *,
    today: date | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> tuple[DayMetrics, ...]:
    output_root = _prepare_output_dir(log_dir, output_dir)
    zone = ZoneInfo(timezone_name)
    lock_fd = _acquire_conversion_lock(output_root)
    try:
        cutoff = today or datetime.now(zone).date()
        sources = sorted(log_dir.glob("daily_log_????-??-??.md"))
        selected = [source for source in sources if _source_day(source) < cutoff]
        expected_outputs = {
            f"historical_analysis_{_source_day(source).isoformat()}.md"
            for source in selected
        }
        orphaned = sorted(
            path.name
            for path in output_root.glob("historical_analysis_????-??-??.md")
            if path.name not in expected_outputs
        )
        manifest = tuple((source.name, _source_digest(source)) for source in selected)
        marker = output_root / INCOMPLETE_NAME
        write_text_file(
            str(marker),
            (
                json.dumps(
                    {
                        "format": "activitylogger-historical-export-incomplete-v1",
                        "orphaned_outputs": orphaned,
                        "sources": [
                            {"file": name, "sha256": digest}
                            for name, digest in manifest
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            ),
        )
        _fsync_directory(output_root)
        if orphaned:
            raise OSError(
                "orphaned historical outputs require operator archive or deletion: "
                + ", ".join(orphaned)
            )
        results = tuple(
            convert_file(source, output_root, zone=zone, expected_digest=digest)
            for source, (_name, digest) in zip(selected, manifest)
        )
        for source, (_name, digest) in zip(selected, manifest):
            if _source_digest(source) != digest:
                raise OSError(f"source changed before summary commit: {source.name}")
        summary = {
            "format": "activitylogger-historical-export-summary-v1",
            "local_only": True,
            "section_boundaries": "inferred_from_legacy_markdown",
            "timezone": zone.key,
            "days": [asdict(result) for result in results],
        }
        source_total = sum(result.source_bytes for result in results)
        output_total = sum(result.output_bytes for result in results)
        reduction = 1.0 - (output_total / source_total) if source_total else 0.0
        write_text_file(
            str(output_root / "conversion_summary.json"),
            (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",),
        )
        write_text_file(
            str(output_root / "README.txt"),
            (
                "PRIVATE LOCAL REVIEW COPY\n\n"
                "These files are outside the live log directory and do not match the "
                "ContextAggregator daily-log filename pattern.\n"
                "Old event times were not available. Times here are legacy section-seal "
                "times. Event kinds and section boundaries were inferred from legacy "
                "Markdown. The unchanged source logs remain the raw reference.\n"
                "Ambiguous content was preserved as exact text. No LLM or network service "
                "was used.\n\n"
                f"Completed days: {len(results)}\n"
                f"Source bytes: {source_total}\n"
                f"Output bytes: {output_total}\n"
                f"Byte reduction: {reduction:.1%}\n"
                f"Legacy sections: {sum(result.source_sections for result in results)}\n"
                f"Output context groups: {sum(result.output_context_groups for result in results)}\n"
                f"Exact repeats collapsed: {sum(result.exact_repeats_collapsed for result in results)}\n"
                f"Ambiguous blocks preserved: {sum(result.ambiguous_blocks_preserved for result in results)}\n"
                f"Ambiguous DST timestamps: {sum(result.ambiguous_dst_timestamps for result in results)}\n"
                f"Merged inferred type blocks: {sum(result.merged_type_blocks for result in results)}\n",
            ),
        )
        _remove_incomplete_marker(marker)
        return results
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create private analysis-format copies of completed legacy logs."
    )
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    results = convert_completed_logs(
        args.log_dir,
        args.output_dir,
        timezone_name=args.timezone,
    )
    source_bytes = sum(result.source_bytes for result in results)
    output_bytes = sum(result.output_bytes for result in results)
    reduction = 1.0 - (output_bytes / source_bytes) if source_bytes else 0.0
    collapsed = sum(result.exact_repeats_collapsed for result in results)
    print(
        f"Converted {len(results)} completed day(s); {reduction:.1%} fewer bytes; "
        f"{collapsed} exact repeats collapsed; output: {args.output_dir.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
