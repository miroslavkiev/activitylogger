from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import analysis_log as al
import analysis_view as av

DAY = date(2026, 8, 22)
PLUS_TWO = timezone(timedelta(hours=2))


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


def _render(records: tuple[al.AnalysisRecord, ...], day: date = DAY) -> str:
    return av.render_compact_view(
        records,
        day=day,
        analysis_name=f"analysis_log_{day.isoformat()}.md",
        analysis_sha256="a" * 64,
        intent_name=f"analysis_intents_{day.isoformat()}.journal",
        intent_sha256="b" * 64,
    )


def _write_intent(
    log_dir: Path,
    day: date,
    records: tuple[al.AnalysisRecord, ...],
    *,
    digest: str | None = None,
) -> None:
    records_digest = digest or al._records_digest(records)
    batch_id = records_digest[:24]
    body = json.dumps(
        {
            "batch_id": batch_id,
            "count": len(records),
            "records_sha256": records_digest,
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


def _commit_day(
    log_dir: Path,
    records: tuple[al.AnalysisRecord, ...],
    *,
    day: date = DAY,
    intent_digest: str | None = None,
) -> tuple[Path, Path]:
    log_dir.mkdir(mode=0o700, parents=True)
    os.chmod(log_dir, 0o700)
    _write_intent(log_dir, day, records, digest=intent_digest)
    al.commit_trial_batch(log_dir, day, records, "test", None)
    analysis_path, _invalid_path = al.shadow_paths(log_dir, day)
    return analysis_path, al.intent_path(log_dir, day)


def _compact_rows(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("@")]


def test_default_private_output_directory_is_ignored():
    repository = Path(__file__).resolve().parents[1]
    ignored = (repository / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert av.DEFAULT_OUTPUT_DIR.parent == repository
    assert f"{av.DEFAULT_OUTPUT_DIR.name}/" in ignored


def test_compact_view_round_trip_preserves_every_record_field_and_digest():
    start = datetime(2026, 8, 22, 10, tzinfo=PLUS_TWO)
    hostile = "  exact\n## not a heading\n@+1 not-a-row\n\u0085\u2028\u2029  "
    records = (
        _record(
            "type",
            start,
            payload=hostile,
            trigger="file_flush",
            section_at=start + timedelta(seconds=5),
        ),
        _record("focus", start + timedelta(seconds=10), payload="changed"),
        _record("heartbeat", start + timedelta(seconds=20)),
        _record(
            "click",
            start + timedelta(seconds=21),
            payload="button",
            trigger="click",
        ),
        _record(
            "privacy_pause_start",
            start + timedelta(seconds=30),
            heading="[PRIVATE CONTEXT]",
        ),
    )

    rendered = _render(records)
    parsed = av.parse_compact_records(rendered)

    assert parsed == records
    assert [al._record_row(record) for record in parsed] == [
        al._record_row(record) for record in records
    ]
    assert al._records_digest(parsed) == al._records_digest(records)

    tampered = rendered.replace("changed", "changed-tampered", 1)
    with pytest.raises(ValueError, match="invalid compact view"):
        av.parse_compact_records(tampered)


def test_cross_midnight_content_uses_exact_v1_fallback():
    section_at = datetime(2026, 8, 22, 0, 0, 1, tzinfo=PLUS_TWO)
    records = (
        _record(
            "type",
            section_at - timedelta(seconds=2),
            payload="before midnight",
            trigger="file_flush",
            section_at=section_at,
        ),
    )

    rendered = _render(records)

    assert _compact_rows(rendered) == []
    assert av.parse_compact_records(rendered) == records
    assert al._records_digest(av.parse_compact_records(rendered)) == al._records_digest(
        records
    )


def test_only_adjacent_singleton_timeline_sections_are_compacted():
    start = datetime(2026, 8, 22, 10, tzinfo=PLUS_TWO)
    shared_section = start + timedelta(minutes=1)
    records = (
        _record("focus", start),
        _record("heartbeat", start + timedelta(seconds=1)),
        _record("idle_start", shared_section, section_at=shared_section),
        _record(
            "idle_end",
            shared_section + timedelta(seconds=1),
            section_at=shared_section,
            section_start=False,
        ),
        _record(
            "heartbeat",
            start + timedelta(minutes=2, seconds=1),
            section_at=start + timedelta(minutes=2),
        ),
        _record("event", start + timedelta(minutes=3)),
        _record(
            "type",
            start + timedelta(minutes=4),
            payload="content",
            trigger="file_flush",
        ),
    )

    rendered = _render(records)

    assert len(_compact_rows(rendered)) == 2
    assert av.parse_compact_records(rendered) == records


def test_timeline_time_encoding_uses_bounded_deltas_and_absolute_resets():
    start = datetime(2026, 8, 22, 12, tzinfo=PLUS_TWO)
    minus_901 = start - timedelta(seconds=901)
    minus_900 = minus_901 - timedelta(seconds=900)
    same = minus_900
    plus_900 = same + timedelta(seconds=900)
    plus_901 = plus_900 + timedelta(seconds=901)
    offset_change = plus_901.astimezone(timezone(timedelta(hours=1)))
    times = (
        start,
        minus_901,
        minus_900,
        same,
        plus_900,
        plus_901,
        offset_change,
    )
    records = tuple(_record("heartbeat", stamp) for stamp in times)

    rendered = _render(records)

    assert f"@{minus_901.strftime('%H:%M:%S%z')} " in rendered
    assert f"@{minus_900.strftime('%H:%M:%S%z')} " in rendered
    assert "@+0 " in rendered
    assert "@+900 " in rendered
    assert f"@{plus_901.strftime('%H:%M:%S%z')} " in rendered
    assert f"@{offset_change.strftime('%H:%M:%S%z')} " in rendered
    assert av.parse_compact_records(rendered) == records


def test_timeline_time_encoding_rejects_records_outside_the_declared_day():
    before_midnight = datetime(2026, 8, 22, 23, 59, 59, tzinfo=PLUS_TWO)
    after_midnight = before_midnight + timedelta(seconds=1)
    records = (
        _record("heartbeat", before_midnight),
        _record("heartbeat", after_midnight),
    )

    with pytest.raises(ValueError, match="round-trip"):
        _render(records)


def test_parser_and_export_errors_do_not_expose_hostile_payload(tmp_path):
    secret = "PRIVATE_SENTINEL_DO_NOT_PRINT"
    stamp = datetime(2026, 8, 22, 10, tzinfo=PLUS_TWO)
    records = (_record("heartbeat", stamp, payload=secret),)
    rendered = _render(records)
    malformed = rendered.replace("heartbeat", "INVALID-KIND", 1)

    with pytest.raises(Exception) as compact_error:
        av.parse_compact_records(malformed)
    assert secret not in str(compact_error.value)

    log_dir = tmp_path / "logs"
    output_dir = tmp_path / "private_review"
    analysis_path, _intent_path = _commit_day(log_dir, records)
    with analysis_path.open("a", encoding="utf-8") as stream:
        stream.write(f"BROKEN {secret}\n")

    with pytest.raises(Exception) as export_error:
        av.export_compact_day(
            log_dir, output_dir, DAY, today=DAY + timedelta(days=1)
        )
    assert secret not in str(export_error.value)
    assert not list(output_dir.glob("*.md")) if output_dir.exists() else True

    completed = subprocess.run(
        (
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "scripts" / "export_compact_analysis.py"),
            "--day",
            DAY.isoformat(),
            "--log-dir",
            str(log_dir),
            "--output-dir",
            str(output_dir),
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert secret not in completed.stdout
    assert secret not in completed.stderr
    assert "error=compact export failed" in completed.stderr


def test_export_rejects_current_day_invalid_marker_and_intent_mismatch(tmp_path):
    stamp = datetime(2026, 8, 22, 10, tzinfo=PLUS_TWO)
    records = (_record("heartbeat", stamp),)

    current_logs = tmp_path / "current" / "logs"
    _commit_day(current_logs, records)
    with pytest.raises(Exception, match="complete|current"):
        av.export_compact_day(current_logs, tmp_path / "current-output", DAY, today=DAY)

    invalid_logs = tmp_path / "invalid" / "logs"
    _commit_day(invalid_logs, records)
    _analysis, invalid_path = al.shadow_paths(invalid_logs, DAY)
    invalid_path.write_text("invalid\n", encoding="utf-8")
    os.chmod(invalid_path, 0o600)
    with pytest.raises(Exception, match="invalid"):
        av.export_compact_day(
            invalid_logs,
            tmp_path / "invalid-output",
            DAY,
            today=DAY + timedelta(days=1),
        )

    mismatch_logs = tmp_path / "mismatch" / "logs"
    wrong_digest = al._records_digest((replace(records[0], payload="different"),))
    _commit_day(mismatch_logs, records, intent_digest=wrong_digest)
    with pytest.raises(Exception, match="intent|match"):
        av.export_compact_day(
            mismatch_logs,
            tmp_path / "mismatch-output",
            DAY,
            today=DAY + timedelta(days=1),
        )


def test_export_rejects_live_tree_overlap_and_symlink_output_directory(tmp_path):
    stamp = datetime(2026, 8, 22, 10, tzinfo=PLUS_TWO)
    records = (_record("heartbeat", stamp),)
    log_dir = tmp_path / "logs"
    _commit_day(log_dir, records)

    with pytest.raises(Exception, match="separate|tree|overlap"):
        av.export_compact_day(
            log_dir,
            log_dir / "review",
            DAY,
            today=DAY + timedelta(days=1),
        )

    real_output = tmp_path / "real-output"
    real_output.mkdir(mode=0o700)
    linked_output = tmp_path / "linked-output"
    linked_output.symlink_to(real_output, target_is_directory=True)
    with pytest.raises(Exception, match="safe|symlink|directory"):
        av.export_compact_day(
            log_dir,
            linked_output,
            DAY,
            today=DAY + timedelta(days=1),
        )
    assert list(real_output.iterdir()) == []


def test_export_rejects_unsafe_existing_destination(tmp_path):
    stamp = datetime(2026, 8, 22, 10, tzinfo=PLUS_TWO)
    records = (_record("heartbeat", stamp),)
    log_dir = tmp_path / "logs"
    output_dir = tmp_path / "private_review"
    _commit_day(log_dir, records)
    av.export_compact_day(
        log_dir, output_dir, DAY, today=DAY + timedelta(days=1)
    )
    output = next(output_dir.glob("*.md"))
    target = tmp_path / "unrelated-private-file"
    target.write_text("do not replace\n", encoding="utf-8")
    output.unlink()
    output.symlink_to(target)

    with pytest.raises(Exception, match="unsafe|destination"):
        av.export_compact_day(
            log_dir, output_dir, DAY, today=DAY + timedelta(days=1)
        )

    assert output.is_symlink()
    assert target.read_text(encoding="utf-8") == "do not replace\n"

    output.unlink()
    output.write_text("weak permissions\n", encoding="utf-8")
    output.chmod(0o644)
    with pytest.raises(Exception, match="unsafe|destination"):
        av.export_compact_day(
            log_dir, output_dir, DAY, today=DAY + timedelta(days=1)
        )
    assert output.read_text(encoding="utf-8") == "weak permissions\n"


def test_export_rejects_source_change_before_atomic_commit(tmp_path, monkeypatch):
    stamp = datetime(2026, 8, 22, 10, tzinfo=PLUS_TWO)
    records = (_record("heartbeat", stamp),)
    log_dir = tmp_path / "logs"
    output_dir = tmp_path / "private_review"
    analysis_path, _intent_path = _commit_day(log_dir, records)
    real_stable_read = av._stable_read
    changed = False

    def change_after_snapshot(path: Path) -> bytes:
        nonlocal changed
        data = real_stable_read(path)
        if path == analysis_path and not changed:
            changed = True
            with path.open("ab") as stream:
                stream.write(b"\n")
        return data

    monkeypatch.setattr(av, "_stable_read", change_after_snapshot)

    with pytest.raises(Exception, match="changed"):
        av.export_compact_day(
            log_dir, output_dir, DAY, today=DAY + timedelta(days=1)
        )

    assert changed
    assert not list(output_dir.glob("*.md"))


def test_export_is_private_deterministic_and_does_not_change_sources(tmp_path):
    start = datetime(2026, 8, 22, 10, tzinfo=PLUS_TWO)
    records = (
        _record("focus", start, payload="changed"),
        _record("heartbeat", start + timedelta(seconds=10)),
        _record(
            "type",
            start + timedelta(seconds=20),
            payload="work",
            trigger="file_flush",
        ),
    )
    log_dir = tmp_path / "logs"
    output_dir = tmp_path / "private_review"
    analysis_path, intent_path = _commit_day(log_dir, records)
    source_hashes = {
        analysis_path: hashlib.sha256(analysis_path.read_bytes()).hexdigest(),
        intent_path: hashlib.sha256(intent_path.read_bytes()).hexdigest(),
    }

    av.export_compact_day(
        log_dir, output_dir, DAY, today=DAY + timedelta(days=1)
    )
    outputs = list(output_dir.glob("*.md"))
    assert len(outputs) == 1
    output = outputs[0]
    first_bytes = output.read_bytes()
    assert output_dir.stat().st_mode & 0o777 == 0o700
    assert output.stat().st_mode & 0o777 == 0o600
    assert av.parse_compact_records(first_bytes.decode("utf-8")) == records

    av.export_compact_day(
        log_dir, output_dir, DAY, today=DAY + timedelta(days=1)
    )
    assert output.read_bytes() == first_bytes
    assert {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_hashes
    } == source_hashes
