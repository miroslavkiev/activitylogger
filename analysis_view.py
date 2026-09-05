"""Private, reversible compact views of completed analysis-log days."""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import stat
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from analysis_log import (
    ANALYSIS_ONLY_START_DAY,
    ANALYSIS_FORMAT_V2,
    TIMELINE_ROW_DECLARATION,
    AnalysisRecord,
    WORKLOAD_KINDS,
    _ensure_private_dir,
    _intents_match_records,
    _json_string,
    _records_digest,
    _safe_json,
    analysis_paths,
    analysis_quality,
    analysis_format_for_day,
    intent_path,
    heartbeat_summary,
    parse_records,
    ready_path,
    read_intents,
    render_records_v2,
    validate_day_ready,
)
from operator_errors import OperatorError
from private_files import read_private_bytes

PROJECT_ROOT = Path(__file__).resolve().parent


def user_private_output_dir(*, home: Path | None = None) -> Path:
    """Return the stable per-user private review path."""
    user_home = home or Path(pwd.getpwuid(os.getuid()).pw_dir)
    return (
        user_home
        / "Library"
        / "Application Support"
        / "ActivityLogger"
        / "private_analysis_review"
    )


def default_output_dir(
    *,
    frozen: bool | None = None,
    home: Path | None = None,
) -> Path:
    """Return a stable private review path for source and bundled runs."""
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if is_frozen:
        return user_private_output_dir(home=home)
    return PROJECT_ROOT / "private_analysis_review"


DEFAULT_OUTPUT_DIR = default_output_dir()
USER_PRIVATE_OUTPUT_DIR = user_private_output_dir()
COMPACT_FORMAT = "activitylogger-analysis-view-v1"
WORKLOAD_FORMAT = "activitylogger-workload-summary-v3-pilot"
WORKLOAD_GAP_SECONDS = 10 * 60
EXACT_WORKLOAD_KINDS = WORKLOAD_KINDS - {"click"}
MARKER_KINDS = frozenset(
    {
        "focus",
        "idle_start",
        "idle_end",
        "session_start",
        "session_stop",
        "privacy_pause_start",
        "privacy_pause_end",
        "heartbeat",
    }
)
STATE_BOUNDARY_KINDS = frozenset(
    {
        "idle_start",
        "idle_end",
        "session_start",
        "session_stop",
        "privacy_pause_start",
        "privacy_pause_end",
    }
)

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
    "> scope: derived-view; authority=analysis-v1-and-intent; coverage=not-asserted\n"
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


@dataclass(frozen=True)
class WorkloadViewMetrics:
    day: str
    analysis_file: str
    intent_file: str
    ready_file: str
    output_file: str
    analysis_sha256: str
    intent_sha256: str
    ready_sha256: str
    output_sha256: str
    analysis_bytes: int
    output_bytes: int
    byte_reduction: float
    source_events: int
    workload_events: int
    exact_evidence_events: int
    click_events: int
    click_groups: int
    summarized_markers: int
    spans: int
    heartbeat_count: int
    heartbeat_first: str | None
    heartbeat_last: str | None
    max_heartbeat_gap_seconds: int
    quality: dict[str, object] = field(default_factory=dict)


def _validate_provenance(name: str, digest: str) -> None:
    if not _SAFE_NAME_RE.fullmatch(name) or not _SHA256_RE.fullmatch(digest):
        raise ValueError("invalid compact-view provenance")


def _stable_read(path: Path) -> bytes:
    """Read one owner-only regular file and reject concurrent replacement."""
    return read_private_bytes(path)


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
        if (
            len(records) != expected_count
            or _records_digest(records) != expected_digest
        ):
            raise ValueError("compact-view records do not match provenance")
        return records
    except (json.JSONDecodeError, OSError, UnicodeError, ValueError, TypeError) as exc:
        raise ValueError(f"invalid compact view [{type(exc).__name__}]") from None


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
        raise OperatorError("day_not_completed")
    output_root = _prepare_output_dir(log_dir, output_dir)
    analysis_file, invalid_file = analysis_paths(log_dir, day)
    intent_file = intent_path(log_dir, day)
    if invalid_file.exists() or invalid_file.is_symlink():
        raise OperatorError("day_unverified")

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
    except (KeyError, OSError, UnicodeError, ValueError, TypeError, RecursionError):
        raise OperatorError("day_unverified") from None
    if not _intents_match_records(intents, records):
        raise OperatorError("day_unverified")
    if _stable_read(intent_file) != intent_bytes:
        raise OperatorError("source_changed")

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
            raise OperatorError("unsafe_file")
    staged = _stage_private_text(output_root, output.name, text)
    try:
        output_bytes = _stable_read(staged)
        if parse_compact_records(output_bytes.decode("utf-8")) != records:
            raise ValueError("staged compact view failed round-trip verification")
        if (
            hashlib.sha256(_stable_read(analysis_file)).hexdigest() != analysis_digest
            or hashlib.sha256(_stable_read(intent_file)).hexdigest() != intent_digest
            or invalid_file.exists() or invalid_file.is_symlink()
        ):
            raise OperatorError("source_changed")
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


def workload_view_path(output_dir: Path, day: date) -> Path:
    return output_dir / f"v3_pilot_{day.isoformat()}.md"


def _stamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _short_stamp(value: datetime, day: date) -> str:
    if value.date() != day:
        return _stamp(value)
    return value.strftime("%H:%M:%S%z")


def _workload_string(value: str) -> str:
    return _json_string(value).replace("\u2013", "\\u2013").replace("\u2014", "\\u2014")


def _workload_spans(
    records: Sequence[AnalysisRecord],
) -> list[list[tuple[int, AnalysisRecord]]]:
    spans: list[list[tuple[int, AnalysisRecord]]] = []
    current: list[tuple[int, AnalysisRecord]] = []
    state_boundary = False
    for ordinal, record in enumerate(records, 1):
        if record.kind not in WORKLOAD_KINDS:
            state_boundary = state_boundary or record.kind in STATE_BOUNDARY_KINDS
            continue
        if current:
            previous = current[-1][1]
            gap = (record.captured_at - previous.captured_at).total_seconds()
            if (
                state_boundary
                or record.heading != previous.heading
                or gap < 0
                or gap > WORKLOAD_GAP_SECONDS
            ):
                spans.append(current)
                current = []
        current.append((ordinal, record))
        state_boundary = False
    if current:
        spans.append(current)
    return spans


def _interval_projection(
    records: Sequence[AnalysisRecord], start_kind: str, end_kind: str
) -> tuple[
    dict[str, int | bool],
    list[tuple[AnalysisRecord | None, AnalysisRecord | None]],
]:
    starts = 0
    ends = 0
    closed = 0
    unmatched_starts = 0
    unmatched_ends = 0
    invalid_order = 0
    total_seconds = 0
    opened: AnalysisRecord | None = None
    intervals: list[tuple[AnalysisRecord | None, AnalysisRecord | None]] = []
    for record in records:
        if record.kind == start_kind:
            starts += 1
            if opened is None:
                opened = record
            else:
                unmatched_starts += 1
                intervals.append((record, None))
        elif record.kind == end_kind:
            ends += 1
            if opened is None:
                unmatched_ends += 1
                intervals.append((None, record))
                continue
            duration = int((record.captured_at - opened.captured_at).total_seconds())
            if duration < 0:
                invalid_order += 1
            else:
                total_seconds += duration
                closed += 1
            intervals.append((opened, record))
            opened = None
    if opened is not None:
        intervals.append((opened, None))
    return (
        {
            "starts": starts,
            "ends": ends,
            "closed": closed,
            "open_at_end": opened is not None,
            "unmatched_starts": unmatched_starts,
            "unmatched_ends": unmatched_ends,
            "invalid_order": invalid_order,
            "closed_seconds": total_seconds,
        },
        intervals,
    )


def _marker_payload_groups(
    records: Sequence[AnalysisRecord],
) -> list[tuple[str, str, str, int, datetime, datetime]]:
    groups: dict[tuple[str, str, str], list[int | datetime]] = {}
    for record in records:
        if record.kind not in MARKER_KINDS or not record.payload:
            continue
        key = (record.kind, record.trigger, record.payload)
        group = groups.get(key)
        if group is None:
            groups[key] = [1, record.captured_at, record.captured_at]
        else:
            group[0] = int(group[0]) + 1
            group[2] = record.captured_at
    return [
        (kind, trigger, payload, int(values[0]), values[1], values[2])
        for (kind, trigger, payload), values in groups.items()
    ]


def _heartbeat_summary(
    records: Sequence[AnalysisRecord],
) -> dict[str, int | str | None]:
    return heartbeat_summary(records)


def _focus_buckets(
    records: Sequence[AnalysisRecord],
) -> list[tuple[datetime, str, int, datetime, datetime]]:
    buckets: dict[tuple[datetime, str], list[int | datetime]] = {}
    for record in records:
        if record.kind != "focus":
            continue
        hour = record.captured_at.replace(minute=0, second=0, microsecond=0)
        key = (hour, record.heading)
        bucket = buckets.get(key)
        if bucket is None:
            buckets[key] = [1, record.captured_at, record.captured_at]
        else:
            bucket[0] = int(bucket[0]) + 1
            bucket[2] = record.captured_at
    return [
        (hour, heading, int(values[0]), values[1], values[2])
        for (hour, heading), values in buckets.items()
    ]


def _click_groups(
    span: Sequence[tuple[int, AnalysisRecord]],
) -> list[tuple[int, str, int, datetime, datetime]]:
    projected: list[tuple[int, str, int, datetime, datetime]] = []
    groups: dict[str, list[int | datetime]] = {}

    def flush() -> None:
        projected.extend(
            (int(values[0]), payload, int(values[1]), values[2], values[3])
            for payload, values in groups.items()
        )
        groups.clear()

    for ordinal, record in span:
        if record.kind != "click":
            flush()
            continue
        group = groups.get(record.payload)
        if group is None:
            groups[record.payload] = [
                ordinal,
                1,
                record.captured_at,
                record.captured_at,
            ]
        else:
            group[1] = int(group[1]) + 1
            group[3] = record.captured_at
    flush()
    return projected


def _click_dictionary(
    grouped_spans: Sequence[Sequence[tuple[int, str, int, datetime, datetime]]],
) -> dict[str, str]:
    frequencies = Counter(
        payload for groups in grouped_spans for _ordinal, payload, *_rest in groups
    )
    references: dict[str, str] = {}
    for groups in grouped_spans:
        for _ordinal, payload, *_rest in groups:
            if payload in references:
                continue
            reference = f"C{len(references) + 1}"
            encoded = _workload_string(payload)
            before = frequencies[payload] * len(encoded.encode("utf-8"))
            after = len(f"- {reference}: {encoded}\n".encode("utf-8")) + (
                frequencies[payload] * len(reference)
            )
            if after < before:
                references[payload] = reference
    return references


def _render_workload_summary(
    records: Sequence[AnalysisRecord],
    *,
    day: date,
    analysis_name: str,
    analysis_sha256: str,
    intent_name: str,
    intent_sha256: str,
    ready_name: str,
    ready_sha256: str,
) -> tuple[str, dict[str, int]]:
    if not records or any(
        record.section_captured_at.date() != day for record in records
    ):
        raise ValueError("workload summary requires one non-empty source day")
    expected_names = (
        f"daily_log_{day.isoformat()}.md",
        f"analysis_intents_{day.isoformat()}.journal",
        f".daily_log_{day.isoformat()}.ready.json",
    )
    if (analysis_name, intent_name, ready_name) != expected_names:
        raise ValueError("workload-summary provenance does not match the day")
    for digest in (analysis_sha256, intent_sha256, ready_sha256):
        if not _SHA256_RE.fullmatch(digest):
            raise ValueError("invalid workload-summary provenance")
    unknown = {record.kind for record in records} - WORKLOAD_KINDS - MARKER_KINDS
    if unknown:
        raise ValueError("workload summary cannot account for every source event")

    spans = _workload_spans(records)
    grouped_spans = [_click_groups(span) for span in spans]
    exact_records = tuple(
        record for record in records if record.kind in EXACT_WORKLOAD_KINDS
    )
    source_counts = Counter(record.kind for record in records)
    click_events = source_counts["click"]
    marker_events = sum(source_counts[kind] for kind in MARKER_KINDS)
    workload_events = sum(source_counts[kind] for kind in WORKLOAD_KINDS)
    click_group_count = sum(len(groups) for groups in grouped_spans)
    accounted = len(exact_records) + click_events + marker_events
    if (
        accounted != len(records)
        or workload_events != len(exact_records) + click_events
    ):
        raise ValueError("workload summary event accounting failed")

    contexts: dict[str, dict[str, int | datetime]] = {}
    for span in spans:
        heading = span[0][1].heading
        context = contexts.setdefault(
            heading,
            {
                "spans": 0,
                "events": 0,
                "clicks": 0,
                "exact_evidence": 0,
                "focus_events": 0,
                "first": span[0][1].captured_at,
                "last": span[-1][1].captured_at,
            },
        )
        context["spans"] = int(context["spans"]) + 1
        context["events"] = int(context["events"]) + len(span)
        context["clicks"] = int(context["clicks"]) + sum(
            record.kind == "click" for _ordinal, record in span
        )
        context["exact_evidence"] = int(context["exact_evidence"]) + sum(
            record.kind in EXACT_WORKLOAD_KINDS for _ordinal, record in span
        )
        context["first"] = min(context["first"], span[0][1].captured_at)
        context["last"] = max(context["last"], span[-1][1].captured_at)

    focus_records = tuple(record for record in records if record.kind == "focus")
    focus_buckets = _focus_buckets(records)
    for record in focus_records:
        context = contexts.setdefault(
            record.heading,
            {
                "spans": 0,
                "events": 0,
                "clicks": 0,
                "exact_evidence": 0,
                "focus_events": 0,
                "first": record.captured_at,
                "last": record.captured_at,
            },
        )
        context["focus_events"] = int(context["focus_events"]) + 1
        context["first"] = min(context["first"], record.captured_at)
        context["last"] = max(context["last"], record.captured_at)

    interval_projections = {
        "privacy": _interval_projection(
            records, "privacy_pause_start", "privacy_pause_end"
        ),
        "idle": _interval_projection(records, "idle_start", "idle_end"),
        "session": _interval_projection(records, "session_start", "session_stop"),
    }
    marker_payload_records = tuple(
        record for record in records if record.kind in MARKER_KINDS and record.payload
    )
    marker_payload_groups = _marker_payload_groups(records)
    context_references = {
        heading: f"H{index}" for index, heading in enumerate(contexts, 1)
    }
    click_references = _click_dictionary(grouped_spans)
    lines = [
        f"# Workload Summary - {day.isoformat()}\n\n",
        f"> format: {WORKLOAD_FORMAT}\n",
        "> scope: derived-lossy; authority=canonical-v2-and-intent\n",
        f"> source-analysis: {_json_string(analysis_name)} sha256={analysis_sha256}\n",
        f"> source-intent: {_json_string(intent_name)} sha256={intent_sha256}\n",
        f"> source-ready: {_json_string(ready_name)} sha256={ready_sha256}\n",
        f"> source-records: count={len(records)} sha256={_records_digest(records)}\n",
        f"> span-policy: same workload heading; split at privacy, idle, session, or after {WORKLOAD_GAP_SECONDS} seconds\n",
        "> evidence-policy: non-click workload evidence exact; clicks grouped by target per span\n",
        "> caution: spans show observed activity, not exact effort duration\n\n",
        "## Loss ledger\n\n",
        f"- accounted-events: {accounted}/{len(records)}\n",
        f"- source-counts: {_safe_json(dict(sorted(source_counts.items())), compact=True)}\n",
        f"- exact-evidence: count={len(exact_records)} sha256={_records_digest(exact_records)}\n",
        f"- clicks: records={click_events} groups={click_group_count}; omitted=intermediate-times-and-cross-target-order\n",
        f"- dictionaries: contexts={len(context_references)} click-targets={len(click_references)}\n",
        f"- summarized-markers: {marker_events}\n",
        f"- focus-contexts: records={len(focus_records)} buckets={len(focus_buckets)} sha256={_records_digest(focus_records)}; omitted=intermediate-times-and-order-within-hour\n",
        f"- marker-payloads: records={len(marker_payload_records)} groups={len(marker_payload_groups)} sha256={_records_digest(marker_payload_records)}; omitted=intermediate-times\n",
        f"- omitted-source-fields: section-captured-at={len(records)} section-start={len(records)} per-record-click-and-marker-trigger-position={click_events + marker_events}\n\n",
        "## Coverage and state\n\n",
        f"- heartbeat: {_safe_json(_heartbeat_summary(records), compact=True)}\n",
        f"- focus-events: {source_counts['focus']}\n",
        f"- privacy: {_safe_json(interval_projections['privacy'][0], compact=True)}\n",
        f"- idle: {_safe_json(interval_projections['idle'][0], compact=True)}\n",
        f"- session: {_safe_json(interval_projections['session'][0], compact=True)}\n\n",
        "## State intervals\n\n",
    ]
    for label in ("privacy", "idle", "session"):
        for start, end in interval_projections[label][1]:
            start_stamp = _short_stamp(start.captured_at, day) if start else "?"
            end_stamp = _short_stamp(end.captured_at, day) if end else "open"
            suffix = ""
            if start is not None and start.payload:
                suffix += f" start-payload={_workload_string(start.payload)}"
            if end is not None and end.payload:
                suffix += f" end-payload={_workload_string(end.payload)}"
            lines.append(f"- {label} @{start_stamp}..{end_stamp}{suffix}\n")
    lines.append("\n## Other marker payloads\n\n")
    other_marker_groups = [
        group for group in marker_payload_groups if group[0] not in STATE_BOUNDARY_KINDS
    ]
    if other_marker_groups:
        for kind, trigger, payload, count, first_at, last_at in other_marker_groups:
            lines.append(
                f"- {kind}/{trigger} x{count} @{_short_stamp(first_at, day)}..{_short_stamp(last_at, day)} {_workload_string(payload)}\n"
            )
    else:
        lines.append("- none\n")
    lines.append("\n## Context dictionary\n\n")
    for heading, reference in context_references.items():
        lines.append(f"- {reference}: {_workload_string(heading)}\n")
    lines.append("\n## Focus context timeline\n\n")
    if focus_buckets:
        for hour, heading, count, first_at, last_at in focus_buckets:
            lines.append(
                f"- @{_short_stamp(hour, day)} {context_references[heading]} x{count} first={_short_stamp(first_at, day)} last={_short_stamp(last_at, day)}\n"
            )
    else:
        lines.append("- none\n")
    lines.append("\n## Click target dictionary\n\n")
    if click_references:
        for payload, reference in click_references.items():
            lines.append(f"- {reference}: {_workload_string(payload)}\n")
    else:
        lines.append("- none\n")
    lines.append("\n## Context index\n\n")
    for heading, context in contexts.items():
        entry = {
            "context": context_references[heading],
            "spans": context["spans"],
            "first": _short_stamp(context["first"], day),
            "last": _short_stamp(context["last"], day),
            "events": context["events"],
            "clicks": context["clicks"],
            "exact_evidence": context["exact_evidence"],
            "focus_events": context["focus_events"],
        }
        lines.append(f"- {_safe_json(entry, compact=True)}\n")
    lines.append("\n## Work spans\n\n")
    for span_number, (span, click_groups) in enumerate(zip(spans, grouped_spans), 1):
        first = span[0][1]
        last = span[-1][1]
        lines.append(
            f"### {span_number} @{_short_stamp(first.captured_at, day)}..{_short_stamp(last.captured_at, day)} {context_references[first.heading]}\n"
        )
        entries: list[tuple[int, str]] = []
        for ordinal, record in span:
            if record.kind in EXACT_WORKLOAD_KINDS:
                entries.append(
                    (
                        ordinal,
                        f"- @{_short_stamp(record.captured_at, day)} {record.kind}/{record.trigger} {_workload_string(record.payload)}\n",
                    )
                )
        for ordinal, payload, count, first_at, last_at in click_groups:
            target = click_references.get(payload, _workload_string(payload))
            times = _short_stamp(first_at, day)
            if last_at != first_at:
                times += f"..{_short_stamp(last_at, day)}"
            entries.append(
                (
                    ordinal,
                    f"- click {target} x{count} @{times}\n",
                )
            )
        lines.extend(
            text for _ordinal, text in sorted(entries, key=lambda item: item[0])
        )
        lines.append("\n")
    text = "".join(lines)
    return text, {
        "workload_events": workload_events,
        "exact_evidence_events": len(exact_records),
        "click_events": click_events,
        "click_groups": click_group_count,
        "summarized_markers": marker_events,
        "spans": len(spans),
    }


def render_workload_summary(
    records: Sequence[AnalysisRecord],
    *,
    day: date,
    analysis_name: str,
    analysis_sha256: str,
    intent_name: str,
    intent_sha256: str,
    ready_name: str,
    ready_sha256: str,
) -> str:
    text, _metrics = _render_workload_summary(
        records,
        day=day,
        analysis_name=analysis_name,
        analysis_sha256=analysis_sha256,
        intent_name=intent_name,
        intent_sha256=intent_sha256,
        ready_name=ready_name,
        ready_sha256=ready_sha256,
    )
    return text


def export_workload_day(
    log_dir: Path,
    output_dir: Path,
    day: date,
    *,
    today: date | None = None,
) -> WorkloadViewMetrics:
    """Export one completed canonical v2 day to a private lossy workload view."""
    cutoff = today or datetime.now().astimezone().date()
    if day >= cutoff:
        raise OperatorError("day_not_completed")
    if day < ANALYSIS_ONLY_START_DAY:
        raise OperatorError("unsupported_format")
    output_root = _prepare_output_dir(log_dir, output_dir)
    analysis_file, invalid_file = analysis_paths(log_dir, day)
    intent_file = intent_path(log_dir, day)
    proof_file = ready_path(log_dir, day)
    if invalid_file.exists() or invalid_file.is_symlink() or not validate_day_ready(log_dir, day):
        raise OperatorError("incomplete_window")

    analysis_bytes = _stable_read(analysis_file)
    intent_bytes = _stable_read(intent_file)
    ready_bytes = _stable_read(proof_file)
    digests = tuple(
        hashlib.sha256(data).hexdigest()
        for data in (analysis_bytes, intent_bytes, ready_bytes)
    )
    try:
        records = parse_records(
            analysis_bytes.decode("utf-8"),
            day=day,
            expected_format=ANALYSIS_FORMAT_V2,
        )
        intents = read_intents(intent_file)
    except (KeyError, OSError, UnicodeError, ValueError, TypeError, RecursionError):
        raise OperatorError("day_unverified") from None
    if not _intents_match_records(intents, records):
        raise OperatorError("day_unverified")

    text, metrics = _render_workload_summary(
        records,
        day=day,
        analysis_name=analysis_file.name,
        analysis_sha256=digests[0],
        intent_name=intent_file.name,
        intent_sha256=digests[1],
        ready_name=proof_file.name,
        ready_sha256=digests[2],
    )
    output = workload_view_path(output_root, day)
    if output.exists() or output.is_symlink():
        info = output.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            raise OperatorError("unsafe_file")
    staged = _stage_private_text(output_root, output.name, text)
    try:
        output_bytes = _stable_read(staged)
        if output_bytes != text.encode("utf-8"):
            raise ValueError("staged workload summary differs from its projection")
        if not validate_day_ready(log_dir, day):
            raise OperatorError("source_changed")
        current = tuple(
            hashlib.sha256(_stable_read(path)).hexdigest()
            for path in (analysis_file, intent_file, proof_file)
        )
        if current != digests or invalid_file.exists() or invalid_file.is_symlink():
            raise OperatorError("source_changed")
        os.replace(staged, output)
        _fsync_directory(output_root)
    finally:
        try:
            staged.unlink()
        except FileNotFoundError:
            pass
    heartbeat = _heartbeat_summary(records)
    return WorkloadViewMetrics(
        day=day.isoformat(),
        analysis_file=analysis_file.name,
        intent_file=intent_file.name,
        ready_file=proof_file.name,
        output_file=output.name,
        analysis_sha256=digests[0],
        intent_sha256=digests[1],
        ready_sha256=digests[2],
        output_sha256=hashlib.sha256(output_bytes).hexdigest(),
        analysis_bytes=len(analysis_bytes),
        output_bytes=len(output_bytes),
        byte_reduction=(
            1.0 - (len(output_bytes) / len(analysis_bytes)) if analysis_bytes else 0.0
        ),
        source_events=len(records),
        workload_events=metrics["workload_events"],
        exact_evidence_events=metrics["exact_evidence_events"],
        click_events=metrics["click_events"],
        click_groups=metrics["click_groups"],
        summarized_markers=metrics["summarized_markers"],
        spans=metrics["spans"],
        heartbeat_count=int(heartbeat["count"]),
        heartbeat_first=heartbeat["first"],
        heartbeat_last=heartbeat["last"],
        max_heartbeat_gap_seconds=int(heartbeat["max_gap_seconds"]),
        quality=analysis_quality(records, source_bytes=len(analysis_bytes)),
    )
