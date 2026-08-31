from __future__ import annotations

import fcntl
import json
import os
import signal
import stat
from datetime import date, datetime, timedelta, timezone

import analysis_log as al
import interleaved_logger as il
import operator_controls as controls


DAY = date(2026, 8, 27)


def _record(day: date) -> al.AnalysisRecord:
    captured = datetime.combine(
        day,
        datetime.min.time(),
        tzinfo=timezone(timedelta(hours=2)),
    ) + timedelta(hours=10)
    return al.AnalysisRecord(
        heading="App",
        kind="heartbeat",
        payload="",
        captured_at=captured,
        trigger="timeline",
        section_captured_at=captured,
        section_start=True,
    )


def _commit_ready_day(log_dir, day: date) -> None:
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    al.prepare_authoritative_transaction(log_dir, ((day, (_record(day),)),), "test")
    al.commit_authoritative_transaction(log_dir)
    al.publish_day_ready(log_dir, day)


def test_manual_pause_uses_shared_fail_closed_gate_without_replay(
    reset_logger_state,
    monkeypatch,
):
    reset_logger_state()
    monkeypatch.setattr(il, "_publish_runtime_state", lambda **_kwargs: True)
    with il._lock:
        il._current_keystrokes.extend(["secret"])
    generation = il._privacy_generation

    il._request_manual_control(signal.SIGUSR1)
    il._apply_pending_manual_control()

    assert il._pause_manual is True
    assert il.is_paused() is True
    assert il._current_keystrokes == []
    assert il._privacy_generation == generation + 1
    count, digest, event = il._apply_clipboard_change_digest(
        2,
        "copied while paused",
        True,
        1,
        "",
    )
    assert event is None

    il._request_manual_control(signal.SIGUSR2)
    il._apply_pending_manual_control()

    assert il._pause_manual is False
    assert il.is_paused() is False
    assert il._current_keystrokes == []
    assert il._apply_clipboard_change_digest(
        count,
        "copied while paused",
        False,
        count,
        digest,
    )[2] is None


def test_manual_resume_never_clears_secure_pause(reset_logger_state, monkeypatch):
    reset_logger_state()
    monkeypatch.setattr(il, "_publish_runtime_state", lambda **_kwargs: True)
    il._set_pause(field=True)
    il._request_manual_control(signal.SIGUSR1)
    il._apply_pending_manual_control()
    il._request_manual_control(signal.SIGUSR2)
    il._apply_pending_manual_control()

    assert il._pause_manual is False
    assert il._pause_secure_field is True
    assert il.is_paused() is True


def test_manual_resume_stays_paused_until_state_is_durable(
    reset_logger_state,
    monkeypatch,
):
    reset_logger_state()
    il._set_pause(manual=True)
    il._request_manual_control(signal.SIGUSR2)
    monkeypatch.setattr(il, "_publish_runtime_state", lambda **_kwargs: False)

    il._apply_pending_manual_control()

    assert il._pause_manual is True
    assert il.is_paused() is True
    assert il._manual_state_dirty.is_set()

    monkeypatch.setattr(il, "_publish_runtime_state", lambda **_kwargs: True)
    il._apply_pending_manual_control()
    assert il._pause_manual is False
    assert il.is_paused() is False


def test_runtime_state_and_instance_lock_are_private(tmp_path):
    root = controls.runtime_dir(tmp_path)
    root.mkdir(mode=0o700, parents=True)
    lock_path = root / controls.LOCK_NAME
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(fd, str(os.getpid()).encode("ascii"))
        assert controls.process_state(tmp_path) == controls.ProcessState(True, os.getpid())

        state_path = controls.write_runtime_state(
            running=True,
            manual_paused=True,
            capture_paused=True,
            control_revision=2,
            home=tmp_path,
        )
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
        assert controls.read_runtime_state(tmp_path)["control_revision"] == 2
    finally:
        os.close(fd)
    assert controls.process_state(tmp_path).running is False


def test_manual_pause_survives_restart_and_corrupt_state_fails_closed(tmp_path):
    controls.write_runtime_state(
        running=False,
        manual_paused=True,
        capture_paused=True,
        control_revision=3,
        home=tmp_path,
    )
    assert controls.initial_manual_pause(tmp_path) is True

    state_path = controls.runtime_dir(tmp_path) / controls.STATE_NAME
    state_path.write_text("broken\n", encoding="utf-8")
    os.chmod(state_path, 0o600)
    assert controls.initial_manual_pause(tmp_path) is True


def test_health_and_storage_reports_are_payload_free(tmp_path):
    log_dir = tmp_path / "logs"
    _commit_ready_day(log_dir, DAY)
    second = DAY + timedelta(days=1)
    al.prepare_authoritative_transaction(
        log_dir,
        ((second, (_record(second),)),),
        "test",
    )
    al.commit_authoritative_transaction(log_dir)
    output_dir = tmp_path / "private_review"
    pack = output_dir / "weekly_review_2026-08-24_2026-08-28_5d"
    pack.mkdir(mode=0o700, parents=True)
    (pack / "INDEX.json").write_text("{}\n", encoding="utf-8")
    os.chmod(pack / "INDEX.json", 0o600)

    health = controls.health_report(log_dir, DAY, home=tmp_path)
    storage = controls.storage_report(
        log_dir,
        output_dir=output_dir,
        today=second + timedelta(days=1),
    )
    rendered = json.dumps({"health": health, "storage": storage})

    assert health["format"] == al.ANALYSIS_FORMAT_V2
    assert health["intent_match"] is True
    assert health["readiness"] is True
    assert health["analysis_mode"] == "600"
    assert health["intent_mode"] == "600"
    assert health["ready_mode"] == "600"
    assert storage["completed_days"] == 2
    assert storage["review_packs"] == 1
    assert storage["missing_readiness_proofs"] == 1
    assert storage["missing_readiness_days"] == second.isoformat()
    assert "App" not in rendered

    analysis_file = al.analysis_paths(log_dir, DAY)[0]
    os.chmod(analysis_file, 0o644)
    unsafe = controls.health_report(log_dir, DAY, home=tmp_path)
    assert unsafe["analysis_mode"] == "644"
    assert unsafe["intent_match"] is False


def test_review_outcome_is_manual_private_markdown(tmp_path):
    output_dir = tmp_path / "private_review"
    path = controls.record_review_outcome(
        DAY,
        "tried",
        "saved one step",
        "keep this local",
        output_dir=output_dir,
    )

    text = path.read_text(encoding="utf-8")
    assert path.name == controls.OUTCOMES_NAME
    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert '"outcome": "tried"' in text
    assert '"value_result": "saved one step"' in text
    assert '"notes": "keep this local"' in text
