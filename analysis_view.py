"""Private, reversible compact views of completed analysis-log days."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from analysis_log import (
    ANALYSIS_FORMAT_V2,
    TIMELINE_ROW_DECLARATION,
    AnalysisRecord,
    _ensure_private_dir,
    _intents_match_records,
    _records_digest,
    analysis_paths,
    analysis_format_for_day,
    intent_path,
    parse_records,
    read_intents,
    render_records_v2,
)

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "private_analysis_review"
COMPACT_FORMAT = "activitylogger-analysis-view-v1"

_DAY_RE = re.compile(r"^# Work Log - (?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})\n$")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ANALYSIS_RE = re.compile(
    r'^> source-analysis: (?P<name>".*") sha256=(?P<digest>[0-9a-f]{64})\n$'
)
_SOURCE_INTENT_RE = re.compile(
    r'^> source-intent: (?P<name>".*") sha256=(?P<digest>[0-9a-f]{64})\n$'
)
_SOURCE_RECORDS_RE = re.compile(
    r"^> source-records: count=(?P<count>[1-9][0-9]*) "
    r"sha256=(?P<digest>[0-9a-f]{64})\n$"
)
_GENERATED_LINE = "> generated locally by ActivityLogger compact-view-v1\n"
_SCOPE_LINE = (
    "> scope: derived-view; authority=source-analysis-and-intent; "
    "coverage=not-asserted\n"
)
_LEGACY_SCOPE_LINE = (
    "> scope: derived-view; authority=analysis-v1-and-intent; "
    "coverage=not-asserted\n"
)


@dataclass(frozen=True)
class ViewMetrics:
    day: str
    analysis_file: str
    intent_file: str
    output_file: str
    analysis_sha256: str
    intent_sha256: str
    output_sha256: str
    analysis_bytes: int
    output_bytes: int
    byte_reduction: float
    event_count: int
    timeline_events: int
    absolute_timeline_rows: int
    delta_timeline_rows: int


def _validate_provenance(name: str, digest: str) -> None:
    if not _SAFE_NAME_RE.fullmatch(name) or not _SHA256_RE.fullmatch(digest):
        raise ValueError("invalid compact-view provenance")


def _stable_read(path: Path) -> bytes:
    """Read one owner-only regular file and reject concurrent replacement."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_mode & 0o077
        ):
            raise OSError("refusing unsafe compact-view source")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(fd)
        if (
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise OSError("compact-view source changed during read")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _render_compact_body(
    records: Sequence[AnalysisRecord],
) -> tuple[str, int, int]:
    body, _last_heading, absolute_rows, delta_rows = render_records_v2(records)
    return body, absolute_rows, delta_rows


def render_compact_view(
    records: Sequence[AnalysisRecord],
    *,
    day: date,
    analysis_name: str,
    analysis_sha256: str,
    intent_name: str,
    intent_sha256: str,
) -> str:
    """Render a self-describing compact view and prove its exact round trip."""
    _validate_provenance(analysis_name, analysis_sha256)
    _validate_provenance(intent_name, intent_sha256)
    if any(record.section_captured_at.date() != day for record in records):
        raise ValueError("compact-view round-trip verification failed")
    body, _absolute_rows, _delta_rows = _render_compact_body(records)
    text = (
        f"# Work Log - {day.isoformat()}\n\n"
        f"> format: {COMPACT_FORMAT}\n"
        f"{TIMELINE_ROW_DECLARATION}"
        f"> source-analysis: {json.dumps(analysis_name)} sha256={analysis_sha256}\n"
        f"> source-intent: {json.dumps(intent_name)} sha256={intent_sha256}\n"
        f"> source-records: count={len(records)} sha256={_records_digest(records)}\n"
        f"{_GENERATED_LINE}"
        f"{_SCOPE_LINE}\n"
        f"{body}"
    )
    if parse_compact_records(text) != tuple(records):
        raise ValueError("compact-view round-trip verification failed")
    return text


def parse_compact_records(text: str) -> tuple[AnalysisRecord, ...]:
    """Strictly parse a compact view into the exact canonical record stream."""
    try:
        restored: list[str] = []
        day: date | None = None
        format_seen = False
        declaration_seen = False
        analysis_seen = False
        intent_seen = False
        records_seen = False
        expected_count = 0
        expected_digest = ""
        generated_seen = False
        scope_seen = False
        content_seen = False

        for line in text.splitlines(keepends=True):
            day_match = _DAY_RE.fullmatch(line)
            if day_match is not None:
                if day is not None or content_seen:
                    raise ValueError("invalid compact-view day header")
                day = date.fromisoformat(day_match.group("day"))
                restored.append(line)
                continue
            if line == f"> format: {COMPACT_FORMAT}\n":
                if format_seen or content_seen:
                    raise ValueError("invalid compact-view format header")
                format_seen = True
                restored.append(f"> format: {ANALYSIS_FORMAT_V2}\n")
                continue
            if line == TIMELINE_ROW_DECLARATION:
                if declaration_seen or content_seen:
                    raise ValueError("invalid compact-view timeline declaration")
                declaration_seen = True
                restored.append(line)
                continue
            analysis_match = _SOURCE_ANALYSIS_RE.fullmatch(line)
            if analysis_match is not None:
                if analysis_seen or content_seen:
                    raise ValueError("invalid compact-view analysis provenance")
                name = json.loads(analysis_match.group("name"))
                _validate_provenance(name, analysis_match.group("digest"))
                analysis_seen = True
                continue
            intent_match = _SOURCE_INTENT_RE.fullmatch(line)
            if intent_match is not None:
                if intent_seen or content_seen:
                    raise ValueError("invalid compact-view intent provenance")
                name = json.loads(intent_match.group("name"))
                _validate_provenance(name, intent_match.group("digest"))
                intent_seen = True
                continue
            records_match = _SOURCE_RECORDS_RE.fullmatch(line)
            if records_match is not None:
                if records_seen or content_seen:
                    raise ValueError("invalid compact-view record provenance")
                expected_count = int(records_match.group("count"))
                expected_digest = records_match.group("digest")
                records_seen = True
                continue
            if line == _GENERATED_LINE:
                if generated_seen or content_seen:
                    raise ValueError("invalid compact-view generator header")
                generated_seen = True
                restored.append(line)
                continue
            if line in {_SCOPE_LINE, _LEGACY_SCOPE_LINE}:
                if scope_seen or content_seen:
                    raise ValueError("invalid compact-view scope header")
                scope_seen = True
                continue
            if line.startswith("## "):
                content_seen = True
                restored.append(line)
                continue
            if line.startswith("### ") or line.startswith("- "):
                content_seen = True
                restored.append(line)
                continue
            if line.startswith("@"):
                content_seen = True
            restored.append(line)

        if not all(
            (
                day is not None,
                format_seen,
                declaration_seen,
                analysis_seen,
                intent_seen,
                records_seen,
                generated_seen,
                scope_seen,
            )
        ):
            raise ValueError("compact-view header is incomplete")
        records = parse_records(
            "".join(restored),
            day=day,
            expected_format=ANALYSIS_FORMAT_V2,
        )
        if len(records) != expected_count or _records_digest(records) != expected_digest:
            raise ValueError("compact-view records do not match provenance")
        return records
    except (json.JSONDecodeError, OSError, UnicodeError, ValueError, TypeError) as exc:
        raise ValueError(
            f"invalid compact view [{type(exc).__name__}]"
        ) from None


def compact_view_path(output_dir: Path, day: date) -> Path:
    return output_dir / f"compact_analysis_{day.isoformat()}.md"


def _prepare_output_dir(log_dir: Path, output_dir: Path) -> Path:
    if output_dir.is_symlink():
        raise OSError("refusing symlinked compact-view output directory")
    log_root = log_dir.resolve()
    output_root = output_dir.resolve()
    if (
        output_root == log_root
        or log_root in output_root.parents
        or output_root in log_root.parents
    ):
        raise ValueError("compact-view output must use a separate private tree")
    _ensure_private_dir(output_root)
    return output_root


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _stage_private_text(output_root: Path, name: str, text: str) -> Path:
    fd, temporary = tempfile.mkstemp(
        dir=output_root,
        prefix=f".{name}.",
        suffix=".pending",
    )
    path = Path(temporary)
    try:
        os.fchmod(fd, 0o600)
        data = text.encode("utf-8")
        offset = 0
        while offset < len(data):
            written = os.write(fd, data[offset:])
            if written <= 0:
                raise OSError("short compact-view staging write")
            offset += written
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise
    os.close(fd)
    return path


def export_compact_day(
    log_dir: Path,
    output_dir: Path,
    day: date,
    *,
    today: date | None = None,
) -> ViewMetrics:
    """Export one completed, intent-verified analysis day to a private compact view."""
    cutoff = today or datetime.now().astimezone().date()
    if day >= cutoff:
        raise ValueError("compact view requires a completed calendar day")
    output_root = _prepare_output_dir(log_dir, output_dir)
    analysis_file, invalid_file = analysis_paths(log_dir, day)
    intent_file = intent_path(log_dir, day)
    if invalid_file.exists():
        raise ValueError("analysis day has an invalid marker")

    analysis_bytes = _stable_read(analysis_file)
    intent_bytes = _stable_read(intent_file)
    analysis_digest = hashlib.sha256(analysis_bytes).hexdigest()
    intent_digest = hashlib.sha256(intent_bytes).hexdigest()
    try:
        records = parse_records(
            analysis_bytes.decode("utf-8"),
            day=day,
            expected_format=analysis_format_for_day(day),
        )
        intents = read_intents(intent_file)
    except (KeyError, OSError, UnicodeError, ValueError, TypeError) as exc:
        raise ValueError(
            f"invalid compact-view source [{type(exc).__name__}]"
        ) from None
    if not _intents_match_records(intents, records):
        raise ValueError("analysis does not match its complete intent stream")
    if _stable_read(intent_file) != intent_bytes:
        raise OSError("compact-view intent changed during validation")

    text = render_compact_view(
        records,
        day=day,
        analysis_name=analysis_file.name,
        analysis_sha256=analysis_digest,
        intent_name=intent_file.name,
        intent_sha256=intent_digest,
    )
    output = compact_view_path(output_root, day)
    if output.exists() or output.is_symlink():
        info = output.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise OSError("refusing unsafe compact-view destination")
    staged = _stage_private_text(output_root, output.name, text)
    try:
        output_bytes = _stable_read(staged)
        if parse_compact_records(output_bytes.decode("utf-8")) != records:
            raise ValueError("staged compact view failed round-trip verification")
        if (
            hashlib.sha256(_stable_read(analysis_file)).hexdigest()
            != analysis_digest
            or hashlib.sha256(_stable_read(intent_file)).hexdigest() != intent_digest
            or invalid_file.exists()
        ):
            raise OSError("compact-view source changed before commit verification")
        os.replace(staged, output)
        _fsync_directory(output_root)
    finally:
        try:
            staged.unlink()
        except FileNotFoundError:
            pass
    _body, absolute_rows, delta_rows = _render_compact_body(records)
    return ViewMetrics(
        day=day.isoformat(),
        analysis_file=analysis_file.name,
        intent_file=intent_file.name,
        output_file=output.name,
        analysis_sha256=analysis_digest,
        intent_sha256=intent_digest,
        output_sha256=hashlib.sha256(output_bytes).hexdigest(),
        analysis_bytes=len(analysis_bytes),
        output_bytes=len(output_bytes),
        byte_reduction=(
            1.0 - (len(output_bytes) / len(analysis_bytes)) if analysis_bytes else 0.0
        ),
        event_count=len(records),
        timeline_events=sum(record.trigger == "timeline" for record in records),
        absolute_timeline_rows=absolute_rows,
        delta_timeline_rows=delta_rows,
    )
