from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import analysis_log as al

V1_DAY = date(2026, 8, 24)
V2_DAY = date(2026, 8, 25)
PLUS_TWO = timezone(timedelta(hours=2))
PLUS_ONE = timezone(timedelta(hours=1))


def _record(
    kind: str,
    captured_at: datetime,
    *,
    payload: str = "",
    heading: str = "App - Window",
    trigger: str = "timeline",
    section_at: datetime | None = None,
    section_start: bool = True,
) -> al.AnalysisRecord:
    return al.AnalysisRecord(
        heading=heading,
        kind=kind,
        payload=payload,
        captured_at=captured_at,
        trigger=trigger,
        section_captured_at=section_at or captured_at,
        section_start=section_start,
    )


def _document(day: date, format_name: str, body: str) -> str:
    declaration = (
        al.TIMELINE_ROW_DECLARATION
        if format_name == al.ANALYSIS_FORMAT_V2
        else ""
    )
    return (
        f"# Work Log - {day.isoformat()}\n\n"
        f"> format: {format_name}\n"
        f"{declaration}"
        "> generated locally by ActivityLogger test; payloads are exact JSON strings\n"
        f"{body}"
    )


def _v2_body(
    records: tuple[al.AnalysisRecord, ...], last_heading: str | None = None
) -> tuple[str, str | None, int, int]:
    return al.render_records_v2(records, last_heading)


def _write_intent(
    log_dir: Path, day: date, records: tuple[al.AnalysisRecord, ...]
) -> None:
    digest = al._records_digest(records)
    batch_id = digest[:24]
    body = json.dumps(
        {
            "batch_id": batch_id,
            "count": len(records),
            "records_sha256": digest,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ) + "\n"
    al.append_batch(
        al.intent_path(log_dir, day),
        header="# ActivityLogger analysis trial intents\n> version: test\n",
        body=body,
        batch_id=batch_id,
        count=len(records),
    )


def _write_existing_analysis(
    log_dir: Path, day: date, format_name: str, records: tuple[al.AnalysisRecord, ...]
) -> Path:
    shadow = log_dir / "analysis_shadow"
    shadow.mkdir(mode=0o700, parents=True)
    os.chmod(shadow, 0o700)
    if format_name == al.ANALYSIS_FORMAT_V2:
        body, _heading, _absolute, _delta = _v2_body(records)
    else:
        body, _heading = al.render_records(records)
    analysis, _invalid = al.shadow_paths(log_dir, day)
    analysis.write_text(_document(day, format_name, body), encoding="utf-8")
    os.chmod(analysis, 0o600)
    return analysis


def _record_rows(records: tuple[al.AnalysisRecord, ...]) -> list[dict[str, object]]:
    return [al._record_row(record) for record in records]


def _timeline_rows(body: str) -> list[str]:
    return [line for line in body.splitlines() if line.startswith("@")]


def test_v2_round_trip_preserves_exact_rows_digest_hostile_payload_and_privacy():
    start = datetime(2026, 8, 25, 10, tzinfo=PLUS_TWO)
    hostile = "  exact\n## not a heading\n@+1 fake\n\u0085\u2028\u2029  "
    shared = start + timedelta(minutes=2)
    records = (
        _record(
            "type",
            start,
            payload=hostile,
            trigger="file_flush",
            section_at=start + timedelta(seconds=5),
        ),
        _record(
            "privacy_pause_start",
            start + timedelta(minutes=1),
            heading="[PRIVATE CONTEXT]",
        ),
        _record(
            "heartbeat",
            start + timedelta(minutes=1, seconds=10),
            heading="[PRIVATE CONTEXT]",
        ),
        _record("focus", shared, section_at=shared),
        _record(
            "idle_start",
            shared + timedelta(seconds=1),
            section_at=shared,
            section_start=False,
        ),
        _record(
            "click",
            start + timedelta(minutes=3),
            payload="button",
            trigger="click",
        ),
    )

    body, _heading, absolute, delta = _v2_body(records)
    text = _document(V2_DAY, al.ANALYSIS_FORMAT_V2, body)
    parsed = al.parse_records(
        text, expected_format=al.ANALYSIS_FORMAT_V2
    )

    assert _record_rows(parsed) == _record_rows(records)
    assert al._records_digest(parsed) == al._records_digest(records)
    assert absolute == 1
    assert delta == 1
    assert all(
        record.heading == "[PRIVATE CONTEXT]"
        for record in parsed
        if record.kind in {"privacy_pause_start", "heartbeat"}
    )


def test_v2_resets_absolute_timeline_anchor_for_every_append_batch():
    start = datetime(2026, 8, 25, 10, tzinfo=PLUS_TWO)
    first = (
        _record("focus", start),
        _record("heartbeat", start + timedelta(seconds=10)),
    )
    second = (
        _record("idle_start", start + timedelta(minutes=1)),
        _record("idle_end", start + timedelta(minutes=1, seconds=10)),
    )

    first_body, heading, first_absolute, first_delta = _v2_body(first)
    second_body, _heading, second_absolute, second_delta = _v2_body(
        second, heading
    )

    assert _timeline_rows(first_body)[0].startswith("@10:00:00+0200 ")
    assert _timeline_rows(first_body)[1].startswith("@+10 ")
    assert _timeline_rows(second_body)[0].startswith("@10:01:00+0200 ")
    assert _timeline_rows(second_body)[1].startswith("@+10 ")
    assert (first_absolute, first_delta) == (1, 1)
    assert (second_absolute, second_delta) == (1, 1)
    parsed = al.parse_records(
        _document(V2_DAY, al.ANALYSIS_FORMAT_V2, first_body + second_body),
        expected_format=al.ANALYSIS_FORMAT_V2,
    )
    assert _record_rows(parsed) == _record_rows(first + second)


def test_v2_delta_boundaries_backward_time_and_offset_change_are_exact():
    start = datetime(2026, 8, 25, 10, tzinfo=PLUS_TWO)
    same = start
    plus_900 = same + timedelta(seconds=900)
    plus_901 = plus_900 + timedelta(seconds=901)
    backward = plus_901 - timedelta(seconds=1)
    offset_change = backward.astimezone(PLUS_ONE)
    records = tuple(
        _record("heartbeat", stamp)
        for stamp in (start, same, plus_900, plus_901, backward, offset_change)
    )

    body, _heading, absolute, delta = _v2_body(records)
    rows = _timeline_rows(body)

    assert rows[0].startswith("@10:00:00+0200 ")
    assert rows[1].startswith("@+0 ")
    assert rows[2].startswith("@+900 ")
    assert rows[3].startswith(f"@{plus_901.strftime('%H:%M:%S%z')} ")
    assert rows[4].startswith(f"@{backward.strftime('%H:%M:%S%z')} ")
    assert rows[5].startswith(f"@{offset_change.strftime('%H:%M:%S%z')} ")
    assert (absolute, delta) == (4, 2)
    parsed = al.parse_records(
        _document(V2_DAY, al.ANALYSIS_FORMAT_V2, body),
        expected_format=al.ANALYSIS_FORMAT_V2,
    )
    assert _record_rows(parsed) == _record_rows(records)


def test_v2_dst_fallback_uses_absolute_rows_with_distinct_offsets():
    day = date(2026, 10, 25)
    summer = datetime(2026, 10, 25, 2, 30, tzinfo=PLUS_TWO)
    winter = datetime(2026, 10, 25, 2, 30, tzinfo=PLUS_ONE)
    records = (
        _record("heartbeat", summer),
        _record("heartbeat", winter),
    )

    body, _heading, absolute, delta = _v2_body(records)

    assert "@02:30:00+0200 heartbeat" in body
    assert "@02:30:00+0100 heartbeat" in body
    assert (absolute, delta) == (2, 0)
    parsed = al.parse_records(
        _document(day, al.ANALYSIS_FORMAT_V2, body),
        expected_format=al.ANALYSIS_FORMAT_V2,
    )
    assert _record_rows(parsed) == _record_rows(records)


def test_v2_cross_midnight_content_uses_exact_standard_fallback():
    section_at = datetime(2026, 8, 25, 0, 0, 1, tzinfo=PLUS_TWO)
    records = (
        _record(
            "type",
            section_at - timedelta(seconds=2),
            payload="before midnight",
            trigger="file_flush",
            section_at=section_at,
        ),
    )

    body, _heading, absolute, delta = _v2_body(records)

    assert _timeline_rows(body) == []
    assert (absolute, delta) == (0, 0)
    parsed = al.parse_records(
        _document(V2_DAY, al.ANALYSIS_FORMAT_V2, body),
        expected_format=al.ANALYSIS_FORMAT_V2,
    )
    assert _record_rows(parsed) == _record_rows(records)
    assert al._records_digest(parsed) == al._records_digest(records)


def test_activation_gate_writes_v1_on_august_24_and_v2_on_august_25(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    v1_at = datetime(2026, 8, 24, 12, tzinfo=PLUS_TWO)
    v2_at = datetime(2026, 8, 25, 12, tzinfo=PLUS_TWO)
    v1_records = (_record("heartbeat", v1_at),)
    v2_records = (_record("heartbeat", v2_at),)

    assert al.ANALYSIS_V2_START_DAY == V2_DAY
    assert al.analysis_format_for_day(V1_DAY) == al.ANALYSIS_FORMAT_V1
    assert al.analysis_format_for_day(V2_DAY) == al.ANALYSIS_FORMAT_V2
    al.commit_trial_batch(log_dir, V1_DAY, v1_records, "test", None)
    al.commit_trial_batch(log_dir, V2_DAY, v2_records, "test", None)
    v1_path, _ = al.shadow_paths(log_dir, V1_DAY)
    v2_path, _ = al.shadow_paths(log_dir, V2_DAY)
    v1_text = v1_path.read_text(encoding="utf-8")
    v2_text = v2_path.read_text(encoding="utf-8")

    assert f"> format: {al.ANALYSIS_FORMAT_V1}\n" in v1_text
    assert al.TIMELINE_ROW_DECLARATION not in v1_text
    assert f"> format: {al.ANALYSIS_FORMAT_V2}\n" in v2_text
    assert al.TIMELINE_ROW_DECLARATION in v2_text
    assert al.parse_records(v1_text, expected_format=al.ANALYSIS_FORMAT_V1) == v1_records
    assert al.parse_records(v2_text, expected_format=al.ANALYSIS_FORMAT_V2) == v2_records


@pytest.mark.parametrize(
    ("day", "wrong_format"),
    (
        (V1_DAY, "activitylogger-analysis-v2"),
        (V2_DAY, "activitylogger-analysis-v1"),
    ),
)
def test_writer_rejects_mixed_day_format_without_mutation(
    tmp_path, day, wrong_format
):
    log_dir = tmp_path / "logs"
    stamp = datetime.combine(day, datetime.min.time(), tzinfo=PLUS_TWO)
    existing = (_record("heartbeat", stamp),)
    path = _write_existing_analysis(log_dir, day, wrong_format, existing)
    original = path.read_bytes()
    appended = (_record("focus", stamp + timedelta(seconds=1)),)

    with pytest.raises((OSError, ValueError)):
        al.commit_trial_batch(log_dir, day, appended, "test", None)

    assert path.read_bytes() == original


def test_plain_writer_rejects_bad_new_header_without_truncating_existing_file(
    tmp_path,
):
    path = tmp_path / "analysis.md"
    original = b"existing private data\n"
    path.write_bytes(original)

    with pytest.raises(ValueError):
        al.append_plain_batch(
            path,
            header=_document(V2_DAY, al.ANALYSIS_FORMAT_V1, ""),
            body="ignored\n",
            expected_format=al.ANALYSIS_FORMAT_V2,
            expected_day=V2_DAY,
            validate_existing=True,
        )

    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "format_name", (al.ANALYSIS_FORMAT_V1, al.ANALYSIS_FORMAT_V2)
)
def test_strict_parser_rejects_wrong_internal_day(format_name):
    stamp = datetime(2026, 8, 25, 10, tzinfo=PLUS_TWO)
    records = (_record("heartbeat", stamp),)
    if format_name == al.ANALYSIS_FORMAT_V2:
        body, _heading, _absolute, _delta = _v2_body(records)
    else:
        body, _heading = al.render_records(records)
    text = _document(V2_DAY + timedelta(days=1), format_name, body)

    with pytest.raises(ValueError, match="expected day"):
        al.parse_records(text, day=V2_DAY, expected_format=format_name)


def test_writer_rejects_wrong_existing_day_without_mutation(tmp_path):
    log_dir = tmp_path / "logs"
    stamp = datetime(2026, 8, 25, 10, tzinfo=PLUS_TWO)
    records = (_record("heartbeat", stamp),)
    path = _write_existing_analysis(
        log_dir,
        V2_DAY + timedelta(days=1),
        al.ANALYSIS_FORMAT_V2,
        records,
    )
    expected_path, _ = al.shadow_paths(log_dir, V2_DAY)
    expected_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    expected_path.write_bytes(path.read_bytes())
    original = expected_path.read_bytes()

    with pytest.raises(ValueError, match="date does not match"):
        al.commit_trial_batch(log_dir, V2_DAY, records, "test", None)

    assert expected_path.read_bytes() == original


def test_v2_restart_multi_batch_append_matches_complete_intent_stream(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    start = datetime(2026, 8, 25, 10, tzinfo=PLUS_TWO)
    batches = (
        (
            _record("focus", start),
            _record("heartbeat", start + timedelta(seconds=10)),
        ),
        (
            _record(
                "type",
                start + timedelta(minutes=1),
                payload="work",
                trigger="file_flush",
            ),
            _record("heartbeat", start + timedelta(minutes=1, seconds=10)),
        ),
        (
            _record("idle_start", start + timedelta(minutes=2)),
            _record("idle_end", start + timedelta(minutes=2, seconds=10)),
        ),
    )

    heading = None
    for index, batch in enumerate(batches):
        _write_intent(log_dir, V2_DAY, batch)
        heading = al.commit_trial_batch(
            log_dir,
            V2_DAY,
            batch,
            "test",
            None if index == 2 else heading,
        )

    analysis_path, _invalid = al.shadow_paths(log_dir, V2_DAY)
    text = analysis_path.read_text(encoding="utf-8")
    parsed = al.parse_records(text, expected_format=al.ANALYSIS_FORMAT_V2)
    expected = tuple(record for batch in batches for record in batch)
    intents = al.read_intents(al.intent_path(log_dir, V2_DAY))

    assert _record_rows(parsed) == _record_rows(expected)
    assert al._records_digest(parsed) == al._records_digest(expected)
    assert al._intents_match_records(intents, parsed)
    assert text.count(f"> format: {al.ANALYSIS_FORMAT_V2}\n") == 1
    assert text.count(al.TIMELINE_ROW_DECLARATION) == 1
    assert len(
        [line for line in text.splitlines() if line.startswith("@") and "+0200" in line]
    ) >= 3


def _commit_heartbeat_day(log_dir: Path, day: date, hours: range) -> None:
    sections: list[al.SectionSnapshot] = []
    for sequence, hour in enumerate(hours, start=1):
        captured = datetime.combine(
            day, datetime.min.time(), tzinfo=PLUS_TWO
        ) + timedelta(hours=hour, minutes=30)
        event = al.EventSnapshot(
            "heartbeat", "", "", captured, sequence
        )
        sections.append(
            al.SectionSnapshot(
                "App",
                captured.strftime("%H:%M:%S"),
                captured,
                "timeline",
                (event,),
                analysis_only=True,
                analysis_order=sequence,
            )
        )
    trial = al.prepare_trial_intent(log_dir, day, tuple(sections), "test")
    assert trial is not None
    al.commit_trial_batch(log_dir, day, trial[1], "test", None)


@pytest.mark.parametrize("target_day", (V1_DAY, V2_DAY))
def test_validator_accepts_v1_to_v2_and_v2_to_v2_next_day_proof(
    tmp_path, target_day
):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _commit_heartbeat_day(log_dir, target_day, range(24))
    _commit_heartbeat_day(log_dir, target_day + timedelta(days=1), range(1))
    (log_dir / f"daily_log_{target_day.isoformat()}.md").write_text(
        "legacy\n" * 5000, encoding="utf-8"
    )

    result = al.validate_trial(
        log_dir,
        target_day,
        today=target_day + timedelta(days=2),
        min_byte_reduction=-1.0,
    )

    assert result.ok, result.errors
    target_path, _ = al.shadow_paths(log_dir, target_day)
    next_path, _ = al.shadow_paths(log_dir, target_day + timedelta(days=1))
    assert al.parse_records(
        target_path.read_text(encoding="utf-8"),
        expected_format=al.analysis_format_for_day(target_day),
    )
    assert al.parse_records(
        next_path.read_text(encoding="utf-8"),
        expected_format=al.analysis_format_for_day(target_day + timedelta(days=1)),
    )


def test_strict_parser_rejects_compact_rows_in_v1_and_missing_v2_declaration():
    stamp = datetime(2026, 8, 25, 10, tzinfo=PLUS_TWO)
    row = f"## App\n@{stamp.strftime('%H:%M:%S%z')} heartbeat\n"
    v1 = _document(V2_DAY, al.ANALYSIS_FORMAT_V1, row)
    v2_without_declaration = _document(
        V2_DAY, al.ANALYSIS_FORMAT_V2, row
    ).replace(al.TIMELINE_ROW_DECLARATION, "")

    with pytest.raises(ValueError):
        al.parse_records(v1, expected_format=al.ANALYSIS_FORMAT_V1)
    with pytest.raises(ValueError):
        al.parse_records(
            v2_without_declaration,
            expected_format=al.ANALYSIS_FORMAT_V2,
        )
