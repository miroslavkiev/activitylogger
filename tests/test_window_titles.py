"""F1 native-first window titles (TDD)."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

import interleaved_logger as il
from markdown_format import format_markdown_fenced_text, sanitize_markdown_inline


@pytest.fixture(autouse=True)
def _reset_logger_state(reset_logger_state):
    reset_logger_state()
    yield


# --- Resolution order ---


def test_resolve_window_prefers_native_over_aw():
    with (
        patch.object(il, "get_native_window", return_value=("Safari", "Docs")) as native,
        patch.object(il, "get_activitywatch_window", return_value=("Other", "AW Title")) as aw,
    ):
        assert il.resolve_window() == ("Safari", "Docs")
        native.assert_called_once()
        # Native complete → skip ActivityWatch HTTP
        aw.assert_not_called()


def test_resolve_window_skips_aw_when_native_complete():
    with (
        patch.object(il, "get_native_window", return_value=("Safari", "Docs")),
        patch.object(il, "get_activitywatch_window") as aw,
    ):
        assert il.resolve_window() == ("Safari", "Docs")
        aw.assert_not_called()


def test_resolve_window_aw_fills_empty_native_title():
    with (
        patch.object(il, "get_native_window", return_value=("Safari", "")),
        patch.object(il, "get_activitywatch_window", return_value=("Safari", "GitHub")),
    ):
        assert il.resolve_window() == ("Safari", "GitHub")


def test_resolve_window_aw_fills_empty_native_app():
    with (
        patch.object(il, "get_native_window", return_value=("", "Some Title")),
        patch.object(il, "get_activitywatch_window", return_value=("Mail", "Some Title")),
    ):
        assert il.resolve_window() == ("Mail", "Some Title")


def test_resolve_window_aw_does_not_override_native_app():
    with (
        patch.object(il, "get_native_window", return_value=("Safari", "")),
        patch.object(il, "get_activitywatch_window", return_value=("Chrome", "GitHub")),
    ):
        assert il.resolve_window() == ("Safari", "GitHub")


def test_resolve_window_aw_down_uses_native_only():
    with (
        patch.object(il, "get_native_window", return_value=("Terminal", "bash")),
        patch.object(il, "get_activitywatch_window", side_effect=RuntimeError("down")),
    ):
        assert il.resolve_window() == ("Terminal", "bash")


def test_resolve_window_aw_disabled_skips_http():
    il.ACTIVITYWATCH_ENRICHER = False
    with (
        patch.object(il, "get_native_window", return_value=("Safari", "")),
        patch.object(il, "get_activitywatch_window", return_value=("Chrome", "GitHub")) as aw,
    ):
        assert il.resolve_window() == ("Safari", "")
        aw.assert_not_called()


def test_resolve_window_both_empty_returns_empty_pair():
    with (
        patch.object(il, "get_native_window", return_value=("", "")),
        patch.object(il, "get_activitywatch_window", return_value=("", "")),
    ):
        assert il.resolve_window() == ("", "")


def test_resolve_window_ax_unavailable_allows_aw_fill():
    with (
        patch.object(il, "get_native_window", return_value=("", "")),
        patch.object(il, "get_activitywatch_window", return_value=("Mail", "Inbox")),
    ):
        assert il.resolve_window() == ("Mail", "Inbox")


def test_get_active_window_no_longer_sole_source():
    order: list[str] = []

    def native():
        order.append("native")
        return ("Safari", "")  # incomplete → AW may fill

    def aw():
        order.append("aw")
        return ("Other", "AW")

    with (
        patch.object(il, "get_native_window", side_effect=native),
        patch.object(il, "get_activitywatch_window", side_effect=aw),
    ):
        result = il.resolve_window()
    assert result == ("Safari", "AW")
    assert order[0] == "native"
    assert "aw" in order


def test_resolve_window_aw_backoff_skips_http():
    il._state.aw_backoff_until = time.monotonic() + 60.0
    with (
        patch.object(il, "get_native_window", return_value=("Safari", "")),
        patch.object(il, "get_activitywatch_window") as aw,
    ):
        assert il.resolve_window() == ("Safari", "")
        aw.assert_not_called()
    il._state.aw_backoff_until = 0.0


def test_activitywatch_failure_sets_backoff():
    il._state.aw_backoff_until = 0.0
    il._window_bucket = "aw-watcher-window_test"
    with patch("interleaved_logger.requests.get", side_effect=RuntimeError("down")):
        assert il.get_activitywatch_window() == ("", "")
    assert il._state.aw_backoff_until > time.monotonic()
    il._state.aw_backoff_until = 0.0
    il._window_bucket = None


# --- Heading / placeholder ---


def test_heading_uses_unknown_window_not_aw_hint():
    body = il.build_heading_body("Safari", "")
    assert body == "Safari \u2014 Unknown window"
    assert "ActivityWatch" not in body
    assert not hasattr(il, "AW_HINT")


def test_heading_normalizes_untrusted_multiline_metadata():
    body = il.build_heading_body("  Safari\t", "Docs\n## injected\x00 title  ")
    assert body == "Safari \u2014 Docs ## injected title"
    assert "\n" not in body
    assert "\x00" not in body


def test_shared_inline_sanitizer_and_fence_are_structurally_safe():
    assert sanitize_markdown_inline(" A\r\n\tB\x7f\x85 C ") == "A B C"
    block = format_markdown_fenced_text("alpha\n```\n````\nomega", "text")
    lines = block.splitlines()
    assert lines[0] == "`````text"
    assert lines[-1] == "`````"
    assert "```" in lines
    assert "````" in lines


def test_heading_uses_em_dash_separator():
    body = il.build_heading_body("Safari", "Docs")
    assert body is not None
    assert " \u2014 " in body
    assert "\u2014" in body
    assert " - " not in body.replace(" \u2014 ", "")


def test_fallback_heading_has_no_aw_instruction():
    assert il.FALLBACK_HEADING == "Unknown \u2014 Unknown window"
    assert "ActivityWatch not running" not in il.FALLBACK_HEADING
    assert "ActivityWatch" not in il.FALLBACK_HEADING


def test_markdown_section_line_format(tmp_path, monkeypatch):
    monkeypatch.setattr(il, "LOG_DIR", tmp_path)
    monkeypatch.setattr(il, "_get_filepath", lambda *_args: tmp_path / "daily_log_test.md")
    with patch.object(il, "refresh_secure_field_focus", return_value=False):
        assert il.apply_resolved_window("Safari", "Example") is True
    with il._lock:
        il._current_events.append("typed hello")
    il.flush_to_file()
    text = (tmp_path / "daily_log_test.md").read_text(encoding="utf-8")
    assert "## Safari \u2014 Example" in text
    assert "typed hello" in text


def test_both_empty_skips_heading_update():
    with il._lock:
        il._current_heading = "Keep \u2014 Me"
    applied = il.apply_resolved_window("", "")
    assert applied is False
    with il._lock:
        assert il._current_heading == "Keep \u2014 Me"


# --- Secure pause inputs ---


def test_secure_pause_from_native_app_name():
    assert il._is_secure_app_name("1Password", "Vault") is True
    with patch.object(il, "refresh_secure_field_focus", return_value=False):
        assert il.apply_resolved_window("1Password", "Vault") is True
    assert il._pause_secure_app is True
    with il._lock:
        assert il._current_heading.startswith("🔒 [SECURE APP PAUSED] ")
        assert "1Password" in il._current_heading
        assert "Vault" in il._current_heading


def test_secure_pause_from_native_title_token():
    assert il._is_secure_app_name("Safari", "Bitwarden \u2014 Login") is True
    with patch.object(il, "refresh_secure_field_focus", return_value=False):
        assert il.apply_resolved_window("Safari", "Bitwarden \u2014 Login") is True
    assert il._pause_secure_app is True
    with il._lock:
        assert "Bitwarden \u2014 Login" in il._current_heading
        assert il._current_heading.startswith("🔒 [SECURE APP PAUSED] ")


def test_non_secure_native_window_does_not_pause_by_name():
    assert il._is_secure_app_name("Safari", "Example") is False
    with patch.object(il, "refresh_secure_field_focus", return_value=False):
        assert il.apply_resolved_window("Safari", "Example") is True
    assert il._pause_secure_app is False
    assert il.is_paused() is False


def test_secure_pause_uses_same_pair_as_heading():
    app, title = "1Password", "Vault"
    with patch.object(il, "refresh_secure_field_focus", return_value=False):
        il.apply_resolved_window(app, title)
    with il._lock:
        heading = il._current_heading
    assert il._is_secure_app_name(app, title) is True
    assert heading == f"🔒 [SECURE APP PAUSED] {app} \u2014 {title}"
    assert "Unknown window" not in heading


def test_secure_pause_empty_title_uses_unknown_window_placeholder():
    """Heading gets Unknown window; pause still uses pre-placeholder title."""
    with patch.object(il, "refresh_secure_field_focus", return_value=False):
        assert il.apply_resolved_window("1Password", "") is True
    assert il._pause_secure_app is True
    with il._lock:
        assert il._current_heading == "🔒 [SECURE APP PAUSED] 1Password \u2014 Unknown window"
