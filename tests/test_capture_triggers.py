"""F5 capture-trigger metadata — TDD cases T-F5-01…19."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

import clean_markdown_log as cleaner
import interleaved_logger as il
from tests.helpers import _seed_keys, enable_features


@pytest.fixture(autouse=True)
def _reset_logger_state(reset_logger_state):
    reset_logger_state(capture_triggers_enabled=False)
    yield


# --- Closed set / format ---


def test_T_F5_01_closed_set_constant():
    assert isinstance(il.CAPTURE_TRIGGERS, frozenset)
    assert all(isinstance(name, str) and name for name in il.CAPTURE_TRIGGERS)


def test_T_F5_02_reject_unknown_trigger_on_write():
    with pytest.raises((ValueError, AssertionError)):
        il.format_section_timestamp_line("12:00:00", trigger="idle")


def test_T_F5_03_format_helper():
    assert (
        il.format_section_timestamp_line("14:02:11", trigger="app_switch")
        == "*14:02:11 · trigger:app_switch*"
    )
    assert "trigger: " not in il.format_section_timestamp_line(
        "14:02:11", trigger="app_switch"
    )


# --- Seal causes (flag ON) ---


def test_T_F5_04_app_switch_seals_with_app_switch(tmp_path: Path):
    enable_features(tmp_path, capture_triggers_enabled=True)
    with il._lock:
        il._current_heading = "AppA — WinA"
        il._current_events[:] = ["typed"]
    il.apply_heading_change("AppB — WinB")
    with il._lock:
        assert len(il._sections) == 1
        sec = il._sections[0]
        assert sec["heading"] == "AppA — WinA"
        assert sec["trigger"] == "app_switch"
        assert sec["events"] == ["typed"]
        assert il._current_heading == "AppB — WinB"
        assert il._current_events == []


def test_T_F5_05_periodic_flush_seals_with_file_flush(tmp_path: Path):
    enable_features(tmp_path, capture_triggers_enabled=True)
    with il._lock:
        il._current_heading = "App — Window"
        il._current_events[:] = ["hello"]
    il.flush_to_file()
    log = next((tmp_path / "logs").glob("daily_log_*.md"))
    text = log.read_text(encoding="utf-8")
    assert "trigger:file_flush" in text
    assert "hello" in text


def test_T_F5_06_click_seals_with_click(tmp_path: Path):
    enable_features(tmp_path, capture_triggers_enabled=True)
    _seed_keys(["h", "i"])
    il.record_click_event("Button 'OK'")
    with il._lock:
        assert len(il._sections) == 1
        sec = il._sections[0]
        assert sec["trigger"] == "click"
        assert sec["events"] == ["hi", "🖱️ **Клік:** Button 'OK'"]
        assert il._current_events == []
        assert il._current_keystrokes == []


def test_T_F5_07_clipboard_seals_with_clipboard(tmp_path: Path):
    enable_features(tmp_path, capture_triggers_enabled=True)
    _seed_keys(["a", "b"])
    _, _, event = il.apply_clipboard_change(2, "paste-me", False, 1, "")
    assert event is not None
    il.record_clipboard_event(event)
    with il._lock:
        assert len(il._sections) == 1
        sec = il._sections[0]
        assert sec["trigger"] == "clipboard"
        assert "ab" in sec["events"][0]
        assert any("CLIPBOARD" in e for e in sec["events"])


def test_T_F5_08_paused_click_does_not_seal_secrets(tmp_path: Path):
    enable_features(tmp_path, capture_triggers_enabled=True)
    with il._lock:
        il._current_keystrokes[:] = ["s", "e", "c"]
        il._current_events[:] = ["secret-event"]
    il._set_pause(field=True)
    il.record_click_event("Button")
    with il._lock:
        assert il._sections == []
        assert "secret-event" not in [
            e for s in il._sections for e in s.get("events", [])
        ]


def test_T_F5_09_paused_clipboard_does_not_seal_secrets(tmp_path: Path):
    enable_features(tmp_path, capture_triggers_enabled=True)
    count, text, event = il.apply_clipboard_change(
        2, "password-secret", True, 1, ""
    )
    assert event is None
    assert count == 2
    assert text == "password-secret"
    with il._lock:
        assert il._sections == []
        assert il._current_events == []
    # No trigger:clipboard section written
    il.flush_to_file()
    logs = list((tmp_path / "logs").glob("daily_log_*.md"))
    if logs:
        assert "trigger:clipboard" not in logs[0].read_text(encoding="utf-8")
        assert "password-secret" not in logs[0].read_text(encoding="utf-8")


# --- Cleaner dual format ---


def test_T_F5_10_cleaner_accepts_legacy_timestamp():
    lines = [
        "# Work Log — 2026-01-01\n",
        "\n",
        "## App — Window\n",
        "*12:00:00*\n",
        "\n",
        "hello\n",
        "\n",
        "---\n",
    ]
    preamble, sections = cleaner.split_into_preamble_and_sections(lines)
    assert len(sections) == 1
    assert sections[0].timestamp.strip() == "*12:00:00*"
    assert cleaner.is_timestamp_line("*12:00:00*\n")


def test_T_F5_11_cleaner_accepts_trigger_timestamp():
    lines = [
        "# Work Log — 2026-01-01\n",
        "\n",
        "## App — Window\n",
        "*12:00:00 · trigger:app_switch*\n",
        "\n",
        "hello\n",
        "\n",
        "---\n",
    ]
    preamble, sections = cleaner.split_into_preamble_and_sections(lines)
    assert len(sections) == 1
    assert "trigger:app_switch" in sections[0].timestamp
    out = cleaner.sanitize_section_body(sections[0].body)
    assert any("hello" in ln for ln in out)
    # FR-F5-009.4: kept sections preserve the trigger timestamp line
    kept = []
    kept.extend(preamble)
    for sec in sections:
        cleaned_body = cleaner.sanitize_section_body(sec.body)
        if not cleaner.section_has_meaningful_content(cleaned_body):
            continue
        kept.append(sec.header)
        if sec.timestamp:
            kept.append(sec.timestamp)
        kept.extend(cleaned_body)
    assert any("trigger:app_switch" in ln for ln in kept)


def test_T_F5_12_cleaner_trigger_line_not_noise_event():
    ts = "*12:00:00 · trigger:file_flush*\n"
    assert cleaner.is_timestamp_line(ts)
    assert not cleaner.is_event_candidate_line(ts)
    body = ["\n", "---\n", "\n"]
    assert cleaner.section_has_meaningful_content(body) is False


# --- Round-trip / contracts ---


def test_T_F5_13_file_output_round_trip(tmp_path: Path):
    enable_features(tmp_path, capture_triggers_enabled=True)
    with il._lock:
        il._sections.append(
            {
                "heading": "Safari — Example",
                "events": ["hello world"],
                "timestamp": "14:02:40",
                "trigger": "file_flush",
            }
        )
    il.flush_to_file()
    text = next((tmp_path / "logs").glob("daily_log_*.md")).read_text(
        encoding="utf-8"
    )
    assert "## Safari — Example\n" in text
    assert "*14:02:40 · trigger:file_flush*" in text
    assert "hello world" in text
    assert "---" in text


def test_T_F5_14_sibling_name_reservation(tmp_path: Path):
    assert "typing_pause" in il.CAPTURE_TRIGGERS
    assert "url_change" in il.CAPTURE_TRIGGERS
    assert "scroll_coalesce" in il.CAPTURE_TRIGGERS
    # F3 v1 must not emit typing_pause as section trigger
    with il._lock:
        il._current_keystrokes[:] = ["x"]
        il._last_key_activity_mono = 0.0
    assert il.check_typing_pause_idle(now=1.0) is True
    with il._lock:
        assert il._sections == []
        assert il._last_key_flush_cause == "typing_pause"
    # Reserved: seal path rejects typing_pause even when flag ON
    enable_features(tmp_path, capture_triggers_enabled=True)
    with il._lock:
        il._current_events[:] = ["chunk"]
        with pytest.raises(ValueError, match="typing_pause"):
            il._seal_open_events_locked("typing_pause")
        assert il._sections == []
    # Intended mappings (stubs until F4/F6 land)
    assert (
        il.format_section_timestamp_line("10:00:00", trigger="url_change")
        == "*10:00:00 · trigger:url_change*"
    )
    assert (
        il.format_section_timestamp_line("10:00:01", trigger="scroll_coalesce")
        == "*10:00:01 · trigger:scroll_coalesce*"
    )


def test_T_F5_15_gemini_prompt_mentions_triggers():
    prompt = Path("prompts/gemini-automation-analysis.md").read_text(
        encoding="utf-8"
    )
    assert "trigger:" in prompt
    assert "app_switch" in prompt
    assert "file_flush" in prompt
    assert "older" in prompt.lower() or "omit" in prompt.lower()
    # FR-F5-010 / §12: closed set with short meanings
    assert "heading changed" in prompt or "app/window" in prompt
    assert "reserved" in prompt.lower()
    assert "do not invent" in prompt.lower()


# --- Flag OFF ---


def test_T_F5_16_flag_off_writes_legacy_timestamp(tmp_path: Path):
    assert il.CAPTURE_TRIGGERS_ENABLED is False
    with il._lock:
        il._current_heading = "App — Window"
        il._current_events[:] = ["typed"]
    il.apply_heading_change("Other — Win")
    il.flush_to_file()
    text = next((tmp_path / "logs").glob("daily_log_*.md")).read_text(
        encoding="utf-8"
    )
    assert "trigger:" not in text
    assert "*typed*" not in text  # sanity
    # Legacy italic time only
    import re

    assert re.search(r"\*\d{2}:\d{2}:\d{2}\*", text)
    assert " · trigger:" not in text


def test_T_F5_17_flag_off_does_not_seal_on_click(tmp_path: Path):
    assert il.CAPTURE_TRIGGERS_ENABLED is False
    _seed_keys(["h", "i"])
    il.record_click_event("Button")
    with il._lock:
        assert il._sections == []
        assert il._current_events == ["hi", "🖱️ **Клік:** Button"]


def test_T_F5_18_flag_off_does_not_seal_on_clipboard(tmp_path: Path):
    assert il.CAPTURE_TRIGGERS_ENABLED is False
    _seed_keys(["a"])
    _, _, event = il.apply_clipboard_change(2, "clip", False, 1, "")
    assert event is not None
    il.record_clipboard_event(event)
    with il._lock:
        assert il._sections == []
        assert len(il._current_events) == 2


def test_T_F5_19_no_migration_rewrite(tmp_path: Path):
    fixture = tmp_path / "legacy_daily_log.md"
    fixture.write_text(
        "# Work Log — 2026-01-01\n\n"
        "## App — Window\n"
        "*09:00:00*\n\n"
        "legacy body\n\n"
        "---\n",
        encoding="utf-8",
    )
    before = fixture.read_bytes()
    # Clean path reads without rewriting source
    lines = cleaner.read_text_file(str(fixture))
    cleaner.split_into_preamble_and_sections(lines)
    # New write goes elsewhere
    enable_features(tmp_path, capture_triggers_enabled=True)
    with il._lock:
        il._current_events[:] = ["new"]
    il.flush_to_file()
    assert fixture.read_bytes() == before
    # Copy fixture and confirm shutil copy also untouched by F5 paths
    copy = tmp_path / "legacy_copy.md"
    shutil.copy(fixture, copy)
    assert copy.read_bytes() == before
