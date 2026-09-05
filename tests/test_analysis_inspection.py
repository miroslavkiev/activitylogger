from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

import analysis_log as al
import operator_controls as controls
import weekly_review as weekly


DAY = date(2026, 8, 27)


def record(day=DAY, *, kind="type", heading="Editor", payload="private sentinel"):
    stamp = datetime.combine(day, datetime.min.time(), timezone.utc).replace(hour=10)
    return al.AnalysisRecord(heading, kind, payload, stamp, "timeline", stamp, True)


def commit(log_dir, days=(DAY,)):
    log_dir.mkdir(mode=0o700)
    al.prepare_authoritative_transaction(log_dir, tuple((day, (record(day),)) for day in days), "test")
    al.commit_authoritative_transaction(log_dir)


@pytest.mark.parametrize("marker_kind", ["regular", "broken_symlink"])
def test_invalid_marker_overrides_existing_proof_and_prevents_republication(tmp_path, marker_kind):
    commit(tmp_path / "logs")
    al.publish_day_ready(tmp_path / "logs", DAY)
    marker = al.analysis_paths(tmp_path / "logs", DAY)[1]
    if marker_kind == "regular":
        marker.write_text("invalid\n")
        marker.chmod(0o600)
    else:
        marker.symlink_to(tmp_path / "absent")
    checked = al.inspect_analysis_day(tmp_path / "logs", DAY)
    assert checked.state == "invalid"
    assert checked.strict_parse and checked.intent_match and checked.stable_snapshot
    assert not checked.ready and not checked.integrity_ok
    assert not al.validate_day_ready(tmp_path / "logs", DAY)
    with pytest.raises(OSError):
        al.publish_day_ready(tmp_path / "logs", DAY)


@pytest.mark.parametrize("proof_kind", ["missing", "broken", "unsafe", "fifo", "nested_json"])
def test_unready_proof_keeps_valid_source_integrity_metadata(tmp_path, proof_kind):
    log_dir = tmp_path / "logs"
    commit(log_dir)
    proof = al.ready_path(log_dir, DAY)
    if proof_kind == "fifo":
        import os
        os.mkfifo(proof, 0o600)
    elif proof_kind != "missing":
        proof.write_text("[" * 1500 + "]" * 1500 if proof_kind == "nested_json" else "not json\n")
        proof.chmod(0o644 if proof_kind == "unsafe" else 0o600)
    checked = al.inspect_analysis_day(log_dir, DAY)
    assert checked.state == "unready"
    assert checked.integrity_ok and checked.strict_parse and checked.intent_match
    assert checked.events == 1 and checked.format_name == al.ANALYSIS_FORMAT_V2
    assert not checked.ready


def test_request_cache_reuses_one_parse_per_day_across_all_reports(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    days = tuple(DAY + timedelta(days=offset) for offset in range(7))
    commit(log_dir, days)
    for day in days:
        al.publish_day_ready(log_dir, day)
    parse = al.parse_records
    parsed = []

    def counted(*args, **kwargs):
        parsed.append(kwargs["day"])
        return parse(*args, **kwargs)

    monkeypatch.setattr(al, "parse_records", counted)
    inspections = {}
    controls.health_report(log_dir, days[-1], home=tmp_path, inspections=inspections)
    controls.storage_report(log_dir, output_dir=tmp_path / "review", inspections=inspections)
    status = weekly.weekly_window_status(log_dir, days[-1], 7, inspections=inspections)
    assert status.ready
    assert sorted(parsed) == list(days)
    assert "private sentinel" not in json.dumps([item.quality for item in status.day_statuses])
    # A new request observes changes. The cache is never used for an export fence.
    al.analysis_paths(log_dir, DAY)[1].symlink_to(tmp_path / "absent")
    assert al.inspect_analysis_day(log_dir, DAY).state == "invalid"
    assert not al.validate_day_ready(log_dir, DAY)


def test_inventory_ignores_invalid_dates_and_unsafe_entries(tmp_path):
    log_dir = tmp_path / "logs"
    commit(log_dir)
    (log_dir / "daily_log_2026-02-30.md").write_text("private sentinel")
    (log_dir / "daily_log_2026-08-28.md").symlink_to(al.analysis_paths(log_dir, DAY)[0])
    (log_dir / "daily_log_2026-08-29.md").mkdir()
    days, malformed = al.analysis_day_inventory(log_dir)
    assert days == (DAY,)
    assert malformed == ("daily_log_2026-02-30.md",)
    assert al.completed_analysis_days(log_dir, before=DAY + timedelta(days=1)) == (DAY,)
    report = controls.storage_report(log_dir, output_dir=tmp_path / "review")
    assert report["malformed_day_count"] == 1
    assert "private sentinel" not in json.dumps(report)
    assert al.analysis_day_inventory(tmp_path / "missing") == ((), ())


@pytest.mark.parametrize("operation", ["write", "fsync"])
def test_ready_publication_failure_removes_only_its_temporary_file(tmp_path, monkeypatch, operation):
    log_dir = tmp_path / "logs"
    commit(log_dir)
    source = al.analysis_paths(log_dir, DAY)[0]
    original = source.read_bytes()

    def fail(*_args):
        raise OSError("injected failure")

    monkeypatch.setattr(al.os, operation, fail)
    with pytest.raises(OSError):
        al.publish_day_ready(log_dir, DAY)
    assert source.read_bytes() == original
    assert not al.ready_path(log_dir, DAY).exists()
    assert not list(log_dir.glob(".*.tmp"))


def test_quality_counts_only_fixed_context_categories_and_valid_storage_gaps():
    items = (
        record(heading="Unknown - private sentinel"),
        record(heading="loginwindow"),
        record(heading="[SECURE APP PAUSED] Editor - private sentinel"),
        record(kind="heartbeat", payload="storage_gap start=2026-08-27T10:00:00+00:00 end=2026-08-27T10:01:00+00:00"),
        replace(record(kind="heartbeat", payload="storage_gap start=private sentinel"), captured_at=record().captured_at + timedelta(hours=3)),
    )
    quality = al.analysis_quality(items, source_bytes=123)
    assert quality["workload_events"] == 3
    assert quality["unknown_context_events"] == 1
    assert quality["system_context_events"] == 1
    assert quality["paused_heading_events"] == 1
    assert quality["storage_gap_count"] == 1
    assert quality["heartbeat_count"] == 2
    assert quality["source_bytes"] == 123
    assert "private sentinel" not in json.dumps(quality)
    assert any("not captured" in warning for warning in quality["warnings"])
