"""F4 browser URL capture cases from docs/specs/F4-browser-url.md section 11."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import browser_url as bu
import interleaved_logger as il
from config import default_config, load_config
from tests.helpers import enable_features
from window_titles import build_heading_body


@pytest.fixture(autouse=True)
def _reset_logger_state(reset_logger_state):
    bu.set_url_provider(None)
    bu.set_unsafe_full_browser_urls(False)
    reset_logger_state(browser_url_capture=False, capture_triggers_enabled=False)
    yield
    bu.set_url_provider(None)
    bu.set_unsafe_full_browser_urls(False)


# --- Pure logic ---


def test_flag_off_never_emits():
    last, event = bu.apply_url_observation(
        enabled=False,
        paused=False,
        candidate="https://example.com",
        last_emitted=None,
    )
    assert event is None
    assert last is None
    assert not bu.should_emit_url(
        enabled=False,
        paused=False,
        candidate="https://example.com",
        last_emitted=None,
    )


def test_format_url_event_stable_prefix():
    assert bu.format_url_event("https://example.com/x") == "> [URL]: https://example.com/x"
    assert re.match(r"^> \[URL\]: \S", bu.format_url_event("https://example.com/x"))


def test_emit_on_first_url():
    last, event = bu.apply_url_observation(
        enabled=True,
        paused=False,
        candidate="https://a.test",
        last_emitted=None,
    )
    assert event == "> [URL]: https://a.test"
    assert last == "https://a.test"


def test_dedup_same_url():
    last, event = bu.apply_url_observation(
        enabled=True,
        paused=False,
        candidate="https://a.test",
        last_emitted="https://a.test",
    )
    assert event is None
    assert last == "https://a.test"


def test_emit_on_url_change():
    last, event = bu.apply_url_observation(
        enabled=True,
        paused=False,
        candidate="https://b.test",
        last_emitted="https://a.test",
    )
    assert event == "> [URL]: https://b.test"
    assert last == "https://b.test"


def test_paused_does_not_emit():
    last, event = bu.apply_url_observation(
        enabled=True,
        paused=True,
        candidate="https://secret.test",
        last_emitted=None,
    )
    assert event is None
    assert last == "https://secret.test"


def test_paused_url_not_flushed_after_resume():
    last, event = bu.apply_url_observation(
        enabled=True,
        paused=True,
        candidate="https://paused-only.test",
        last_emitted=None,
    )
    assert event is None
    assert last == "https://paused-only.test"

    last, event = bu.apply_url_observation(
        enabled=True,
        paused=False,
        candidate="https://paused-only.test",
        last_emitted=last,
    )
    assert event is None

    last, event = bu.apply_url_observation(
        enabled=True,
        paused=False,
        candidate="https://after.test",
        last_emitted=last,
    )
    assert event == "> [URL]: https://after.test"
    assert last == "https://after.test"


def test_empty_or_whitespace_url_rejected():
    assert bu.normalize_url_candidate("") is None
    assert bu.normalize_url_candidate("  ") is None
    last, event = bu.apply_url_observation(
        enabled=True,
        paused=False,
        candidate="   ",
        last_emitted=None,
    )
    assert event is None
    assert last is None


def test_url_longer_than_2000_truncated():
    long = "https://example.com/" + ("x" * 2500)
    norm = bu.normalize_url_candidate(long)
    assert norm is not None
    assert len(norm) == 2000
    last, event = bu.apply_url_observation(
        enabled=True,
        paused=False,
        candidate=long,
        last_emitted=None,
    )
    assert event == bu.format_url_event(norm)
    assert last == norm


def test_url_privacy_redacts_secrets_and_preserves_query_shape():
    raw = "https://user:pass@example.test/a?token=secret&blank=&flag&token=two#private"
    assert bu.normalize_url_candidate(raw) == (
        "https://example.test/a?REDACTED=REDACTED&REDACTED=REDACTED&"
        "REDACTED=REDACTED&REDACTED=REDACTED"
    )
    assert bu.normalize_url_candidate(raw, unsafe_full=True) == (
        "https://example.test/a?token=secret&blank=&flag&token=two"
    )


@pytest.mark.parametrize(
    "raw",
    (
        "ftp://example.test/file",
        "javascript:alert(1)",
        "https:///missing-host",
        "https://",
        "/relative/path",
        "https://example.test:bad/path",
    ),
)
def test_url_requires_http_scheme_and_valid_hostname(raw):
    assert bu.normalize_url_candidate(raw) is None
    assert bu.normalize_url_candidate(raw, unsafe_full=True) is None


def test_url_is_parsed_before_cap_and_always_drops_userinfo_and_fragment():
    raw = (
        "https://"
        + ("user" * 1000)
        + ":password@example.test/path?token=secret#"
        + ("private" * 1000)
    )
    assert bu.normalize_url_candidate(raw) == (
        "https://example.test/path?REDACTED=REDACTED"
    )
    assert bu.normalize_url_candidate(raw, unsafe_full=True) == (
        "https://example.test/path?token=secret"
    )


@pytest.mark.parametrize("control", ("\x00", "\x1f", "\n", "\x7f"))
def test_url_control_characters_are_rejected_in_all_modes(control):
    raw = f"https://example.test/path{control}Injected"
    assert bu.normalize_url_candidate(raw) is None
    assert bu.normalize_url_candidate(raw, unsafe_full=True) is None


def test_process_url_privacy_mode_is_configurable():
    raw = "https://user:pass@example.test/?token=secret#private"
    bu.set_unsafe_full_browser_urls(True)
    assert bu.normalize_url_candidate(raw) == "https://example.test/?token=secret"
    bu.set_unsafe_full_browser_urls(False)
    assert bu.normalize_url_candidate(raw) == "https://example.test/?REDACTED=REDACTED"


def test_is_browser_app_positive_negative():
    positives = (
        "Safari",
        "Google Chrome",
        "Microsoft Edge",
        "Brave Browser",
        "Arc",
        "Chromium",
        "Firefox",
    )
    negatives = ("Terminal", "Code", "Cursor", "1Password", "Finder")
    for name in positives:
        assert bu.is_browser_app(name), name
    for name in negatives:
        assert not bu.is_browser_app(name), name


def test_add_event_still_blocks_url_when_paused():
    with il._lock:
        il._is_paused = True
        il._current_events.clear()
    il.add_event(bu.format_url_event("https://should-not-land.test"))
    with il._lock:
        assert il._current_events == []


# --- Provider port ---


def test_provider_ax_preferred_when_present():
    got = bu.resolve_browser_url_sources(
        "Safari",
        ax_fetch=lambda _a: "https://from-ax.test",
        ae_fetch=lambda _a: "https://from-ae.test",
    )
    assert got == "https://from-ax.test"


def test_provider_falls_back_to_apple_events():
    got = bu.resolve_browser_url_sources(
        "Google Chrome",
        ax_fetch=lambda _a: None,
        ae_fetch=lambda _a: "https://from-ae.test",
    )
    assert got == "https://from-ae.test"


def test_provider_failure_returns_none():
    def boom(_a: str):
        raise RuntimeError("denied")

    got = bu.resolve_browser_url_sources("Safari", ax_fetch=boom, ae_fetch=boom)
    assert got is None


def test_provider_backs_off_failed_sources_across_calls():
    now = [100.0]
    calls = {"ax": 0, "ae": 0}

    def ax_fetch(_app):
        calls["ax"] += 1
        return None

    def ae_fetch(_app):
        calls["ae"] += 1
        return "https://example.test"

    provider = bu.MacBrowserUrlProvider(
        ax_fetch=ax_fetch,
        ae_fetch=ae_fetch,
        backoff_sec=30,
        clock=lambda: now[0],
    )
    assert provider.get_url("Safari") == "https://example.test"
    assert provider.get_url("Safari") == "https://example.test"
    assert calls == {"ax": 1, "ae": 2}
    assert provider.get_url("Google Chrome") == "https://example.test"
    assert calls == {"ax": 2, "ae": 3}
    now[0] += 31
    assert provider.get_url("Safari") == "https://example.test"
    assert calls == {"ax": 3, "ae": 4}


def test_ax_tree_walk_has_a_global_node_budget(monkeypatch):
    calls = 0

    def fake_attr(element, name):
        nonlocal calls
        if name == "AXURL":
            calls += 1
        if name == "AXChildren":
            return [(element, index) for index in range(12)]
        return None

    monkeypatch.setattr(bu, "_ax_attr", fake_attr)
    assert bu._ax_find_url_in_tree("root", 0, 10000, max_nodes=7) is None
    assert calls == 7


def test_ax_tree_walk_stops_at_deadline(monkeypatch):
    calls = 0
    now = [0.0]

    def fake_clock():
        now[0] += 0.04
        return now[0]

    def fake_attr(element, name):
        nonlocal calls
        if name == "AXURL":
            calls += 1
        if name == "AXChildren":
            return [(element, index) for index in range(12)]
        return None

    monkeypatch.setattr(bu, "_ax_attr", fake_attr)
    assert (
        bu._ax_find_url_in_tree(
            "root",
            0,
            10000,
            max_nodes=1000,
            deadline=0.1,
            clock=fake_clock,
        )
        is None
    )
    assert calls == 2


# --- Integration-style ---


def test_url_event_lands_under_current_heading(tmp_path: Path):
    enable_features(tmp_path, browser_url_capture=True)
    heading = build_heading_body("Google Chrome", "Title")
    assert heading is not None
    with il._lock:
        il._current_heading = heading
        il._current_events.clear()
        il._sections.clear()
    il.record_browser_url_observation("https://example.com/path")
    il.flush_to_file()
    text = (tmp_path / "logs" / Path(il._get_filepath()).name).read_text(encoding="utf-8")
    assert f"## {heading}" in text
    assert "> [URL]: https://example.com/path" in text
    heading_idx = text.index(f"## {heading}")
    url_idx = text.index("> [URL]: https://example.com/path")
    assert heading_idx < url_idx
    assert url_idx < text.index("---", heading_idx)


def test_title_and_url_same_cycle_url_under_new_heading(tmp_path: Path):
    enable_features(tmp_path, browser_url_capture=True)
    with patch.object(il, "refresh_secure_field_focus", return_value=False):
        il.apply_resolved_window("Google Chrome", "Old Title")
        il.process_window_check_cycle(
            "Google Chrome",
            "New Title",
            url="https://new.example/",
        )
    il.flush_to_file()
    text = (tmp_path / "logs" / Path(il._get_filepath()).name).read_text(encoding="utf-8")
    new_heading = build_heading_body("Google Chrome", "New Title")
    assert new_heading is not None
    assert f"## {new_heading}" in text
    url_idx = text.index("> [URL]: https://new.example/")
    heading_idx = text.index(f"## {new_heading}")
    assert heading_idx < url_idx


def test_flag_off_window_loop_skips_provider(tmp_path: Path):
    provider = MagicMock()
    provider.get_url.return_value = "https://should-not-fetch.test"
    bu.set_url_provider(provider)
    with patch.object(il, "refresh_secure_field_focus", return_value=False):
        il.process_window_check_cycle(
            "Google Chrome",
            "Example",
            url_provider=provider,
        )
    assert provider.get_url.call_count == 0


def test_f4_alone_does_not_write_trigger_metadata(tmp_path: Path):
    enable_features(tmp_path, browser_url_capture=True, capture_triggers_enabled=False)
    with il._lock:
        il._current_heading = "Google Chrome \u2014 Example Domain"
        il._current_events.clear()
        il._sections.clear()
    il.record_browser_url_observation("https://example.com/")
    il.flush_to_file()
    text = (tmp_path / "logs" / Path(il._get_filepath()).name).read_text(encoding="utf-8")
    assert "> [URL]: https://example.com/" in text
    assert "trigger:" not in text


def test_f4_with_f5_seals_url_change(tmp_path: Path):
    enable_features(tmp_path, browser_url_capture=True, capture_triggers_enabled=True)
    with il._lock:
        il._current_heading = "Google Chrome \u2014 Example Domain"
        il._current_events.clear()
        il._sections.clear()
        il._last_emitted_url = None
    il.record_browser_url_observation("https://example.com/")
    with il._lock:
        assert len(il._sections) == 1
        sec = il._sections[0]
        assert sec["trigger"] == "url_change"
        assert any("> [URL]: https://example.com/" in e for e in sec["events"])
        assert il._current_events == []


def test_secure_app_match_unchanged_with_url_helper(tmp_path: Path):
    enable_features(tmp_path, browser_url_capture=True)
    assert il._is_secure_app_name("1Password", "Vault") is True
    assert il._is_secure_app_name("Safari", "Example") is False
    last, event = bu.apply_url_observation(
        enabled=True,
        paused=False,
        candidate="https://vault.example/",
        last_emitted=None,
    )
    assert event is not None
    assert last is not None
    assert il._is_secure_app_name("1Password", "Vault") is True
    assert il._is_secure_app_name("Safari", "Bitwarden \u2014 Login") is True


# --- Constraint / grep guards ---


def test_no_screen_capture_imports_in_url_module():
    sources = [
        Path(bu.module_source_path()).read_text(encoding="utf-8"),
        Path(il.__file__).read_text(encoding="utf-8"),
    ]
    joined = "\n".join(sources)
    forbidden = (
        "CGWindowList",
        "CGDisplayStream",
        "screencapture",
        "pytesseract",
        "easyocr",
        "CGWindowListCreateImage",
    )
    for token in forbidden:
        assert token not in joined, token


def test_config_key_is_browser_url_capture(tmp_path: Path):
    cfg = default_config()
    assert cfg.browser_url_capture is False
    assert il.BROWSER_URL_CAPTURE is False
    path = tmp_path / "config.toml"
    path.write_text(
        "[features]\nbrowser_url_capture = true\n",
        encoding="utf-8",
    )
    loaded = load_config(path)
    assert loaded.browser_url_capture is True


def test_cleaner_leaves_url_event_lines_intact():
    """F4 §12: cleaner must not truncate or redact ``> [URL]:`` lines."""
    import clean_markdown_log as cleaner

    long_url = "https://example.com/" + ("q" * 800)
    line = bu.format_url_event(long_url) + "\n"
    assert len(line) > cleaner.MAX_PLAINTEXT_LINE_CHARS
    out = cleaner.sanitize_section_body([line, "---\n"])
    joined = "".join(out)
    assert f"> [URL]: {long_url}" in joined
    assert "Truncated" not in joined
