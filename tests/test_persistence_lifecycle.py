from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import analysis_log as al
import interleaved_logger as il


@pytest.fixture(autouse=True)
def _reset(reset_logger_state):
    reset_logger_state()
    yield


def _section(label: str, captured_at: datetime) -> dict:
    return {
        "heading": "App - Window",
        "events": [label],
        "timestamp": captured_at.strftime("%H:%M:%S"),
        "captured_at": captured_at,
    }


def test_flush_restores_in_place_after_path_failure(monkeypatch):
    identity = il._sections
    il._sections.append(_section("kept", datetime.now(timezone.utc)))
    monkeypatch.setattr(il, "_get_filepath", lambda *args: (_ for _ in ()).throw(OSError("disk")))
    assert il.flush_to_file() is False
    assert il._sections is identity
    assert [s["events"] for s in il._sections] == [["kept"]]


def test_flush_keeps_sections_until_trial_guard_is_durable(monkeypatch):
    pending = _section("kept", datetime.now(timezone.utc))
    il._sections.append(pending)

    def fail_intent(*args):
        assert il._sections == [pending]
        raise OSError("intent")

    monkeypatch.setattr(il, "prepare_trial_intent", fail_intent)
    monkeypatch.setattr(il, "mark_invalid", lambda *args: (_ for _ in ()).throw(OSError("marker")))
    monkeypatch.setattr(
        il,
        "_write_section_group",
        lambda *args: pytest.fail("legacy write started without a durable trial guard"),
    )
    assert il.flush_to_file() is False
    assert il._sections == [pending]


def test_cross_day_trial_intent_retry_is_idempotent(monkeypatch):
    first = datetime(2026, 8, 20, 23, 59, tzinfo=timezone.utc)
    second = first + timedelta(minutes=2)
    il._sections.extend([_section("first", first), _section("second", second)])
    real_prepare = il.prepare_trial_intent
    failed = False

    def prepare(log_dir, day, sections, version):
        if day == second.date() and not failed:
            raise OSError("intent")
        return real_prepare(log_dir, day, sections, version)

    def mark(log_dir, day, reason):
        nonlocal failed
        if day == second.date() and not failed:
            failed = True
            raise OSError("marker")
        return al.mark_invalid(log_dir, day, reason)

    monkeypatch.setattr(il, "prepare_trial_intent", prepare)
    monkeypatch.setattr(il, "mark_invalid", mark)
    monkeypatch.setattr(il, "_write_section_group", lambda *args: True)
    monkeypatch.setattr(il, "_write_analysis_group", lambda *args: None)
    assert il.flush_to_file() is False
    assert len(il._sections) == 2
    assert il.flush_to_file() is True
    first_intents = al.read_intents(al.intent_path(il.LOG_DIR, first.date()))
    assert len(first_intents) == 1


def test_flush_restores_only_uncommitted_date_groups(monkeypatch):
    local_tz = datetime.now().astimezone().tzinfo
    first = datetime(2026, 8, 20, 12, 0, tzinfo=local_tz)
    second = first + timedelta(days=1)
    il._sections.extend([_section("first", first), _section("second", second)])
    calls: list[str] = []

    def write_group(day, captured_at, sections):
        calls.append(sections[0]["events"][0])
        return len(calls) == 1

    monkeypatch.setattr(il, "_write_section_group", write_group)
    assert il.flush_to_file() is False
    assert calls == ["first", "second"]
    assert [s["events"] for s in il._sections] == [["second"]]


def test_flush_groups_sections_by_capture_date(tmp_path):
    local_tz = datetime.now().astimezone().tzinfo
    first = datetime(2026, 8, 20, 23, 59, tzinfo=local_tz)
    second = datetime(2026, 8, 21, 0, 1, tzinfo=local_tz)
    il._sections.extend([_section("before midnight", first), _section("after midnight", second)])
    assert il.flush_to_file() is True
    assert "before midnight" in (tmp_path / "logs" / "daily_log_2026-08-20.md").read_text()
    assert "after midnight" in (tmp_path / "logs" / "daily_log_2026-08-21.md").read_text()


def test_capture_date_is_not_converted_to_machine_timezone(tmp_path):
    captured = datetime(2026, 8, 20, 23, 59, tzinfo=timezone.utc)
    il._sections.append(_section("utc date", captured))
    assert il.flush_to_file() is True
    assert "utc date" in (tmp_path / "logs" / "daily_log_2026-08-20.md").read_text()


def test_concurrent_flushes_are_serialized(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    active = 0
    peak = 0
    guard = threading.Lock()

    def write_group(day, captured_at, sections):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        entered.set()
        release.wait(2)
        with guard:
            active -= 1
        return True

    monkeypatch.setattr(il, "_write_section_group", write_group)
    il._sections.append(_section("one", datetime.now(timezone.utc)))
    first = threading.Thread(target=il.flush_to_file)
    first.start()
    assert entered.wait(1)
    il._sections.append(_section("two", datetime.now(timezone.utc)))
    second = threading.Thread(target=il.flush_to_file)
    second.start()
    release.set()
    first.join(2)
    second.join(2)
    assert peak == 1
    assert il._sections == []


def test_restore_bounds_failed_buffer_to_newest_sections(monkeypatch):
    monkeypatch.setattr(il, "MAX_SECTIONS", 2)
    now = datetime.now(timezone.utc)
    il._sections.extend([_section(str(i), now) for i in range(4)])
    monkeypatch.setattr(il, "_write_section_group", lambda *args: False)
    assert il.flush_to_file() is False
    assert [s["events"][0] for s in il._sections] == ["2", "3"]


def test_secure_writer_forces_private_mode(tmp_path):
    path = tmp_path / "log.md"
    assert il._write_to_file(path, ["secret\n"])
    assert path.stat().st_mode & 0o777 == 0o600


def test_secure_writer_rolls_back_a_failed_append(tmp_path, monkeypatch):
    path = tmp_path / "log.md"
    path.write_text("before\n", encoding="utf-8")
    real_write = il.os.write
    calls = 0

    def fail_after_partial(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(fd, data[:2])
        raise OSError("disk full")

    monkeypatch.setattr(il.os, "write", fail_after_partial)
    assert il._write_to_file(path, ["after\n"]) is False
    assert path.read_text(encoding="utf-8") == "before\n"


def test_file_writer_retries_with_capped_backoff(monkeypatch):
    waits: list[float] = []
    outcomes = iter([False, False, True])

    def wait(delay):
        waits.append(delay)
        if len(waits) == 4:
            raise StopIteration
        return False

    monkeypatch.setattr(il._writer_wakeup, "wait", wait)
    monkeypatch.setattr(il, "flush_to_file", lambda: next(outcomes))
    monkeypatch.setattr(il, "FLUSH_INTERVAL_SEC", 30)
    with pytest.raises(StopIteration):
        il.file_writer_loop()
    assert waits == [30.0, 60.0, 60.0, 30.0]


def test_pending_click_is_never_persisted(tmp_path):
    pending = _section("", datetime.now(timezone.utc))
    pending.update({"events": [], "pending_click": 9, "privacy_generation": 0})
    il._sections.append(pending)
    il._pending_clicks[9] = pending
    assert il.flush_to_file() is True
    assert il._sections == [pending]
    assert not list((tmp_path / "logs").glob("daily_log_*.md"))


def test_unresolved_click_blocks_all_later_sections(monkeypatch):
    now = datetime.now(timezone.utc)
    before = _section("before", now)
    pending = _section("", now)
    pending.update(
        {
            "events": [],
            "pending_click": 9,
            "privacy_generation": 0,
            "click_context": (1, "Safari", "Page"),
            "expires_mono": 100.0,
        }
    )
    after = _section("after", now)
    il._sections.extend([before, pending, after])
    il._pending_clicks[9] = pending
    written: list[str] = []

    def write_group(day, captured_at, sections):
        written.extend(section["events"][0] for section in sections)
        return True

    monkeypatch.setattr(il.time, "monotonic", lambda: 1.0)
    monkeypatch.setattr(il, "_write_section_group", write_group)
    assert il.flush_to_file() is True
    assert written == ["before"]
    assert il._sections == [pending, after]


def test_pending_click_expiry_unblocks_later_sections(monkeypatch):
    now = datetime.now(timezone.utc)
    pending = _section("", now)
    pending.update(
        {
            "events": [],
            "pending_click": 9,
            "privacy_generation": 0,
            "click_context": (1, "Safari", "Page"),
            "expires_mono": 2.0,
        }
    )
    after = _section("after", now)
    il._sections.extend([pending, after])
    il._pending_clicks[9] = pending
    written: list[str] = []
    monkeypatch.setattr(il.time, "monotonic", lambda: 3.0)
    monkeypatch.setattr(
        il,
        "_write_section_group",
        lambda day, captured_at, sections: written.extend(
            section["events"][0] for section in sections
        )
        is None,
    )
    assert il.flush_to_file() is True
    assert written == ["after"]
    assert il._pending_clicks == {}
    assert il._sections == []


def test_writer_wakes_at_pending_click_expiry(monkeypatch):
    now = datetime.now(timezone.utc)
    pending = _section("", now)
    pending.update(
        {
            "events": [],
            "pending_click": 9,
            "privacy_generation": 0,
            "click_context": (1, "Safari", "Page"),
            "expires_mono": 12.0,
        }
    )
    il._sections.append(pending)
    il._pending_clicks[9] = pending
    waits: list[float] = []
    monkeypatch.setattr(il.time, "monotonic", lambda: 10.0)

    def wait(timeout):
        waits.append(timeout)
        raise StopIteration

    monkeypatch.setattr(il._writer_wakeup, "wait", wait)
    with pytest.raises(StopIteration):
        il.file_writer_loop()
    assert waits == [2.0]


def test_instance_lock_uses_fixed_private_runtime_path(tmp_path, monkeypatch):
    monkeypatch.setattr(il.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(tmp_path)))
    try:
        assert il.acquire_instance_lock() is True
        path = tmp_path / "Library" / "Application Support" / "ActivityLogger"
        assert path.stat().st_mode & 0o777 == 0o700
        assert (path / "activitylogger.lock").stat().st_mode & 0o777 == 0o600
    finally:
        il._close_instance_lock()
