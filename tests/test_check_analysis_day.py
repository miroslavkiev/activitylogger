from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import analysis_log as al


DAY = date(2026, 8, 22)
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_analysis_day.py"


def _commit_day(log_dir: Path, secret: str) -> None:
    captured = datetime(2026, 8, 22, 10, tzinfo=timezone.utc)
    section = al.SectionSnapshot(
        heading="App",
        timestamp="10:00:00",
        captured_at=captured,
        trigger="timeline",
        events=(
            al.EventSnapshot("heartbeat", "", "", captured, 1),
            al.EventSnapshot(
                "privacy_pause_start",
                secret,
                "",
                captured + timedelta(seconds=1),
                2,
            ),
        ),
    )
    log_dir.mkdir()
    trial = al.prepare_trial_intent(log_dir, DAY, (section,), "test")
    assert trial is not None
    al.commit_trial_batch(log_dir, DAY, trial[1], "test", None)


def _run(log_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (
            sys.executable,
            str(SCRIPT),
            "--day",
            DAY.isoformat(),
            "--log-dir",
            str(log_dir),
        ),
        check=False,
        capture_output=True,
        text=True,
    )


def test_check_analysis_day_reports_only_aggregate_integrity(tmp_path):
    secret = "PRIVATE_SENTINEL_DO_NOT_PRINT"
    log_dir = tmp_path / "logs"
    _commit_day(log_dir, secret)

    result = _run(log_dir)

    assert result.returncode == 0, result.stderr
    assert "format=activitylogger-analysis-v1" in result.stdout
    assert "strict_parse=true" in result.stdout
    assert "intent_match=true" in result.stdout
    assert "invalid_marker=false" in result.stdout
    assert "events=2" in result.stdout
    assert "heartbeats=1" in result.stdout
    assert "privacy_starts=1" in result.stdout
    assert "ok=true" in result.stdout
    assert secret not in result.stdout
    assert secret not in result.stderr


def test_check_analysis_day_fails_closed_without_printing_payload(tmp_path):
    secret = "PRIVATE_SENTINEL_DO_NOT_PRINT"
    log_dir = tmp_path / "logs"
    _commit_day(log_dir, secret)
    analysis_file, _invalid_file = al.shadow_paths(log_dir, DAY)
    with analysis_file.open("a", encoding="utf-8") as stream:
        stream.write(f"BROKEN {secret}\n")

    result = _run(log_dir)

    assert result.returncode == 1
    assert "strict_parse=false" in result.stdout
    assert "ok=false" in result.stdout
    assert "error=Analysis check failed" in result.stderr
    assert "Recovery help" in result.stderr
    assert secret not in result.stdout
    assert secret not in result.stderr


def test_check_analysis_day_reports_invalid_marker(tmp_path):
    secret = "PRIVATE_SENTINEL_DO_NOT_PRINT"
    log_dir = tmp_path / "logs"
    _commit_day(log_dir, secret)
    al.mark_invalid(log_dir, DAY, "test marker")

    result = _run(log_dir)

    assert result.returncode == 1
    assert "strict_parse=true" in result.stdout
    assert "intent_match=true" in result.stdout
    assert "invalid_marker=true" in result.stdout
    assert "ok=false" in result.stdout
    assert secret not in result.stdout
    assert secret not in result.stderr


def test_check_analysis_day_rejects_the_wrong_format_for_its_day(tmp_path):
    secret = "PRIVATE_SENTINEL_DO_NOT_PRINT"
    log_dir = tmp_path / "logs"
    _commit_day(log_dir, secret)
    analysis_file, _invalid_file = al.shadow_paths(log_dir, DAY)
    text = analysis_file.read_text(encoding="utf-8").replace(
        al.ANALYSIS_FORMAT_V1, al.ANALYSIS_FORMAT_V2, 1
    )
    analysis_file.write_text(text, encoding="utf-8")

    result = _run(log_dir)

    assert result.returncode == 1
    assert f"format={al.ANALYSIS_FORMAT_V2}" in result.stdout
    assert "strict_parse=false" in result.stdout
    assert "ok=false" in result.stdout
    assert secret not in result.stdout
    assert secret not in result.stderr
