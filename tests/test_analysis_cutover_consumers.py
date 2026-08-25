from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import analysis_log as al
from analysis_view import export_compact_day
from clean_markdown_log import compact_file
from historical_analysis import convert_completed_logs
from scripts.check_analysis_day import check_day


DAY = date(2026, 8, 27)


def _record() -> al.AnalysisRecord:
    captured = datetime(2026, 8, 27, 10, tzinfo=timezone(timedelta(hours=2)))
    return al.AnalysisRecord(
        heading="App",
        kind="heartbeat",
        payload="",
        captured_at=captured,
        trigger="timeline",
        section_captured_at=captured,
        section_start=True,
    )


def _write_v2_day(log_dir: Path) -> tuple[al.AnalysisRecord, ...]:
    records = (_record(),)
    body, _heading, _absolute, _delta = al.render_records_v2(records)
    text = (
        f"# Work Log - {DAY.isoformat()}\n\n"
        f"> format: {al.ANALYSIS_FORMAT_V2}\n"
        f"{al.TIMELINE_ROW_DECLARATION}"
        "> generated locally by ActivityLogger test; payloads are exact JSON strings\n"
        f"{body}"
    )
    log_dir.mkdir(mode=0o700)
    os.chmod(log_dir, 0o700)
    analysis_file = log_dir / f"daily_log_{DAY.isoformat()}.md"
    analysis_file.write_text(text, encoding="utf-8")
    os.chmod(analysis_file, 0o600)

    digest = al._records_digest(records)
    batch_id = digest[:24]
    intent_body = json.dumps(
        {"batch_id": batch_id, "count": len(records), "records_sha256": digest},
        separators=(",", ":"),
    ) + "\n"
    al.append_batch(
        al.intent_path(log_dir, DAY),
        header="# ActivityLogger analysis intents\n> version: test\n",
        body=intent_body,
        batch_id=batch_id,
        count=len(records),
    )
    return records


def test_post_cutover_check_and_export_use_the_canonical_v2_file(tmp_path):
    log_dir = tmp_path / "logs"
    records = _write_v2_day(log_dir)

    checked = check_day(log_dir, DAY)
    exported = export_compact_day(
        log_dir,
        tmp_path / "private_review",
        DAY,
        today=DAY + timedelta(days=1),
    )

    assert checked.ok
    assert checked.events == len(records)
    assert exported.analysis_file == f"daily_log_{DAY.isoformat()}.md"
    assert exported.event_count == len(records)


def test_historical_export_skips_canonical_analysis_days(tmp_path):
    log_dir = tmp_path / "logs"
    _write_v2_day(log_dir)

    results = convert_completed_logs(
        log_dir,
        tmp_path / "historical_review",
        today=DAY + timedelta(days=1),
    )

    assert results == ()
    assert not list((tmp_path / "historical_review").glob("historical_analysis_*.md"))


def test_legacy_compactor_rejects_v2_without_mutating_destination(tmp_path):
    log_dir = tmp_path / "logs"
    _write_v2_day(log_dir)
    source = log_dir / f"daily_log_{DAY.isoformat()}.md"
    destination = tmp_path / "existing.md"
    destination.write_text("unchanged\n", encoding="utf-8")

    with pytest.raises(ValueError, match="already compact"):
        compact_file(str(source), str(destination))

    assert destination.read_text(encoding="utf-8") == "unchanged\n"


def test_consumers_reject_unknown_analysis_format_without_mutation(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(mode=0o700)
    source = log_dir / f"daily_log_{DAY.isoformat()}.md"
    source.write_text(
        f"# Work Log - {DAY.isoformat()}\n\n"
        "> format: activitylogger-analysis-v99\n"
        "## Context\ncontent\n",
        encoding="utf-8",
    )
    source.chmod(0o600)
    destination = tmp_path / "existing.md"
    destination.write_text("unchanged\n", encoding="utf-8")

    with pytest.raises(ValueError, match="already compact"):
        compact_file(str(source), str(destination))
    with pytest.raises(ValueError, match="unsupported analysis format"):
        convert_completed_logs(
            log_dir,
            tmp_path / "historical_review",
            today=DAY + timedelta(days=1),
        )

    assert destination.read_text(encoding="utf-8") == "unchanged\n"
    assert not list((tmp_path / "historical_review").glob("historical_analysis_*.md"))
