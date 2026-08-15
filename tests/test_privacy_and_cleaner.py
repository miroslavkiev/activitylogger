"""Unit tests for ActivityLogger privacy, flush, queue, and cleaner helpers."""

from __future__ import annotations

import queue
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import clean_markdown_log as cleaner
import interleaved_logger as il


@pytest.fixture(autouse=True)
def _reset_logger_state():
    with il._lock:
        il._current_heading = ""
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
    # Keep privacy baseline after config injection tests
    il.SECURE_APPS = {
        "1password",
        "bitwarden",
        "keychain",
        "keepass",
        "lastpass",
        "passwords",
    }
    # Drain AX queue
    while True:
        try:
            il._ax_jobs.get_nowait()
            il._ax_jobs.task_done()
        except queue.Empty:
            break
    yield


def test_stale_cache_false_does_not_clear_pause_after_secure_mark():
    """P0: after secure click marks pause+cache True, stale False must not clear."""
    il._mark_secure_field_cache(True)
    il._set_pause(field=True)
    assert il.is_paused() is True

    # Simulate stale cache flipped incorrectly without force
    il._secure_field_cache = False
    # TTL still valid → sync without force must NOT clear
    with patch.object(il, "refresh_secure_field_focus", return_value=False) as mock_ref:
        il.sync_secure_field_from_focus(force=False)
        mock_ref.assert_called_once_with(force=False)
    assert il.is_paused() is True
    assert il._pause_secure_field is True


def test_force_refresh_false_clears_field_pause():
    il._set_pause(field=True)
    with patch.object(il, "refresh_secure_field_focus", return_value=False):
        il.sync_secure_field_from_focus(force=True)
    assert il._pause_secure_field is False
    assert il.is_paused() is False


def test_force_refresh_true_sets_field_pause():
    with patch.object(il, "refresh_secure_field_focus", return_value=True):
        il.sync_secure_field_from_focus(force=False)
    assert il._pause_secure_field is True
    assert il.is_paused() is True


def test_add_event_noop_when_paused():
    il._set_pause(field=True)
    il.add_event("should not appear")
    with il._lock:
        assert il._current_events == []


def test_recompute_clears_keystrokes_on_pause_edge():
    with il._lock:
        il._current_keystrokes.extend(["a", "b"])
        il._current_modifiers.add("SHIFT")
    il._set_pause(field=True)
    with il._lock:
        assert il._current_keystrokes == []
        assert il._current_modifiers == set()


def test_clipboard_while_paused_advances_markers_no_event():
    count, text, event = il.apply_clipboard_change(
        count=2,
        text="secret-password",
        paused=True,
        last_count=1,
        last_text="",
    )
    assert count == 2
    assert text == "secret-password"
    assert event is None


def test_clipboard_secret_not_logged_after_unpause():
    count, text, event = il.apply_clipboard_change(
        count=2,
        text="secret-password",
        paused=True,
        last_count=1,
        last_text="",
    )
    count2, text2, event2 = il.apply_clipboard_change(
        count=2,
        text="secret-password",
        paused=False,
        last_count=count,
        last_text=text,
    )
    assert event is None
    assert event2 is None
    assert text2 == "secret-password"
    assert count2 == 2


def test_clipboard_new_text_after_unpause_is_logged():
    _, text, _ = il.apply_clipboard_change(2, "secret", True, 1, "")
    _, _, event = il.apply_clipboard_change(3, "hello world", False, 2, text)
    assert event is not None
    assert "hello world" in event
    assert "secret" not in event


def test_is_secure_app_name_positive_and_negative():
    assert il._is_secure_app_name("1Password", "Vault")
    assert il._is_secure_app_name("Safari", "Bitwarden — Login")
    assert not il._is_secure_app_name("Safari", "Example")


def test_flush_restore_on_body_write_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(il, "LOG_DIR", tmp_path)
    monkeypatch.setattr(il, "_get_filepath", lambda: tmp_path / "daily_log_test.md")
    # Pretend file exists so header path is skipped
    (tmp_path / "daily_log_test.md").write_text("# existing\n", encoding="utf-8")

    batch = [{"heading": "App — Win", "events": ["typed"], "timestamp": "12:00:00"}]
    with il._lock:
        il._sections = list(batch)

    def fail_write(filepath, lines, append=True):
        return False

    monkeypatch.setattr(il, "_write_to_file", fail_write)
    il.flush_to_file()
    with il._lock:
        assert il._sections == batch


def test_flush_success_clears_sections(tmp_path, monkeypatch):
    monkeypatch.setattr(il, "LOG_DIR", tmp_path)
    path = tmp_path / "daily_log_test.md"
    path.write_text("# existing\n", encoding="utf-8")
    monkeypatch.setattr(il, "_get_filepath", lambda: path)

    with il._lock:
        il._sections = [{"heading": "H", "events": ["e"], "timestamp": "01:02:03"}]
    il.flush_to_file()
    with il._lock:
        assert il._sections == []
    assert "e" in path.read_text(encoding="utf-8")


def test_enqueue_ax_drops_on_full_without_raising():
    # Fill with click jobs (scans coalesce)
    while True:
        try:
            il._ax_jobs.put_nowait(("click", 0, 0))
        except queue.Full:
            break
    il._enqueue_ax(("click", 1, 1))  # must not raise
    assert il._ax_jobs.full()


def test_enqueue_ax_coalesces_scans():
    il._enqueue_ax(("scan",))
    il._enqueue_ax(("scan",))
    jobs = []
    while True:
        try:
            jobs.append(il._ax_jobs.get_nowait())
            il._ax_jobs.task_done()
        except queue.Empty:
            break
    assert jobs.count(("scan",)) == 1


def test_intra_block_repeat_marker_always_ends_with_newline():
    lines = ["spam\n"] * (cleaner.INTRA_BLOCK_REPEAT_THRESHOLD + 2) + ["other\n"]
    out = cleaner.compress_repeated_lines_in_code_block(lines)
    assert out[0] == "spam\n"
    assert out[1].endswith("\n")
    assert "repeated" in out[1]
    assert out[2] == "other\n"


def test_traceback_stops_at_section_boundary():
    lines = [
        "Traceback (most recent call last):\n",
        '  File "/tmp/x.py", line 1, in <module>\n',
        "ValueError: boom\n",
        "## Next Section\n",
        "keep me\n",
    ]
    out = cleaner.compress_traceback_blocks(lines)
    assert any("## Next Section" in x for x in out)
    assert any("keep me" in x for x in out)


def test_traceback_does_not_swallow_following_prose():
    lines = [
        "Traceback (most recent call last):\n",
        '  File "/tmp/x.py", line 1, in <module>\n',
        "RuntimeError: fail\n",
        "Normal work continued in Safari\n",
    ]
    out = cleaner.compress_traceback_blocks(lines)
    assert any("Normal work continued in Safari" in x for x in out)
