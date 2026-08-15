"""F6 optional scroll coalescing — TDD cases T-F6-01…12."""

from __future__ import annotations

import queue
import re
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import interleaved_logger as il
import scroll_coalesce as sc
from config import default_config


@pytest.fixture(autouse=True)
def _reset_logger_state(tmp_path: Path):
    cfg = replace(
        default_config(),
        log_dir=tmp_path / "logs",
        scroll_coalesce_enabled=False,
        scroll_coalesce_ms=400,
        capture_triggers_enabled=False,
    )
    il.apply_config(cfg)
    with il._lock:
        il._current_heading = "App — Window"
        il._current_keystrokes.clear()
        il._current_events.clear()
        il._sections.clear()
        il._last_screen_text = ""
        il._last_clipboard_count = 0
        il._last_clipboard_text = ""
        il._pause_secure_app = False
        il._pause_secure_field = False
        il._is_paused = False
        il._current_modifiers.clear()
        il._secure_field_cache = False
        il._secure_field_cache_at = 0.0
        il._window_bucket = None
        il._scan_pending = False
        il._last_key_activity_mono = None
        il._last_key_flush_cause = None
        il._key_flush_hook = None
        il._scroll_burst = None
        il._scroll_diag_emitted = False
    while True:
        try:
            il._ax_jobs.get_nowait()
            il._ax_jobs.task_done()
        except queue.Empty:
            break
    yield


def _enable_scroll(
    tmp_path: Path,
    *,
    coalesce_ms: int = 400,
    triggers: bool = False,
) -> None:
    cfg = replace(
        default_config(),
        log_dir=tmp_path / "logs",
        scroll_coalesce_enabled=True,
        scroll_coalesce_ms=coalesce_ms,
        capture_triggers_enabled=triggers,
    )
    il.apply_config(cfg)


def _feed_scrolls(
    n: int,
    *,
    dx: float = 0.0,
    dy: float = -1.0,
    start: float = 0.0,
    step: float = 0.005,
    app: str = "Safari",
    heading: str = "Safari — Docs",
) -> None:
    for i in range(n):
        il.on_scroll_tick(
            dx=dx,
            dy=dy,
            now=start + i * step,
            app=app,
            heading=heading,
        )


# --- T-F6-01 ---


def test_T_F6_01_default_off_ignores_scrolls(tmp_path: Path):
    assert il.SCROLL_COALESCE_ENABLED is False
    _feed_scrolls(50, heading="Safari — Docs")
    il.check_scroll_coalesce_idle(now=10.0)
    with il._lock:
        assert il._scroll_burst is None or not getattr(il._scroll_burst, "is_open", False)
        assert not any("Scroll" in e for e in il._current_events)
        assert not any(
            any("Scroll" in e for e in s.get("events", [])) for s in il._sections
        )
        assert all(s.get("trigger") != "scroll_coalesce" for s in il._sections)


# --- T-F6-02 ---


def test_T_F6_02_rapid_scroll_coalesces_to_one_note(tmp_path: Path):
    _enable_scroll(tmp_path, coalesce_ms=400, triggers=True)
    with il._lock:
        il._current_heading = "Safari — Docs"
    _feed_scrolls(40, dy=-1.0, start=0.0, step=0.005)
    # Quiet after last tick (~0.195) + 400ms → flush at 0.6
    flushed = il.check_scroll_coalesce_idle(now=0.6)
    assert flushed is True
    with il._lock:
        assert len(il._sections) == 1
        sec = il._sections[0]
        assert sec["trigger"] == "scroll_coalesce"
        assert len(sec["events"]) == 1
        line = sec["events"][0]
        assert "40 ticks" in line
        assert "net down" in line
        assert "🖱️ **Scroll:**" in line


def test_T_F6_02b_f5_off_seals_without_trigger(tmp_path: Path):
    """F5 OFF: still seal one section; no trigger field (FR-F6-004 / closed decision)."""
    _enable_scroll(tmp_path, coalesce_ms=50, triggers=False)
    with il._lock:
        il._current_heading = "Safari — Docs"
    _feed_scrolls(12, dy=-1.0, start=0.0, step=0.001)
    assert il.check_scroll_coalesce_idle(now=0.1) is True
    with il._lock:
        assert len(il._sections) == 1
        sec = il._sections[0]
        assert "trigger" not in sec
        assert "12 ticks" in sec["events"][0]
        assert "net down" in sec["events"][0]
        ts = il.format_section_timestamp_line(sec["timestamp"], sec.get("trigger"))
    assert re.fullmatch(r"\*\d{2}:\d{2}:\d{2}\*", ts)


# --- T-F6-03 ---


def test_T_F6_03_quiet_period_resets_on_each_tick(tmp_path: Path):
    _enable_scroll(tmp_path, coalesce_ms=400, triggers=True)
    with il._lock:
        il._current_heading = "Safari — Docs"
    il.on_scroll_tick(dx=0, dy=-1, now=0.0, app="Safari", heading="Safari — Docs")
    assert il.check_scroll_coalesce_idle(now=0.3) is False
    il.on_scroll_tick(dx=0, dy=-1, now=0.3, app="Safari", heading="Safari — Docs")
    assert il.check_scroll_coalesce_idle(now=0.6) is False
    il.on_scroll_tick(dx=0, dy=-1, now=0.6, app="Safari", heading="Safari — Docs")
    # Flush only after last tick + 400ms → t=1.0
    assert il.check_scroll_coalesce_idle(now=0.999) is False
    assert il.check_scroll_coalesce_idle(now=1.0) is True
    with il._lock:
        assert len(il._sections) == 1
        assert "3 ticks" in il._sections[0]["events"][0]


# --- T-F6-04 ---


def test_T_F6_04_pause_discards_burst(tmp_path: Path):
    _enable_scroll(tmp_path, coalesce_ms=100, triggers=True)
    with il._lock:
        il._current_heading = "Safari — Docs"
    _feed_scrolls(10, start=0.0, step=0.01)
    il._set_pause(app=True)
    assert il.check_scroll_coalesce_idle(now=5.0) is False
    with il._lock:
        assert not any("Scroll" in e for e in il._current_events)
        assert il._sections == []
    # Scrolls while paused are ignored
    _feed_scrolls(5, start=5.0, step=0.01)
    il.check_scroll_coalesce_idle(now=6.0)
    with il._lock:
        assert il._sections == []
    # After pause clears, only new ticks count
    il._set_pause(app=False)
    _feed_scrolls(3, start=7.0, step=0.01, dy=-1.0)
    assert il.check_scroll_coalesce_idle(now=7.2) is True
    with il._lock:
        assert len(il._sections) == 1
        assert "3 ticks" in il._sections[0]["events"][0]


# --- T-F6-05 ---


def test_T_F6_05_app_switch_flushes_prior_section(tmp_path: Path):
    _enable_scroll(tmp_path, coalesce_ms=400, triggers=True)
    with il._lock:
        il._current_heading = "AppA — TitleA"
    _feed_scrolls(5, app="AppA", heading="AppA — TitleA", start=0.0)
    il.apply_heading_change("AppB — TitleB")
    with il._lock:
        assert len(il._sections) == 1
        sec = il._sections[0]
        assert sec["heading"] == "AppA — TitleA"
        assert sec["trigger"] == "scroll_coalesce"
        assert "5 ticks" in sec["events"][0]
        assert "AppA" in sec["events"][0]
        assert il._scroll_burst is None or not il._scroll_burst.is_open
        assert il._current_heading == "AppB — TitleB"
    _feed_scrolls(2, app="AppB", heading="AppB — TitleB", start=1.0, dy=1.0)
    assert il.check_scroll_coalesce_idle(now=1.5) is True
    with il._lock:
        assert len(il._sections) == 2
        sec2 = il._sections[1]
        assert sec2["heading"] == "AppB — TitleB"
        assert "2 ticks" in sec2["events"][0]
        assert "AppB" in sec2["events"][0]


# --- T-F6-06 ---


def test_T_F6_06_no_mouse_move_side_effects(tmp_path: Path):
    _enable_scroll(tmp_path, coalesce_ms=100)
    # Simulated moves only — no scroll API
    il.on_mouse_move_stub(1.0, 2.0)
    il.check_scroll_coalesce_idle(now=1.0)
    with il._lock:
        assert il._sections == []
        assert not any("Scroll" in e for e in il._current_events)
        assert not any("move" in e.lower() for e in il._current_events)
    kwargs = il.mouse_listener_kwargs_for_config()
    assert "on_move" not in kwargs
    assert "on_scroll" in kwargs
    assert "on_click" in kwargs
    # Default off: no on_scroll
    il.apply_config(
        replace(default_config(), log_dir=tmp_path / "logs", scroll_coalesce_enabled=False)
    )
    kwargs_off = il.mouse_listener_kwargs_for_config()
    assert "on_scroll" not in kwargs_off
    assert "on_move" not in kwargs_off


# --- T-F6-07 ---


def test_T_F6_07_f5_trigger_name_scroll_coalesce(tmp_path: Path):
    _enable_scroll(tmp_path, coalesce_ms=50, triggers=True)
    with il._lock:
        il._current_heading = "Safari — Docs"
    _feed_scrolls(4, start=0.0, step=0.001)
    il.check_scroll_coalesce_idle(now=0.1)
    with il._lock:
        sec = il._sections[0]
        assert sec["trigger"] == "scroll_coalesce"
        ts_line = il.format_section_timestamp_line(sec["timestamp"], sec["trigger"])
    assert re.fullmatch(r"\*\d{2}:\d{2}:\d{2} · trigger:scroll_coalesce\*", ts_line)
    assert "*trigger: " not in ts_line
    assert "trigger:scroll" not in ts_line.replace("scroll_coalesce", "")


# --- T-F6-08 ---


def test_T_F6_08_flush_while_paused_appends_nothing(tmp_path: Path):
    _enable_scroll(tmp_path, coalesce_ms=50, triggers=True)
    with il._lock:
        il._current_heading = "Safari — Docs"
    _feed_scrolls(8, start=0.0)
    # Force pause without going through discard path, then flush
    with il._lock:
        il._is_paused = True
    assert il.flush_scroll_burst(now=10.0) is False
    with il._lock:
        assert il._sections == []
        assert not any("Scroll" in e for e in il._current_events)


# --- T-F6-09 ---


def test_T_F6_09_format_contract():
    line = sc.format_scroll_event(28, "down", app="Safari")
    assert line == "🖱️ **Scroll:** 28 ticks, net down (Safari)"
    bare = sc.format_scroll_event(3, "up")
    assert bare == "🖱️ **Scroll:** 3 ticks, net up"
    assert "x=" not in line
    assert not re.search(r"\(\d+,\s*\d+\)", line)
    assert sc.net_direction(0, 5) == "up"
    assert sc.net_direction(0, -3) == "down"
    assert sc.net_direction(2, 0) == "right"
    assert sc.net_direction(-2, 0) == "left"
    assert sc.net_direction(1, -1) == "mixed"
    assert sc.net_direction(0, 0) == "none"


# --- T-F6-10 ---


def test_T_F6_10_scroll_delivery_failure_soft(tmp_path: Path, monkeypatch):
    _enable_scroll(tmp_path, coalesce_ms=100, triggers=True)
    diags: list[str] = []

    def fake_listener(**kwargs):
        if "on_scroll" in kwargs:
            raise RuntimeError("scroll not available")
        return MagicMock(name="click_only_listener")

    monkeypatch.setattr(il, "mouse_Listener", fake_listener, raising=False)
    # Prefer explicit factory used by main()
    listener, note = il.create_mouse_listener_safe(on_click=lambda *a: None)
    assert listener is not None
    assert note is not None
    assert "scroll" in note.lower()
    # Second call must not emit another diagnostic string
    listener2, note2 = il.create_mouse_listener_safe(on_click=lambda *a: None)
    assert listener2 is not None
    assert note2 is None
    # Keys/clicks path still works
    il.record_click_event("Button 'OK'")
    with il._lock:
        assert any("Клік" in e for e in il._current_events) or any(
            any("Клік" in e for e in s["events"]) for s in il._sections
        )


# --- T-F6-11 ---


def test_T_F6_11_shutdown_flushes_open_burst(tmp_path: Path):
    _enable_scroll(tmp_path, coalesce_ms=400, triggers=True)
    with il._lock:
        il._current_heading = "Safari — Docs"
    _feed_scrolls(6, start=0.0)
    il.flush_scroll_burst_on_shutdown()
    with il._lock:
        assert len(il._sections) == 1
        assert "6 ticks" in il._sections[0]["events"][0]
        assert il._sections[0]["trigger"] == "scroll_coalesce"

    # Reset and pause path
    with il._lock:
        il._sections.clear()
        il._scroll_burst = None
    _feed_scrolls(4, start=1.0)
    il._set_pause(app=True)
    il.flush_scroll_burst_on_shutdown()
    with il._lock:
        assert il._sections == []


def test_T_F6_11b_file_flush_does_not_drop_open_burst(tmp_path: Path):
    _enable_scroll(tmp_path, coalesce_ms=400, triggers=True)
    with il._lock:
        il._current_heading = "Safari — Docs"
    _feed_scrolls(7, start=0.0)
    il.flush_to_file()
    log = next((tmp_path / "logs").glob("daily_log_*.md"))
    text = log.read_text(encoding="utf-8")
    assert "7 ticks" in text
    assert "Scroll" in text
    assert "trigger:scroll_coalesce" in text


# --- T-F6-12 ---


def test_T_F6_12_no_screenshot_or_scan_on_scroll(tmp_path: Path):
    _enable_scroll(tmp_path, coalesce_ms=50, triggers=True)
    with il._lock:
        il._current_heading = "Safari — Docs"
    with (
        patch.object(il, "scan_screen") as scan,
        patch.object(il, "_enqueue_ax") as enq,
    ):
        _feed_scrolls(5, start=0.0)
        il.check_scroll_coalesce_idle(now=0.2)
        scan.assert_not_called()
        # Scroll flush must not enqueue AX scan solely for scroll
        for call in enq.call_args_list:
            args = call.args[0] if call.args else None
            assert args != ("scan",)
            if isinstance(args, tuple):
                assert args[0] != "scan"


# --- Pure accumulate helpers ---


def test_accumulate_and_should_flush_pure():
    b = sc.accumulate(None, dx=0, dy=-1, now=0.0, app="A", heading="A — T")
    assert b.ticks == 1
    assert sc.should_flush(b, now=0.3, coalesce_ms=400) is False
    b = sc.accumulate(b, dx=0, dy=-1, now=0.3, app="A", heading="A — T")
    assert b.ticks == 2
    assert sc.should_flush(b, now=0.7, coalesce_ms=400) is True
    assert "net down" in sc.format_burst_line(b)


def test_mouse_listener_kwargs_never_on_move():
    kw = sc.mouse_listener_kwargs(on_click=lambda *a: None, on_scroll=lambda *a: None)
    assert "on_move" not in kw
    assert "on_scroll" in kw
