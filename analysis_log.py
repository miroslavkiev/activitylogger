"""Deterministic, lossless analysis-log projection and durable persistence."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence

from markdown_format import CAPTURE_TRIGGERS, sanitize_markdown_inline
from window_titles import FALLBACK_HEADING


EVENT_KINDS = frozenset(
    {
        "type",
        "click",
        "clipboard",
        "screen",
        "url",
        "scroll",
        "focus",
        "idle_start",
        "idle_end",
        "session_start",
        "session_stop",
        "privacy_pause_start",
        "privacy_pause_end",
        "heartbeat",
        "event",
    }
)
ANALYSIS_TRIGGERS = CAPTURE_TRIGGERS | {"historical", "timeline"}
ANALYSIS_FORMAT_V1 = "activitylogger-analysis-v1"
ANALYSIS_FORMAT_V2 = "activitylogger-analysis-v2"
ANALYSIS_V2_START_DAY = date(2026, 8, 25)
ANALYSIS_ONLY_START_DAY = date(2026, 8, 27)
AUTHORITATIVE_TRANSACTION_SCHEMA = "activitylogger-authoritative-transaction-v1"
READY_PROOF_SCHEMA = "activitylogger-analysis-ready-v1"
# Large enough for an exceptional flush, bounded to reject hostile local files.
MAX_PENDING_MANIFEST_BYTES = 512 * 1024 * 1024
TIMELINE_ROW_DECLARATION = (
    "> timeline-row: @HH:MM:SS+ZZZZ|@+seconds kind [json-string]\n"
)
MAX_TIMELINE_DELTA_SECONDS = 900
TIMELINE_KINDS = frozenset(
    {
        "focus",
        "heartbeat",
        "idle_start",
        "idle_end",
        "privacy_pause_start",
        "privacy_pause_end",
        "session_start",
        "session_stop",
    }
)
HEADER_END = "<!-- header-end -->\n"
_END_RE = re.compile(br"<!-- batch-end id=[0-9a-f]+ sha256=[0-9a-f]{64} -->\n")
_START_RE = re.compile(
    br"<!-- batch-start id=([0-9a-f]+) count=([0-9]+) sha256=([0-9a-f]{64}) -->\n"
)
_RECORD_RE = re.compile(
    r"^- (?P<kind>[a-z_]+)(?: x(?P<count>[1-9][0-9]*))?"
    r"(?: @(?P<times>[^ ]+))?: (?P<payload>.+)\n$"
)
_SECTION_RE = re.compile(
    r"^### (?P<captured_at>[0-9:]+[+-][0-9]{4}) (?P<trigger>[a-z_]+)\n$"
)
_DAY_RE = re.compile(r"^# Work Log - (?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})\n$")
_OFFSET_RE = re.compile(r"^> utc-offset: (?P<offset>[+-][0-9]{4})\n$")
_ABSOLUTE_TIME_RE = re.compile(r"^[0-9]{2}:[0-9]{2}:[0-9]{2}[+-][0-9]{4}$")
_TIMELINE_ROW_RE = re.compile(
    r"^@(?P<time>(?:[0-9]{2}:[0-9]{2}:[0-9]{2}[+-][0-9]{4}|\+[0-9]+)) "
    r"(?P<kind>[a-z_]+)(?: (?P<payload>\".*\"))?\n$"
)


class CapturedEvent(str):
    """A legacy-compatible string with immutable analysis metadata."""

    def __new__(
        cls,
        legacy: str,
        *,
        kind: str,
        payload: str,
        captured_at: datetime | None = None,
        sequence: int | None = None,
    ) -> "CapturedEvent":
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind: {kind!r}")
        obj = super().__new__(cls, legacy)
        object.__setattr__(obj, "kind", kind)
        object.__setattr__(obj, "payload", payload)
        object.__setattr__(obj, "captured_at", captured_at or datetime.now().astimezone())
        object.__setattr__(obj, "sequence", sequence)
        return obj

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("CapturedEvent is immutable")


@dataclass(frozen=True)
class EventSnapshot:
    kind: str
    payload: str
    legacy: str
    captured_at: datetime
    sequence: int | None = None


@dataclass(frozen=True)
class SectionSnapshot:
    heading: str
    timestamp: str
    captured_at: datetime
    trigger: str
    events: tuple[EventSnapshot, ...]
    analysis_only: bool = False
    analysis_order: int = 0


@dataclass(frozen=True)
class AnalysisRecord:
    heading: str
    kind: str
    payload: str
    captured_at: datetime
    trigger: str
    section_captured_at: datetime
    section_start: bool
    order: int = field(default=0, compare=False, repr=False)
    section_key: int = field(default=0, compare=False, repr=False)


@dataclass(frozen=True)
class FramedBatch:
    batch_id: str
    count: int
    body: str


@dataclass(frozen=True)
class TrialValidation:
    ok: bool
    errors: tuple[str, ...]
    event_count: int
    legacy_bytes: int
    analysis_bytes: int
    byte_reduction: float
    coverage_hours: float
    max_heartbeat_gap_hours: float


def snapshot_sections(sections: Iterable[dict]) -> tuple[SectionSnapshot, ...]:
    """Copy the allowlisted fields needed by both output formats."""
    snapshots: list[SectionSnapshot] = []
    for section in sections:
        captured_at = section.get("captured_at")
        if not isinstance(captured_at, datetime):
            captured_at = datetime.now().astimezone()
        trigger = section.get("_trigger") or section.get("trigger") or "unknown"
        if trigger not in ANALYSIS_TRIGGERS:
            trigger = "unknown"
        events: list[EventSnapshot] = []
        for event in tuple(section.get("events", ())):
            event_at = getattr(event, "captured_at", captured_at)
            if not isinstance(event_at, datetime):
                event_at = captured_at
            kind = getattr(event, "kind", "event")
            if kind not in EVENT_KINDS:
                kind = "event"
            events.append(
                EventSnapshot(
                    kind=kind,
                    payload=str(getattr(event, "payload", event)),
                    legacy=str(event),
                    captured_at=event_at,
                    sequence=getattr(event, "sequence", None),
                )
            )
        snapshots.append(
            SectionSnapshot(
                heading=sanitize_markdown_inline(section.get("heading"), FALLBACK_HEADING),
                timestamp=str(section.get("timestamp") or captured_at.strftime("%H:%M:%S")),
                captured_at=captured_at,
                trigger=trigger,
                events=tuple(events),
                analysis_only=section.get("analysis_only") is True,
                analysis_order=int(section.get("_analysis_order") or 0),
            )
        )
    return tuple(snapshots)


def records_from_sections(sections: Sequence[SectionSnapshot]) -> tuple[AnalysisRecord, ...]:
    unordered: list[AnalysisRecord] = []
    for section_key, section in enumerate(sections, start=1):
        for index, event in enumerate(section.events):
            unordered.append(
                AnalysisRecord(
                    section.heading,
                    event.kind,
                    event.payload,
                    event.captured_at.replace(microsecond=0),
                    section.trigger,
                    section.captured_at.replace(microsecond=0),
                    False,
                    event.sequence or section.analysis_order + index,
                    section_key,
                )
            )
    unordered.sort(key=lambda record: record.order)
    prior_section = 0
    ordered: list[AnalysisRecord] = []
    for record in unordered:
        ordered.append(replace(record, section_start=record.section_key != prior_section))
        prior_section = record.section_key
    return tuple(ordered)


def _safe_json(value: object, *, compact: bool = False) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":") if compact else None,
        )
        .replace("\u0085", "\\u0085")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _json_string(value: str) -> str:
    return _safe_json(value)


def _records_digest(records: Sequence[AnalysisRecord]) -> str:
    canonical = "".join(_safe_json(_record_row(record), compact=True) for record in records)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def render_records(
    records: Sequence[AnalysisRecord], last_heading: str | None = None
) -> tuple[str, str | None]:
    """Render adjacent exact duplicates as one reversible record."""
    lines: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        if record.heading != last_heading:
            lines.append(f"## {record.heading}\n")
            last_heading = record.heading
        if record.section_start:
            lines.append(
                f"### {record.section_captured_at.strftime('%H:%M:%S%z')} {record.trigger}\n"
            )
        end = index + 1
        while end < len(records):
            candidate = records[end]
            if candidate.section_start or (
                candidate.section_captured_at != record.section_captured_at
                or candidate.trigger != record.trigger
                or (candidate.heading, candidate.kind, candidate.payload)
                != (record.heading, record.kind, record.payload)
            ):
                break
            end += 1
        run = records[index:end]
        count = f" x{len(run)}" if len(run) > 1 else ""
        times = ""
        if any(item.captured_at != record.section_captured_at for item in run):
            encoded_times: list[str] = []
            for item in run:
                if item.captured_at.utcoffset() != record.section_captured_at.utcoffset():
                    encoded_times.append("!" + item.captured_at.isoformat())
                else:
                    delta = int(
                        (item.captured_at - record.section_captured_at).total_seconds()
                    )
                    encoded_times.append(f"{delta:+d}")
            times = " @" + ",".join(encoded_times)
        lines.append(f"- {record.kind}{count}{times}: {_json_string(record.payload)}\n")
        index = end
    return "".join(lines), last_heading


def analysis_format_for_day(day: date) -> str:
    """Return the single analysis format allowed for a calendar day."""
    return ANALYSIS_FORMAT_V2 if day >= ANALYSIS_V2_START_DAY else ANALYSIS_FORMAT_V1


def _can_inline_timeline(
    records: Sequence[AnalysisRecord], index: int
) -> bool:
    record = records[index]
    return (
        record.trigger == "timeline"
        and record.kind in TIMELINE_KINDS
        and record.section_start
        and record.section_captured_at == record.captured_at
        and (index + 1 == len(records) or records[index + 1].section_start)
    )


def render_records_v2(
    records: Sequence[AnalysisRecord], last_heading: str | None = None
) -> tuple[str, str | None, int, int]:
    """Render one independently anchored v2 append batch."""
    lines: list[str] = []
    previous_timeline: AnalysisRecord | None = None
    absolute_rows = 0
    delta_rows = 0
    index = 0
    while index < len(records):
        record = records[index]
        if record.heading != last_heading:
            lines.append(f"## {record.heading}\n")
            last_heading = record.heading
            previous_timeline = None

        if _can_inline_timeline(records, index):
            delta: int | None = None
            if (
                previous_timeline is not None
                and previous_timeline.heading == record.heading
                and previous_timeline.captured_at.utcoffset()
                == record.captured_at.utcoffset()
            ):
                delta = int(
                    (record.captured_at - previous_timeline.captured_at).total_seconds()
                )
            if delta is not None and 0 <= delta <= MAX_TIMELINE_DELTA_SECONDS:
                time_spec = f"+{delta}"
                delta_rows += 1
            else:
                time_spec = record.captured_at.strftime("%H:%M:%S%z")
                absolute_rows += 1
            payload = "" if record.payload == "" else f" {_json_string(record.payload)}"
            lines.append(f"@{time_spec} {record.kind}{payload}\n")
            previous_timeline = record
            index += 1
            continue

        end = index + 1
        while end < len(records) and not _can_inline_timeline(records, end):
            end += 1
        body, last_heading = render_records(records[index:end], last_heading)
        lines.append(body)
        previous_timeline = None
        index = end
    return "".join(lines), last_heading, absolute_rows, delta_rows


def _parse_v1_records(
    text: str, *, day: date | None = None, strict: bool = True
) -> tuple[AnalysisRecord, ...]:
    """Expand an analysis log into its exact ordered event records."""
    expected_day = day
    heading: str | None = None
    section_at: datetime | None = None
    trigger: str | None = None
    section_first = False
    format_seen = False
    generated_seen = False
    day_seen = False
    content_seen = False
    heading_pending = False
    section_pending = False
    records: list[AnalysisRecord] = []
    for line in text.splitlines(keepends=True):
        day_match = _DAY_RE.fullmatch(line)
        if day_match is not None:
            if strict and (content_seen or day_seen):
                raise ValueError("analysis day header is misplaced or repeated")
            declared_day = date.fromisoformat(day_match.group("day"))
            if expected_day is not None and declared_day != expected_day:
                raise ValueError("analysis day header does not match the expected day")
            day = declared_day
            day_seen = True
            continue
        if _OFFSET_RE.fullmatch(line) is not None:
            continue
        if line == f"> format: {ANALYSIS_FORMAT_V1}\n":
            if content_seen or format_seen:
                raise ValueError("analysis format header is misplaced or repeated")
            format_seen = True
            continue
        if line.startswith("> generated locally by ActivityLogger "):
            if content_seen or generated_seen:
                raise ValueError("analysis generator header is misplaced or repeated")
            generated_seen = True
            continue
        if not line.strip():
            continue
        if line.startswith("## "):
            if section_pending:
                raise ValueError("analysis section has no records")
            heading = line[3:].rstrip("\r\n")
            content_seen = True
            heading_pending = True
            continue
        if line.startswith("### "):
            if section_pending:
                raise ValueError("analysis section has no records")
            match = _SECTION_RE.fullmatch(line)
            if match is None:
                raise ValueError(f"invalid analysis section: {line.rstrip()!r}")
            trigger = match.group("trigger")
            if trigger not in ANALYSIS_TRIGGERS:
                raise ValueError(f"unknown analysis trigger: {trigger!r}")
            if day is None:
                raise ValueError("analysis date is missing")
            section_at = datetime.strptime(
                f"{day.isoformat()} {match.group('captured_at')}",
                "%Y-%m-%d %H:%M:%S%z",
            )
            section_first = True
            heading_pending = False
            section_pending = True
            continue
        if not line.startswith("- "):
            if strict:
                raise ValueError(f"unexpected analysis line: {line.rstrip()!r}")
            continue
        match = _RECORD_RE.fullmatch(line)
        if match is None or heading is None or section_at is None or trigger is None:
            raise ValueError(f"invalid analysis record: {line.rstrip()!r}")
        payload = json.loads(match.group("payload"))
        if not isinstance(payload, str):
            raise ValueError("analysis payload must be a JSON string")
        expected = int(match.group("count") or "1")
        if match.group("kind") not in EVENT_KINDS:
            raise ValueError(f"unknown analysis event kind: {match.group('kind')!r}")
        raw_times = match.group("times")
        if raw_times is None:
            times = [section_at] * expected
        else:
            times = [
                datetime.fromisoformat(raw[1:])
                if raw.startswith("!")
                else section_at + timedelta(seconds=int(raw))
                for raw in raw_times.split(",")
            ]
        if len(times) != expected:
            raise ValueError("analysis repeat count does not match timestamps")
        for captured_at in times:
            records.append(
                AnalysisRecord(
                    heading=heading,
                    kind=match.group("kind"),
                    payload=payload,
                    captured_at=captured_at,
                    trigger=trigger,
                    section_captured_at=section_at,
                    section_start=section_first,
                )
            )
            section_first = False
            section_pending = False
    if strict and not format_seen:
        raise ValueError("analysis format header is missing")
    if strict and not generated_seen:
        raise ValueError("analysis generator header is missing")
    if strict and not day_seen:
        raise ValueError("analysis day header is missing")
    if strict and (heading_pending or section_pending):
        raise ValueError("analysis file has an incomplete content tail")
    return tuple(records)


def _declared_analysis_format(text: str) -> str | None:
    declared = [
        line[len("> format: ") :].rstrip("\r\n")
        for line in text.splitlines(keepends=True)
        if line.startswith("> format: ")
    ]
    if not declared:
        return None
    if len(declared) != 1 or declared[0] not in {
        ANALYSIS_FORMAT_V1,
        ANALYSIS_FORMAT_V2,
    }:
        raise ValueError("analysis format header is unknown or repeated")
    return declared[0]


def _parse_v2_records(
    text: str, *, expected_day: date | None = None
) -> tuple[AnalysisRecord, ...]:
    restored: list[str] = []
    day: date | None = None
    heading_seen = False
    previous_timeline_at: datetime | None = None
    format_seen = False
    declaration_seen = False
    generated_seen = False
    content_seen = False
    for line in text.splitlines(keepends=True):
        day_match = _DAY_RE.fullmatch(line)
        if day_match is not None:
            if day is not None or content_seen:
                raise ValueError("analysis v2 day header is misplaced or repeated")
            day = date.fromisoformat(day_match.group("day"))
            if expected_day is not None and day != expected_day:
                raise ValueError("analysis day header does not match the expected day")
            restored.append(line)
            continue
        if line == f"> format: {ANALYSIS_FORMAT_V2}\n":
            if format_seen or content_seen:
                raise ValueError("analysis v2 format header is misplaced or repeated")
            format_seen = True
            restored.append(f"> format: {ANALYSIS_FORMAT_V1}\n")
            continue
        if line == TIMELINE_ROW_DECLARATION:
            if declaration_seen or content_seen:
                raise ValueError("analysis v2 timeline declaration is misplaced or repeated")
            declaration_seen = True
            continue
        if line.startswith("> generated locally by ActivityLogger "):
            if generated_seen or content_seen:
                raise ValueError("analysis v2 generator header is misplaced or repeated")
            generated_seen = True
            restored.append(line)
            continue
        if line.startswith("## "):
            content_seen = True
            heading_seen = True
            previous_timeline_at = None
            restored.append(line)
            continue
        if line.startswith("### ") or line.startswith("- "):
            content_seen = True
            previous_timeline_at = None
            restored.append(line)
            continue
        row = _TIMELINE_ROW_RE.fullmatch(line)
        if row is not None:
            if not heading_seen or day is None:
                raise ValueError("analysis v2 timeline row has no heading or day")
            kind = row.group("kind")
            if kind not in TIMELINE_KINDS:
                raise ValueError("unknown analysis v2 timeline kind")
            time_spec = row.group("time")
            if time_spec.startswith("+"):
                seconds = int(time_spec[1:])
                if (
                    previous_timeline_at is None
                    or seconds > MAX_TIMELINE_DELTA_SECONDS
                ):
                    raise ValueError("invalid analysis v2 timeline delta")
                captured_at = previous_timeline_at + timedelta(seconds=seconds)
            else:
                if not _ABSOLUTE_TIME_RE.fullmatch(time_spec):
                    raise ValueError("invalid analysis v2 absolute time")
                captured_at = datetime.strptime(
                    f"{day.isoformat()} {time_spec}", "%Y-%m-%d %H:%M:%S%z"
                )
            if captured_at.date() != day:
                raise ValueError("analysis v2 timeline row is outside its day")
            payload_text = row.group("payload")
            payload = json.loads(payload_text) if payload_text is not None else ""
            if not isinstance(payload, str):
                raise ValueError("analysis v2 payload is not a string")
            restored.append(
                f"### {captured_at.strftime('%H:%M:%S%z')} timeline\n"
                f"- {kind}: {_json_string(payload)}\n"
            )
            previous_timeline_at = captured_at
            content_seen = True
            continue
        restored.append(line)
    if not all((day is not None, format_seen, declaration_seen, generated_seen)):
        raise ValueError("analysis v2 header is incomplete")
    return _parse_v1_records("".join(restored), day=expected_day)


def parse_records(
    text: str,
    *,
    day: date | None = None,
    strict: bool = True,
    expected_format: str | None = None,
) -> tuple[AnalysisRecord, ...]:
    """Expand a strict v1 or v2 analysis document into exact records."""
    if expected_format not in {None, ANALYSIS_FORMAT_V1, ANALYSIS_FORMAT_V2}:
        raise ValueError("unknown expected analysis format")
    declared = _declared_analysis_format(text)
    if expected_format is not None and declared != expected_format:
        raise ValueError("analysis format does not match the expected day format")
    if declared == ANALYSIS_FORMAT_V2:
        if not strict:
            raise ValueError("analysis v2 requires strict document parsing")
        return _parse_v2_records(text, expected_day=day)
    if declared is None and expected_format == ANALYSIS_FORMAT_V2:
        raise ValueError("analysis v2 format header is missing")
    return _parse_v1_records(text, day=day, strict=strict)


def read_batches(path: Path) -> tuple[FramedBatch, ...]:
    """Read and verify every committed batch in one shadow file."""
    data = path.read_bytes()
    header_end = data.find(HEADER_END.encode("utf-8"))
    if header_end < 0:
        raise ValueError("missing shadow header terminator")
    position = header_end + len(HEADER_END.encode("utf-8"))
    batches: list[FramedBatch] = []
    while position < len(data):
        start = _START_RE.match(data, position)
        if start is None:
            raise ValueError("invalid shadow batch start")
        batch_id = start.group(1).decode("ascii")
        count = int(start.group(2))
        digest = start.group(3).decode("ascii")
        end_marker = f"<!-- batch-end id={batch_id} sha256={digest} -->\n".encode()
        body_end = data.find(end_marker, start.end())
        if body_end < 0:
            raise ValueError("incomplete shadow batch")
        body = data[start.end() : body_end]
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("shadow batch digest mismatch")
        batches.append(FramedBatch(batch_id, count, body.decode("utf-8")))
        position = body_end + len(end_marker)
    return tuple(batches)


def read_intents(path: Path) -> tuple[tuple[str, int, str], ...]:
    intents: list[tuple[str, int, str]] = []
    for batch in read_batches(path):
        rows = batch.body.splitlines()
        if len(rows) != 1:
            raise ValueError("intent batch must contain one row")
        row = json.loads(rows[0])
        item = (row["batch_id"], row["count"], row["records_sha256"])
        if item[0] != batch.batch_id or item[1] != batch.count:
            raise ValueError("intent batch identity mismatch")
        intents.append(item)
    return tuple(intents)


def _intents_match_records(
    intents: Sequence[tuple[str, int, str]], records: Sequence[AnalysisRecord]
) -> bool:
    offset = 0
    for _batch_id, count, digest in intents:
        batch = records[offset : offset + count]
        if len(batch) != count or _records_digest(batch) != digest:
            return False
        offset += count
    return offset == len(records)


def validate_trial(
    log_dir: Path,
    day: date,
    *,
    today: date | None = None,
    min_byte_reduction: float = 0.15,
    min_coverage_hours: float = 20.0,
    max_heartbeat_gap_hours: float = 2.0,
) -> TrialValidation:
    """Apply the programmatic day-end gates used before format cutover."""
    analysis_path, invalid_path = shadow_paths(log_dir, day)
    legacy_path = log_dir / f"daily_log_{day.isoformat()}.md"
    errors: list[str] = []
    coverage_hours = 0.0
    observed_max_gap = 0.0
    if day >= (today or datetime.now().astimezone().date()):
        errors.append("calendar day is not complete")
    for label, path in (
        ("legacy", legacy_path),
        ("analysis", analysis_path),
        ("intent", intent_path(log_dir, day)),
    ):
        if not path.is_file():
            errors.append(f"missing {label} file")
    if invalid_path.exists():
        errors.append("invalid marker exists")
    journal_records: tuple[AnalysisRecord, ...] = ()
    if not errors:
        try:
            intents = read_intents(intent_path(log_dir, day))
            projected = parse_records(
                analysis_path.read_text(encoding="utf-8"),
                day=day,
                expected_format=analysis_format_for_day(day),
            )
            if not _intents_match_records(intents, projected):
                errors.append("analysis differs from intents")
            starts = sum(record.kind == "session_start" for record in projected)
            stops = sum(record.kind == "session_stop" for record in projected)
            if starts != stops:
                errors.append("session markers are unbalanced")
            heartbeats = sorted(
                record.captured_at
                for record in projected
                if record.kind == "heartbeat"
            )
            if len(heartbeats) >= 2:
                coverage_hours = (
                    heartbeats[-1] - heartbeats[0]
                ).total_seconds() / 3600
                day_start = datetime.combine(
                    day, datetime.min.time(), tzinfo=heartbeats[0].tzinfo
                )
                day_end = datetime.combine(
                    day + timedelta(days=1),
                    datetime.min.time(),
                    tzinfo=heartbeats[-1].tzinfo,
                )
                gaps = [
                    max(0.0, (heartbeats[0] - day_start).total_seconds() / 3600),
                    max(0.0, (day_end - heartbeats[-1]).total_seconds() / 3600),
                ]
                gaps.extend(
                    (right - left).total_seconds() / 3600
                    for left, right in zip(heartbeats, heartbeats[1:])
                )
                observed_max_gap = max(gaps)
            if min_coverage_hours > 0:
                if starts or stops:
                    errors.append("session changed during trial day")
                if coverage_hours < min_coverage_hours:
                    errors.append(
                        f"heartbeat coverage {coverage_hours:.1f}h is below "
                        f"{min_coverage_hours:.1f}h"
                    )
                next_analysis, next_invalid = shadow_paths(
                    log_dir, day + timedelta(days=1)
                )
                if next_invalid.exists():
                    errors.append("next-day invalid marker exists")
                elif not next_analysis.is_file():
                    errors.append("missing next-day heartbeat proof")
                elif not intent_path(log_dir, day + timedelta(days=1)).is_file():
                    errors.append("missing next-day intent proof")
                else:
                    next_day = day + timedelta(days=1)
                    next_records = parse_records(
                        next_analysis.read_text(encoding="utf-8"),
                        day=next_day,
                        expected_format=analysis_format_for_day(next_day),
                    )
                    next_intents = read_intents(
                        intent_path(log_dir, day + timedelta(days=1))
                    )
                    if not _intents_match_records(next_intents, next_records):
                        errors.append("next-day analysis differs from intents")
                        next_records = ()
                    proof_index = next(
                        (
                            index
                            for index, record in enumerate(next_records)
                            if record.kind == "heartbeat"
                        ),
                        None,
                    )
                    if proof_index is None:
                        errors.append("missing next-day heartbeat proof")
                    else:
                        next_heartbeat = next_records[proof_index].captured_at
                        if any(
                            record.kind in {"session_start", "session_stop"}
                            for record in next_records[: proof_index + 1]
                        ):
                            errors.append(
                                "next-day session changed before heartbeat proof"
                            )
                        next_boundary = datetime.combine(
                            day + timedelta(days=1),
                            datetime.min.time(),
                            tzinfo=next_heartbeat.tzinfo,
                        )
                        next_gap = (
                            next_heartbeat - next_boundary
                        ).total_seconds() / 3600
                        if next_gap < 0 or next_gap > max_heartbeat_gap_hours:
                            errors.append(
                                f"next-day heartbeat gap {next_gap:.1f}h exceeds "
                                f"{max_heartbeat_gap_hours:.1f}h"
                            )
                        elif heartbeats:
                            observed_max_gap = max(
                                observed_max_gap,
                                (
                                    next_heartbeat - heartbeats[-1]
                                ).total_seconds()
                                / 3600,
                            )
                if observed_max_gap > max_heartbeat_gap_hours:
                    errors.append(
                        f"heartbeat gap {observed_max_gap:.1f}h exceeds "
                        f"{max_heartbeat_gap_hours:.1f}h"
                    )
            journal_records = projected
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"trial parse failed: {type(exc).__name__}")
    legacy_bytes = legacy_path.stat().st_size if legacy_path.is_file() else 0
    analysis_bytes = analysis_path.stat().st_size if analysis_path.is_file() else 0
    reduction = 1.0 - (analysis_bytes / legacy_bytes) if legacy_bytes else 0.0
    if legacy_bytes and reduction < min_byte_reduction:
        errors.append(
            f"byte reduction {reduction:.1%} is below {min_byte_reduction:.1%}"
        )
    return TrialValidation(
        ok=not errors,
        errors=tuple(errors),
        event_count=len(journal_records),
        legacy_bytes=legacy_bytes,
        analysis_bytes=analysis_bytes,
        byte_reduction=reduction,
        coverage_hours=coverage_hours,
        max_heartbeat_gap_hours=observed_max_gap,
    )


def shadow_paths(log_dir: Path, day: date) -> tuple[Path, Path]:
    root = log_dir / "analysis_shadow"
    stamp = day.isoformat()
    return (
        root / f"analysis_log_{stamp}.md",
        root / f"analysis_invalid_{stamp}.txt",
    )


def analysis_paths(log_dir: Path, day: date) -> tuple[Path, Path]:
    """Resolve the active analysis document without moving historical files."""
    _shadow, invalid = shadow_paths(log_dir, day)
    if day >= ANALYSIS_ONLY_START_DAY:
        return log_dir / f"daily_log_{day.isoformat()}.md", invalid
    return _shadow, invalid


def intent_path(log_dir: Path, day: date) -> Path:
    return log_dir / "analysis_shadow" / f"analysis_intents_{day.isoformat()}.journal"


def _record_row(record: AnalysisRecord) -> dict[str, object]:
    return {
        "heading": record.heading,
        "kind": record.kind,
        "payload": record.payload,
        "captured_at": record.captured_at.isoformat(),
        "trigger": record.trigger,
        "section_captured_at": record.section_captured_at.isoformat(),
        "section_start": record.section_start,
    }


def prepare_trial_intent(
    log_dir: Path, day: date, sections: Sequence[SectionSnapshot], version: str
) -> tuple[str, tuple[AnalysisRecord, ...]] | None:
    """Persist one small digest intent before the authoritative legacy append."""
    _analysis_path, invalid_path = shadow_paths(log_dir, day)
    if invalid_path.exists():
        return None
    records = records_from_sections(sections)
    records_digest = _records_digest(records)
    batch_id = records_digest[:24]
    body = _safe_json(
        {
            "batch_id": batch_id,
            "count": len(records),
            "records_sha256": records_digest,
        },
        compact=True,
    ) + "\n"
    append_batch(
        intent_path(log_dir, day),
        header=f"# ActivityLogger analysis trial intents\n> version: {version}\n",
        body=body,
        batch_id=batch_id,
        count=len(records),
    )
    return batch_id, records


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=False, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise OSError("refusing non-directory or foreign-owned shadow path")
    os.chmod(path, 0o700)


def _write_all(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(fd, data[offset:])
        if written <= 0:
            raise OSError("short shadow-log write")
        offset += written


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise OSError("refusing unsafe analysis directory")
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_private_file(
    path: Path, *, max_bytes: int | None = None
) -> tuple[bool, bytes]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return False, b""
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
        ):
            raise OSError("refusing unsafe analysis file")
        if max_bytes is not None and info.st_size > max_bytes:
            raise OSError("private analysis file exceeds its size limit")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                return True, b"".join(chunks)
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise OSError("private analysis file exceeds its size limit")
            chunks.append(chunk)
    finally:
        os.close(fd)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _self_digest(document: dict[str, object]) -> str:
    unsigned = {key: value for key, value in document.items() if key != "self_sha256"}
    return _sha256(
        json.dumps(
            unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    )


def _analysis_header(day: date, version: str, expected_format: str) -> str:
    if expected_format == ANALYSIS_FORMAT_V2:
        format_header = f"> format: {ANALYSIS_FORMAT_V2}\n{TIMELINE_ROW_DECLARATION}"
    elif expected_format == ANALYSIS_FORMAT_V1:
        format_header = f"> format: {ANALYSIS_FORMAT_V1}\n"
    else:
        raise ValueError("unknown analysis format")
    return (
        f"# Work Log - {day.isoformat()}\n\n"
        f"{format_header}"
        f"> generated locally by ActivityLogger {version}; payloads are exact JSON strings\n"
    )


def _framed_batch_bytes(body: str, batch_id: str, count: int) -> bytes:
    body_bytes = body.encode("utf-8")
    digest = _sha256(body_bytes)
    return (
        f"<!-- batch-start id={batch_id} count={count} sha256={digest} -->\n".encode()
        + body_bytes
        + f"<!-- batch-end id={batch_id} sha256={digest} -->\n".encode()
    )


def _declared_analysis_format_bytes(data: bytes) -> str | None:
    declared = [
        line[len(b"> format: ") :]
        for line in data.splitlines()
        if line.startswith(b"> format: ")
    ]
    if not declared:
        return None
    if len(declared) != 1:
        raise ValueError("analysis format header is repeated")
    try:
        value = declared[0].decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("analysis format header is not ASCII") from None
    if value not in {ANALYSIS_FORMAT_V1, ANALYSIS_FORMAT_V2}:
        raise ValueError("analysis format header is unknown")
    return value


def _declared_analysis_day_bytes(data: bytes) -> date | None:
    declared = [
        line[len(b"# Work Log - ") :]
        for line in data.splitlines()
        if line.startswith(b"# Work Log - ")
    ]
    if not declared:
        return None
    if len(declared) != 1:
        raise ValueError("analysis day header is repeated")
    try:
        return date.fromisoformat(declared[0].decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("analysis day header is invalid") from None


def append_batch(
    path: Path,
    *,
    header: str,
    body: str,
    batch_id: str,
    count: int,
) -> None:
    """Append one fsynced batch, or restore the file to its prior size."""
    body_bytes = body.encode("utf-8")
    digest = hashlib.sha256(body_bytes).hexdigest()
    framed = (
        f"<!-- batch-start id={batch_id} count={count} sha256={digest} -->\n".encode()
        + body_bytes
        + f"<!-- batch-end id={batch_id} sha256={digest} -->\n".encode()
    )
    _ensure_private_dir(path.parent)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    original_size = 0
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise OSError("refusing non-regular or foreign-owned shadow file")
        os.fchmod(fd, 0o600)
        original_size = info.st_size
        if original_size == 0:
            _write_all(fd, (header + HEADER_END).encode("utf-8"))
            os.fsync(fd)
            original_size = os.lseek(fd, 0, os.SEEK_END)
        else:
            tail_size = min(original_size, max(512, len(framed)))
            os.lseek(fd, original_size - tail_size, os.SEEK_SET)
            tail = os.read(fd, tail_size)
            endings = tuple(_END_RE.finditer(tail))
            if not endings or endings[-1].end() != len(tail):
                os.lseek(fd, 0, os.SEEK_SET)
                existing = os.read(fd, original_size)
                header_end = existing.find(HEADER_END.encode("utf-8"))
                valid_end = (
                    header_end + len(HEADER_END.encode("utf-8"))
                    if header_end >= 0
                    else 0
                )
                for match in _END_RE.finditer(existing):
                    valid_end = match.end()
                os.ftruncate(fd, valid_end)
                os.fsync(fd)
                original_size = valid_end
                raise OSError("shadow file has an incomplete batch")
            if tail.endswith(framed):
                return
        os.lseek(fd, 0, os.SEEK_END)
        _write_all(fd, framed)
        os.fsync(fd)
    except Exception:
        try:
            os.ftruncate(fd, original_size)
            os.fsync(fd)
        except OSError:
            pass
        raise
    finally:
        os.close(fd)


def append_plain_batch(
    path: Path,
    *,
    header: str,
    body: str,
    expected_format: str,
    expected_day: date,
    validate_existing: bool,
) -> None:
    """Append clean LLM text with in-process rollback and restart validation."""
    header_bytes = header.encode("utf-8")
    if _declared_analysis_format_bytes(header_bytes) != expected_format:
        raise ValueError("new analysis header does not match its expected format")
    if _declared_analysis_day_bytes(header_bytes) != expected_day:
        raise ValueError("new analysis header does not match its expected day")
    _ensure_private_dir(path.parent)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    original_size = 0
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise OSError("refusing non-regular or foreign-owned analysis file")
        os.fchmod(fd, 0o600)
        original_size = info.st_size
        if original_size:
            os.lseek(fd, original_size - 1, os.SEEK_SET)
            if os.read(fd, 1) != b"\n":
                raise OSError("analysis file has an incomplete tail")
            os.lseek(fd, 0, os.SEEK_SET)
            prefix = os.read(fd, min(original_size, 1024))
            if _declared_analysis_format_bytes(prefix) != expected_format:
                raise ValueError("analysis file format does not match its day")
            if _declared_analysis_day_bytes(prefix) != expected_day:
                raise ValueError("analysis file date does not match its path")
        if original_size and validate_existing:
            os.lseek(fd, 0, os.SEEK_SET)
            existing = os.read(fd, original_size)
            parse_records(
                existing.decode("utf-8"),
                day=expected_day,
                expected_format=expected_format,
            )
        elif not original_size:
            _write_all(fd, header.encode("utf-8"))
            os.fsync(fd)
            original_size = os.lseek(fd, 0, os.SEEK_END)
        os.lseek(fd, 0, os.SEEK_END)
        _write_all(fd, body.encode("utf-8"))
        os.fsync(fd)
    except Exception:
        try:
            os.ftruncate(fd, original_size)
            os.fsync(fd)
        except OSError:
            pass
        raise
    finally:
        os.close(fd)


def _pending_transaction_path(log_dir: Path) -> Path:
    return log_dir / "analysis_shadow" / "authoritative_pending.json"


def _exists_no_follow(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


def _authoritative_state(
    log_dir: Path, day: date
) -> tuple[bytes, bytes, tuple[AnalysisRecord, ...], str | None]:
    if day < ANALYSIS_ONLY_START_DAY:
        raise ValueError("authoritative analysis is not enabled for this day")
    canonical_path, _invalid_path = analysis_paths(log_dir, day)
    canonical_exists, canonical = _read_private_file(canonical_path)
    intent_exists, intent = _read_private_file(intent_path(log_dir, day))
    if canonical_exists != intent_exists:
        raise ValueError("authoritative analysis files are incomplete")
    if not canonical_exists:
        return b"", b"", (), None
    records = parse_records(
        canonical.decode("utf-8"),
        day=day,
        expected_format=ANALYSIS_FORMAT_V2,
    )
    intents = read_intents(intent_path(log_dir, day))
    if not _intents_match_records(intents, records):
        raise ValueError("authoritative analysis differs from intents")
    return canonical, intent, records, records[-1].heading if records else None


def validate_authoritative_day(log_dir: Path, day: date) -> str | None:
    """Strictly validate one canonical v2 day and its complete intent chain."""
    return _authoritative_state(log_dir, day)[3]


def authoritative_day_present(log_dir: Path, day: date) -> bool:
    """Return false only when both authoritative files are absent."""
    canonical_path, _invalid_path = analysis_paths(log_dir, day)
    canonical_exists = _exists_no_follow(canonical_path)
    intent_exists = _exists_no_follow(intent_path(log_dir, day))
    if not canonical_exists and not intent_exists:
        return False
    validate_authoritative_day(log_dir, day)
    return True


def _target_plan(
    *,
    role: str,
    relative_path: str,
    day: date,
    original: bytes,
    append: bytes,
    batch_id: str,
    count: int,
    records_digest: str,
) -> dict[str, object]:
    final = original + append
    return {
        "role": role,
        "relative_path": relative_path,
        "day": day.isoformat(),
        "batch_id": batch_id,
        "count": count,
        "records_sha256": records_digest,
        "original_size": len(original),
        "original_sha256": _sha256(original),
        "final_size": len(final),
        "final_sha256": _sha256(final),
        "suffix_sha256": _sha256(append),
        "append_base64": base64.b64encode(append).decode("ascii"),
    }


def _publish_no_replace(path: Path, data: bytes) -> None:
    _ensure_private_dir(path.parent)
    temp = path.parent / f".{path.name}.publish.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    published = False
    try:
        fd = os.open(temp, flags, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise OSError("refusing unsafe pending transaction file")
            os.fchmod(fd, 0o600)
            _write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        _fsync_directory(path.parent)
        os.link(temp, path, follow_symlinks=False)
        published = True
        _fsync_directory(path.parent)
        temp.unlink()
        _fsync_directory(path.parent)
    except Exception:
        if published:
            raise
        temp.unlink(missing_ok=True)
        _fsync_directory(path.parent)
        raise


def prepare_authoritative_transaction(
    log_dir: Path,
    groups: Sequence[tuple[date, Sequence[AnalysisRecord]]],
    version: str,
) -> dict[date, str | None]:
    """Durably publish one all-day-group transaction without applying it."""
    if not groups:
        raise ValueError("authoritative transaction has no groups")
    _ensure_private_dir(log_dir)
    pending = _pending_transaction_path(log_dir)
    if authoritative_transaction_pending(log_dir) or _pending_temp_paths(log_dir):
        raise FileExistsError("an authoritative transaction is already pending")
    transaction_id = uuid.uuid4().hex
    targets: list[dict[str, object]] = []
    headings: dict[date, str | None] = {}
    seen_days: set[date] = set()
    for index, (day, group_records) in enumerate(groups):
        if day in seen_days:
            raise ValueError("authoritative transaction repeats a day")
        if day < ANALYSIS_ONLY_START_DAY:
            raise ValueError("authoritative transaction precedes the cutover")
        records = tuple(group_records)
        if not records:
            raise ValueError("authoritative transaction has an empty group")
        seen_days.add(day)
        canonical, intent, _existing_records, last_heading = _authoritative_state(
            log_dir, day
        )
        body, next_heading, _absolute_rows, _delta_rows = render_records_v2(
            records, last_heading
        )
        canonical_append = (
            b""
            if canonical
            else _analysis_header(day, version, ANALYSIS_FORMAT_V2).encode("utf-8")
        ) + body.encode("utf-8")
        records_digest = _records_digest(records)
        batch_id = _sha256(
            f"{transaction_id}:{index}:{day.isoformat()}".encode("ascii")
        )[:24]
        intent_body = (
            _safe_json(
                {
                    "batch_id": batch_id,
                    "count": len(records),
                    "records_sha256": records_digest,
                },
                compact=True,
            )
            + "\n"
        )
        intent_append = (
            b""
            if intent
            else (
                f"# ActivityLogger analysis intents\n> version: {version}\n"
                + HEADER_END
            ).encode("utf-8")
        ) + _framed_batch_bytes(intent_body, batch_id, len(records))
        canonical_path, _invalid_path = analysis_paths(log_dir, day)
        day_intent_path = intent_path(log_dir, day)
        targets.extend(
            (
                _target_plan(
                    role="canonical",
                    relative_path=canonical_path.relative_to(log_dir).as_posix(),
                    day=day,
                    original=canonical,
                    append=canonical_append,
                    batch_id=batch_id,
                    count=len(records),
                    records_digest=records_digest,
                ),
                _target_plan(
                    role="intent",
                    relative_path=day_intent_path.relative_to(log_dir).as_posix(),
                    day=day,
                    original=intent,
                    append=intent_append,
                    batch_id=batch_id,
                    count=len(records),
                    records_digest=records_digest,
                ),
            )
        )
        headings[day] = next_heading
    manifest: dict[str, object] = {
        "schema": AUTHORITATIVE_TRANSACTION_SCHEMA,
        "transaction_id": transaction_id,
        "created_at": datetime.now().astimezone().isoformat(),
        "targets": targets,
    }
    manifest["self_sha256"] = _self_digest(manifest)
    encoded = (
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_PENDING_MANIFEST_BYTES:
        raise OSError("pending transaction exceeds its size limit")
    _publish_no_replace(pending, encoded)
    return headings


_MANIFEST_KEYS = frozenset(
    {"schema", "transaction_id", "created_at", "targets", "self_sha256"}
)
_TARGET_KEYS = frozenset(
    {
        "role",
        "relative_path",
        "day",
        "batch_id",
        "count",
        "records_sha256",
        "original_size",
        "original_sha256",
        "final_size",
        "final_sha256",
        "suffix_sha256",
        "append_base64",
    }
)
_HEX_24_RE = re.compile(r"^[0-9a-f]{24}$")
_HEX_32_RE = re.compile(r"^[0-9a-f]{32}$")
_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


def authoritative_transaction_pending(log_dir: Path) -> bool:
    """Report possible ownership after an uncertain prepare result."""
    return _exists_no_follow(_pending_transaction_path(log_dir))


def _pending_temp_paths(log_dir: Path) -> tuple[Path, ...]:
    pending = _pending_transaction_path(log_dir)
    try:
        info = pending.parent.lstat()
    except FileNotFoundError:
        return ()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise OSError("refusing unsafe pending transaction directory")
    prefix = f".{pending.name}."
    return tuple(
        sorted(
            path
            for path in pending.parent.iterdir()
            if path.name.startswith(prefix) and path.name.endswith(".tmp")
        )
    )


def _reconcile_pending_artifacts(log_dir: Path) -> None:
    pending = _pending_transaction_path(log_dir)
    temps = _pending_temp_paths(log_dir)
    if len(temps) > 1:
        raise OSError("multiple pending transaction artifacts exist")
    pending_exists = _exists_no_follow(pending)
    if not temps:
        if pending_exists and pending.lstat().st_nlink != 1:
            raise OSError("pending transaction has an unsafe link count")
        return
    temp = temps[0]
    temp_info = temp.lstat()
    if (
        not stat.S_ISREG(temp_info.st_mode)
        or temp_info.st_uid != os.getuid()
        or not pending_exists
    ):
        raise OSError("orphan pending transaction artifact exists")
    pending_info = pending.lstat()
    if (
        not stat.S_ISREG(pending_info.st_mode)
        or pending_info.st_uid != os.getuid()
        or pending_info.st_dev != temp_info.st_dev
        or pending_info.st_ino != temp_info.st_ino
        or pending_info.st_nlink != 2
    ):
        raise OSError("pending transaction artifacts disagree")
    temp.unlink()
    _fsync_directory(pending.parent)


def _load_transaction(log_dir: Path) -> dict[str, object] | None:
    _reconcile_pending_artifacts(log_dir)
    exists, raw = _read_private_file(
        _pending_transaction_path(log_dir), max_bytes=MAX_PENDING_MANIFEST_BYTES
    )
    if not exists:
        return None
    document = json.loads(raw)
    if not isinstance(document, dict) or set(document) != _MANIFEST_KEYS:
        raise ValueError("pending transaction schema is invalid")
    if document["schema"] != AUTHORITATIVE_TRANSACTION_SCHEMA:
        raise ValueError("pending transaction schema is unknown")
    if not isinstance(document["transaction_id"], str) or not _HEX_32_RE.fullmatch(
        document["transaction_id"]
    ):
        raise ValueError("pending transaction id is invalid")
    if not isinstance(document["created_at"], str):
        raise ValueError("pending transaction time is invalid")
    try:
        created_at = datetime.fromisoformat(document["created_at"])
    except ValueError:
        raise ValueError("pending transaction time is invalid") from None
    if created_at.tzinfo is None:
        raise ValueError("pending transaction time has no offset")
    if not isinstance(document["self_sha256"], str) or not _HEX_64_RE.fullmatch(
        document["self_sha256"]
    ):
        raise ValueError("pending transaction digest is invalid")
    if document["self_sha256"] != _self_digest(document):
        raise ValueError("pending transaction digest does not match")
    if not isinstance(document["targets"], list) or not document["targets"]:
        raise ValueError("pending transaction targets are invalid")
    return document


def _validated_target(log_dir: Path, target: object) -> tuple[Path, bytes, date, str]:
    if not isinstance(target, dict) or set(target) != _TARGET_KEYS:
        raise ValueError("pending transaction target schema is invalid")
    try:
        day = date.fromisoformat(target["day"])
    except (TypeError, ValueError):
        raise ValueError("pending transaction target day is invalid") from None
    role = target["role"]
    if role == "canonical":
        path = analysis_paths(log_dir, day)[0]
    elif role == "intent":
        path = intent_path(log_dir, day)
    else:
        raise ValueError("pending transaction target role is invalid")
    if day < ANALYSIS_ONLY_START_DAY:
        raise ValueError("pending transaction target precedes the cutover")
    if target["relative_path"] != path.relative_to(log_dir).as_posix():
        raise ValueError("pending transaction target path is invalid")
    if not isinstance(target["batch_id"], str) or not _HEX_24_RE.fullmatch(
        target["batch_id"]
    ):
        raise ValueError("pending transaction batch id is invalid")
    if type(target["count"]) is not int or target["count"] <= 0:
        raise ValueError("pending transaction count is invalid")
    for key in (
        "records_sha256",
        "original_sha256",
        "final_sha256",
        "suffix_sha256",
    ):
        if not isinstance(target[key], str) or not _HEX_64_RE.fullmatch(target[key]):
            raise ValueError("pending transaction target digest is invalid")
    for key in ("original_size", "final_size"):
        if type(target[key]) is not int or target[key] < 0:
            raise ValueError("pending transaction target size is invalid")
    if not isinstance(target["append_base64"], str):
        raise ValueError("pending transaction suffix is invalid")
    try:
        append = base64.b64decode(target["append_base64"], validate=True)
    except (ValueError, TypeError):
        raise ValueError("pending transaction suffix is invalid") from None
    if _sha256(append) != target["suffix_sha256"]:
        raise ValueError("pending transaction suffix digest does not match")
    original_size = target["original_size"]
    final_size = target["final_size"]
    if final_size != original_size + len(append):
        raise ValueError("pending transaction final size does not match")
    return path, append, day, role


def _read_fd(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _apply_target(log_dir: Path, target: dict[str, object]) -> tuple[date, str]:
    path, append, day, role = _validated_target(log_dir, target)
    _ensure_private_dir(path.parent)
    if not _exists_no_follow(path) and target["original_size"]:
        raise OSError("authoritative target is missing from its planned state")
    flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    if not target["original_size"]:
        flags |= os.O_CREAT
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            raise OSError("refusing unsafe authoritative target")
        os.fchmod(fd, 0o600)
        current = _read_fd(fd)
        original_size = target["original_size"]
        already_final = (
            len(current) == target["final_size"]
            and _sha256(current) == target["final_sha256"]
        )
        if already_final:
            os.fsync(fd)
        else:
            if (
                len(current) == original_size
                and _sha256(current) == target["original_sha256"]
            ):
                pass
            elif (
                len(current) > original_size
                and len(current) < target["final_size"]
                and _sha256(current[:original_size]) == target["original_sha256"]
                and append.startswith(current[original_size:])
            ):
                os.ftruncate(fd, original_size)
                os.fsync(fd)
            else:
                raise OSError("authoritative target differs from its planned state")
            os.lseek(fd, original_size, os.SEEK_SET)
            _write_all(fd, append)
            os.fsync(fd)
            final = _read_fd(fd)
            if (
                len(final) != target["final_size"]
                or _sha256(final) != target["final_sha256"]
            ):
                raise OSError("authoritative target final digest does not match")
            os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(path.parent)
    return day, role


def commit_authoritative_transaction(log_dir: Path) -> dict[date, str | None]:
    """Recover or commit the one pending transaction, then remove its owner."""
    manifest = _load_transaction(log_dir)
    if manifest is None:
        return {}
    targets = manifest["targets"]
    pairs: dict[date, set[str]] = {}
    batch_ids: set[str] = set()
    validated: list[dict[str, object]] = []
    for target in targets:
        _path, _append, day, role = _validated_target(log_dir, target)
        if target["batch_id"] in batch_ids and role == "canonical":
            raise ValueError("pending transaction repeats a batch id")
        if role == "canonical":
            batch_ids.add(target["batch_id"])
        pairs.setdefault(day, set()).add(role)
        validated.append(target)
    if any(roles != {"canonical", "intent"} for roles in pairs.values()):
        raise ValueError("pending transaction target pair is incomplete")
    if len(validated) != len(pairs) * 2:
        raise ValueError("pending transaction repeats a target")
    for day in pairs:
        day_targets = [
            target for target in validated if target["day"] == day.isoformat()
        ]
        identities = {
            (target["batch_id"], target["count"], target["records_sha256"])
            for target in day_targets
        }
        if len(identities) != 1:
            raise ValueError("pending transaction target pair differs")
    for target in validated:
        _apply_target(log_dir, target)
    headings = {day: validate_authoritative_day(log_dir, day) for day in pairs}
    pending = _pending_transaction_path(log_dir)
    pending.unlink()
    _fsync_directory(pending.parent)
    return headings


def recover_authoritative_transaction(log_dir: Path) -> dict[date, str | None]:
    """Complete a pending transaction before capture starts."""
    return commit_authoritative_transaction(log_dir)


def ready_path(log_dir: Path, day: date) -> Path:
    return log_dir / f".daily_log_{day.isoformat()}.ready.json"


_READY_KEYS = frozenset(
    {
        "schema",
        "day",
        "canonical",
        "canonical_sha256",
        "intent",
        "intent_sha256",
        "self_sha256",
    }
)


def validate_day_ready(log_dir: Path, day: date) -> bool:
    """Independently validate a payload-free completed-day proof."""
    try:
        if _exists_no_follow(_pending_transaction_path(log_dir)) or _pending_temp_paths(
            log_dir
        ):
            return False
        exists, raw = _read_private_file(ready_path(log_dir, day))
        if not exists:
            return False
        document = json.loads(raw)
        if not isinstance(document, dict) or set(document) != _READY_KEYS:
            return False
        if (
            document["schema"] != READY_PROOF_SCHEMA
            or document["day"] != day.isoformat()
        ):
            return False
        if document["self_sha256"] != _self_digest(document):
            return False
        canonical_path, _invalid_path = analysis_paths(log_dir, day)
        day_intent_path = intent_path(log_dir, day)
        if document["canonical"] != canonical_path.name:
            return False
        if document["intent"] != day_intent_path.relative_to(log_dir).as_posix():
            return False
        validate_authoritative_day(log_dir, day)
        canonical_exists, canonical = _read_private_file(canonical_path)
        intent_exists, intent = _read_private_file(day_intent_path)
        return bool(
            canonical_exists
            and intent_exists
            and document["canonical_sha256"] == _sha256(canonical)
            and document["intent_sha256"] == _sha256(intent)
        )
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        return False


def publish_day_ready(log_dir: Path, day: date) -> Path:
    """Publish a completed-day proof after the caller confirms next-day health."""
    if _exists_no_follow(_pending_transaction_path(log_dir)) or _pending_temp_paths(
        log_dir
    ):
        raise OSError("cannot publish readiness while a transaction is pending")
    validate_authoritative_day(log_dir, day)
    canonical_path, _invalid_path = analysis_paths(log_dir, day)
    day_intent_path = intent_path(log_dir, day)
    canonical_exists, canonical = _read_private_file(canonical_path)
    intent_exists, intent = _read_private_file(day_intent_path)
    if not canonical_exists or not intent_exists:
        raise OSError("cannot publish readiness for incomplete analysis files")
    proof: dict[str, object] = {
        "schema": READY_PROOF_SCHEMA,
        "day": day.isoformat(),
        "canonical": canonical_path.name,
        "canonical_sha256": _sha256(canonical),
        "intent": day_intent_path.relative_to(log_dir).as_posix(),
        "intent_sha256": _sha256(intent),
    }
    proof["self_sha256"] = _self_digest(proof)
    destination = ready_path(log_dir, day)
    _ensure_private_dir(destination.parent)
    if _exists_no_follow(destination):
        info = destination.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
        ):
            raise OSError("refusing unsafe ready proof")
    temp = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temp, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        _write_all(
            fd,
            (
                json.dumps(
                    proof,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
        )
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(destination.parent)
    os.replace(temp, destination)
    os.chmod(destination, 0o600, follow_symlinks=False)
    _fsync_directory(destination.parent)
    if not validate_day_ready(log_dir, day):
        raise OSError("published ready proof did not validate")
    return destination


def commit_trial_batch(
    log_dir: Path,
    day: date,
    records: Sequence[AnalysisRecord],
    version: str,
    last_heading: str | None,
) -> str | None:
    analysis_path, _invalid_path = shadow_paths(log_dir, day)
    expected_format = analysis_format_for_day(day)
    if expected_format == ANALYSIS_FORMAT_V2:
        body, next_heading, _absolute_rows, _delta_rows = render_records_v2(
            records, last_heading
        )
    else:
        body, next_heading = render_records(records, last_heading)
    header = _analysis_header(day, version, expected_format)
    append_plain_batch(
        analysis_path,
        header=header,
        body=body,
        expected_format=expected_format,
        expected_day=day,
        validate_existing=last_heading is None,
    )
    return next_heading


def mark_invalid(log_dir: Path, day: date, reason: str) -> None:
    """Make a trial failure durable without writing private event content."""
    _analysis_path, invalid_path = shadow_paths(log_dir, day)
    _ensure_private_dir(invalid_path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(invalid_path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise OSError("refusing unsafe invalid marker")
        os.fchmod(fd, 0o600)
        line = f"{datetime.now().astimezone().isoformat()} {reason}\n".encode("utf-8")
        _write_all(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)
