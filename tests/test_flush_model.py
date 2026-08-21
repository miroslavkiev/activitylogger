"""F3 typing-pause flush model, TDD cases T-F3-01 through T-F3-24."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import interleaved_logger as il
from config import default_config
from tests.helpers import _seed_keys


@pytest.fixture(autouse=True)
def _reset_logger_state(reset_logger_state):
    reset_logger_state(typing_pause_sec=0.5, flush_interval_sec=30)
    yield


def _idle_check(now: float) -> bool:
    return il.check_typing_pause_idle(now=now)


# --- Idle flush happy path ---


def test_T_F3_01_idle_flush_moves_keys_to_events_only(tmp_path: Path):
    _seed_keys(["h", "i"], at=0.0)
    with il._lock:
        heading_before = il._current_heading
        sections_before = list(il._sections)
    logs = tmp_path / "logs"
    before_files = set(logs.glob("daily_log_*.md")) if logs.exists() else set()
    with patch.object(il, "flush_to_file") as mock_file_flush:
        flushed = _idle_check(0.5)
    assert flushed is True
    mock_file_flush.assert_not_called()
    with il._lock:
        assert il._current_events[-1] == "hi"
        assert il._current_keystrokes == []
        assert il._sections == sections_before
        assert il._current_heading == heading_before
        assert il._last_key_flush_cause == "typing_pause"
    after_files = set(logs.glob("daily_log_*.md")) if logs.exists() else set()
    assert after_files == before_files


def test_T_F3_char_level_keys_preserved_through_idle_flush():
    """FR-F3-001: chars stay char-level in the buffer; idle joins once (no keys-off)."""
    assert not hasattr(il, "KEYS_OFF")
    assert not hasattr(il, "keystroke_mode")
    with patch.object(il, "sync_secure_field_from_focus", return_value=False):
        il.on_press(char_key("h"))
        il.on_press(char_key("i"))
    with il._lock:
        assert il._current_keystrokes == ["h", "i"]
        il._last_key_activity_mono = 0.0
    sections_before = list(il._sections)
    assert _idle_check(0.5) is True
    with il._lock:
        assert il._current_events[-1] == "hi"
        assert il._current_keystrokes == []
        assert il._sections == sections_before


def test_T_F3_02_idle_check_empty_buffer_no_empty_event():
    with il._lock:
        il._current_events.clear()
        il._current_keystrokes.clear()
    il.note_key_activity(now=0.0)
    events_before = list(il._current_events)
    flushed = _idle_check(1.0)
    assert flushed is False
    with il._lock:
        assert il._current_events == events_before


# --- Continuous typing ---


def test_T_F3_03_continuous_typing_no_flush_before_pause():
    _seed_keys(["a"], at=0.0)
    with il._lock:
        il._current_keystrokes.append("b")
    il.note_key_activity(now=0.2)
    with il._lock:
        il._current_keystrokes.append("c")
    il.note_key_activity(now=0.4)
    assert _idle_check(0.6) is False
    with il._lock:
        assert "".join(il._current_keystrokes) == "abc"
        assert "abc" not in il._current_events


def test_T_F3_04_flush_after_full_idle_from_last_key():
    _seed_keys(["a"], at=0.0)
    with il._lock:
        il._current_keystrokes.append("b")
    il.note_key_activity(now=0.2)
    with il._lock:
        il._current_keystrokes.append("c")
    il.note_key_activity(now=0.4)
    sections_before = list(il._sections)
    assert _idle_check(0.9) is True
    with il._lock:
        assert il._current_events[-1] == "abc"
        assert il._current_keystrokes == []
        assert il._sections == sections_before


# --- Backspace ---


def test_T_F3_05_backspace_before_idle_flush():
    _seed_keys(["a", "b", "c"], at=0.0)
    with il._lock:
        il._current_keystrokes.pop()
    il.note_key_activity(now=0.1)
    assert _idle_check(0.6) is True
    with il._lock:
        assert il._current_events[-1] == "ab"


def test_T_F3_06_backspace_after_flush_does_not_mutate_events():
    _seed_keys(["a", "b"], at=0.0)
    assert _idle_check(0.5) is True
    with patch.object(il, "sync_secure_field_from_focus", return_value=False):
        il.on_press(keyboard_key("backspace"))
    with il._lock:
        assert il._current_events == ["ab"]
        assert il._current_keystrokes == []


def test_T_F3_07_backspace_empties_buffer_no_event_on_idle():
    _seed_keys(["a"], at=0.0)
    with il._lock:
        il._current_keystrokes.pop()
    il.note_key_activity(now=0.1)
    events_before = list(il._current_events)
    assert _idle_check(0.6) is False
    with il._lock:
        assert il._current_events == events_before
        assert il._current_keystrokes == []


# --- Hotkeys and special tokens ---


def test_T_F3_08_hotkey_tokens_in_burst():
    _seed_keys(["a", "[CMD+C]"], at=0.0)
    assert _idle_check(0.5) is True
    with il._lock:
        assert il._current_events[-1] == "a[CMD+C]"


def test_T_F3_09_enter_token_preserved():
    _seed_keys(["x", "\n[ENTER]\n", "y"], at=0.0)
    assert _idle_check(0.5) is True
    with il._lock:
        assert il._current_events[-1] == "x\n[ENTER]\ny"


# --- Pause / privacy ---


def test_T_F3_10_pause_discards_buffer_no_flush():
    _seed_keys(["s", "e", "c"], at=0.0)
    events_before = list(il._current_events)
    il._set_pause(field=True)
    with il._lock:
        assert il._current_keystrokes == []
        assert il._current_events == events_before
        assert il._current_modifiers == set()
        assert il._last_key_activity_mono is None


def test_T_F3_11_pause_cancels_pending_idle_no_resurrect():
    _seed_keys(["s", "e", "c"], at=0.0)
    il._set_pause(field=True)  # at conceptual t=0.4
    il._set_pause(field=False)  # at conceptual t=0.6
    assert _idle_check(0.6) is False
    assert _idle_check(2.0) is False
    with il._lock:
        assert "sec" not in il._current_events
        assert il._current_keystrokes == []


def test_T_F3_12_paused_key_press_ignored():
    il._set_pause(field=True)
    with patch.object(il, "sync_secure_field_from_focus", return_value=True):
        il.on_press(char_key("x"))
    with il._lock:
        assert il._current_keystrokes == []
    assert _idle_check(1.0) is False


def test_T_F3_13_idle_while_paused_no_append():
    _seed_keys(["a"], at=0.0)
    # Simulate race: buffer still present but pause edge should clear;
    # force paused + leftover deadline should still no-op if we re-pause after seed.
    il._set_pause(field=True)
    # Inject stale buffer+deadline as if timer raced (should still not flush while paused).
    with il._lock:
        il._current_keystrokes.extend(["leak"])
        il._last_key_activity_mono = 0.0
        il._is_paused = True
    events_before = list(il._current_events)
    assert _idle_check(1.0) is False
    with il._lock:
        assert il._current_events == events_before


def test_T_F3_14_post_unpause_burst_only_new_keys():
    _seed_keys(["s", "e", "c"], at=0.0)
    il._set_pause(field=True)
    il._set_pause(field=False)
    _seed_keys(["o", "k"], at=1.0)
    assert _idle_check(1.5) is True
    with il._lock:
        assert il._current_events[-1] == "ok"
        assert "sec" not in "".join(il._current_events)


# --- Mid-type add_event ---


def test_T_F3_15_add_event_flushes_keys_first():
    _seed_keys(["x"], at=0.0)
    il.add_event("🖱️ click")
    with il._lock:
        assert il._current_events == ["x", "🖱️ click"]
        assert il._current_keystrokes == []


# --- Window switch ---


def test_T_F3_16_heading_change_seals_mid_buffer():
    with il._lock:
        il._current_heading = "A"
        il._current_events.clear()
    _seed_keys(["a"], at=0.0)
    il.apply_heading_change("B")
    with il._lock:
        assert il._current_heading == "B"
        assert il._current_keystrokes == []
        assert il._current_events == []
        assert len(il._sections) == 1
        assert il._sections[0]["heading"] == "A"
        assert il._sections[0]["events"] == ["a"]
        assert il._last_key_activity_mono is None


def test_T_F3_17_heading_change_with_prior_burst_and_buffer():
    with il._lock:
        il._current_heading = "A"
        il._current_events[:] = ["hello"]
    _seed_keys(["!"], at=0.0)
    il.apply_heading_change("B")
    with il._lock:
        assert il._sections[-1]["heading"] == "A"
        assert il._sections[-1]["events"] == ["hello", "!"]
        assert il._current_events == []
        assert il._current_heading == "B"


# --- File flush coordination ---


def test_T_F3_18_flush_to_file_seals_open_events(tmp_path: Path):
    with il._lock:
        il._current_heading = "App - Win"
        il._current_events[:] = ["hello", "world"]
        il._current_keystrokes.clear()
    il.flush_to_file()
    with il._lock:
        assert il._current_events == []
        assert il._sections == []
    log = next((tmp_path / "logs").glob("daily_log_*.md"))
    text = log.read_text(encoding="utf-8")
    assert "hello" in text
    assert "world" in text


def test_T_F3_19_file_writer_uses_flush_interval_sec():
    cfg = replace(default_config(), log_dir=Path(il.LOG_DIR), flush_interval_sec=5)
    il.apply_config(cfg)
    assert il.FLUSH_INTERVAL_SEC == 5
    waited: list[float] = []

    def _wait(sec: float) -> bool:
        waited.append(sec)
        raise StopIteration

    with patch.object(il._writer_wakeup, "wait", side_effect=_wait):
        with pytest.raises(StopIteration):
            il.file_writer_loop()
    assert waited[0] == 5


# --- F5 reason / trigger contract ---


def test_T_F3_20_key_flush_cause_typing_pause_no_section_seal():
    causes: list[str] = []
    _seed_keys(["z"], at=0.0)
    sections_len = len(il._sections)

    def _hook(cause: str) -> None:
        causes.append(cause)

    prev = getattr(il, "_key_flush_hook", None)
    il._key_flush_hook = _hook
    try:
        assert _idle_check(0.5) is True
    finally:
        il._key_flush_hook = prev
    assert causes == ["typing_pause"]
    assert il._last_key_flush_cause == "typing_pause"
    assert len(il._sections) == sections_len


def test_T_F3_21_later_file_flush_seal_not_typing_pause_trigger(tmp_path: Path):
    """Typing-pause chunks events only; a later file-flush seal must not use trigger typing_pause."""
    il.CAPTURE_TRIGGERS_ENABLED = True
    _seed_keys(["a"], at=0.0)
    assert _idle_check(0.5) is True
    _seed_keys(["b"], at=1.0)
    assert _idle_check(1.5) is True
    with il._lock:
        assert il._current_events == ["a", "b"]
        assert il._sections == []  # F3: no section seal from typing pause
    # Idle leaves key-flush cause; seal must not copy it as F5 trigger.
    assert il._last_key_flush_cause == "typing_pause"

    sealed: list[dict] = []

    class _SpySections(list):
        def append(self, item):  # noqa: ANN001
            sealed.append(dict(item) if isinstance(item, dict) else item)
            return super().append(item)

    with il._lock:
        il.rebind_capture_buffers()
        il._sections = _SpySections(list(il._sections))
    try:
        il.flush_to_file()
        assert sealed, "file flush must seal open typing-pause events"
        for section in sealed:
            assert section.get("events") == ["a", "b"]
            assert section.get("trigger") != "typing_pause"
            if "trigger" in section:
                assert section["trigger"] == "file_flush"
        log = next((tmp_path / "logs").glob("daily_log_*.md"))
        text = log.read_text(encoding="utf-8")
        assert "trigger:typing_pause" not in text
        assert "a" in text and "b" in text
    finally:
        with il._lock:
            # Restore LoggerState list identity after spy substitution.
            data = list(il._sections)
            il._state.sections.clear()
            il._state.sections.extend(data)
            il.rebind_capture_buffers()


# --- Modifier-only and races ---


def test_T_F3_22_modifier_only_does_not_reset_idle():
    _seed_keys(["a"], at=0.0)
    with patch.object(il, "sync_secure_field_from_focus", return_value=False):
        il.on_press(keyboard_key("cmd"))
        il.on_press(keyboard_key("shift"))
    assert _idle_check(0.5) is True
    with il._lock:
        assert il._current_events[-1] == "a"


def test_T_F3_23_idle_and_add_event_no_duplicate():
    _seed_keys(["xy"], at=0.0)
    # Concurrent under same lock semantics: idle first then add_event, or reverse
    with il._lock:
        # about to fire
        assert il._last_key_activity_mono == 0.0
    assert _idle_check(0.5) is True
    il.add_event("🖱️ click")
    with il._lock:
        assert il._current_events.count("xy") == 1
        assert "🖱️ click" in il._current_events

    # Reverse order path
    with il._lock:
        il._current_events.clear()
        il._current_keystrokes[:] = ["zz"]
        il._last_key_activity_mono = 0.0
    il.add_event("🖱️ other")
    assert _idle_check(0.5) is False
    with il._lock:
        assert il._current_events == ["zz", "🖱️ other"]
        assert il._current_events.count("zz") == 1


def test_T_F3_24_idle_and_heading_change_no_duplicate():
    with il._lock:
        il._current_heading = "A"
        il._current_events.clear()
    _seed_keys(["q"], at=0.0)
    assert _idle_check(0.5) is True
    il.apply_heading_change("B")
    with il._lock:
        joined = []
        for sec in il._sections:
            joined.extend(sec["events"])
        joined.extend(il._current_events)
        assert joined.count("q") == 1

    with il._lock:
        il._sections.clear()
        il._current_heading = "A"
        il._current_events.clear()
        il._current_keystrokes[:] = ["r"]
        il._last_key_activity_mono = 0.0
    il.apply_heading_change("B")
    assert _idle_check(0.5) is False
    with il._lock:
        assert il._sections[0]["events"] == ["r"]
        assert "".join(il._current_keystrokes) == ""


# --- Key helpers (no live pynput required beyond module import) ---


def keyboard_key(name: str):
    """Build a pynput-like Key for on_press/on_release tests."""
    key = getattr(il.keyboard.Key, name)
    return key


def char_key(ch: str):
    return SimpleNamespace(char=ch)
