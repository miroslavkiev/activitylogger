#!/usr/bin/env python3
"""
Interleaved Work Log — macOS (v4)
Логує клавіатуру (з хоткеями), кліки, екран, буфер обміну + ЗАХИСТ ПАРОЛІВ.
"""

from __future__ import annotations

import fcntl
import os
import queue
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import requests

try:
    from pynput import keyboard, mouse

    PYNPUT_AVAILABLE = True
except ImportError:
    keyboard = None  # type: ignore
    mouse = None  # type: ignore
    PYNPUT_AVAILABLE = False

try:
    from AppKit import NSWorkspace, NSPasteboard, NSStringPboardType
    from ApplicationServices import (
        AXUIElementCreateSystemWide,
        AXUIElementCopyElementAtPosition,
        AXUIElementCopyAttributeValue,
        AXUIElementCreateApplication,
    )

    AX_AVAILABLE = True
except ImportError:
    AX_AVAILABLE = False

from browser_url import (
    apply_url_observation,
    get_frontmost_browser_url,
    is_browser_app,
    set_url_provider as set_browser_url_provider,
)
from config import AppConfig, ConfigError, ensure_log_dir, load_config, startup_diag_line
from scroll_coalesce import (
    ScrollBurst,
    accumulate as scroll_accumulate,
    discard_burst as scroll_discard,
    format_burst_line,
    mouse_listener_kwargs,
    should_flush as scroll_should_flush,
)
from window_titles import (
    FALLBACK_HEADING,
    build_heading_body,
    merge_native_and_aw,
)

__version__ = "4.1.0"

# Defaults match F2 §6.2 / pre-F2 constants. main() calls apply_config(load_config()).
AW_BASE_URL = "http://localhost:5600"
WINDOW_CHECK_SEC = 5
FLUSH_INTERVAL_SEC = 30
TYPING_PAUSE_SEC = 0.5
SECURE_FIELD_CACHE_SEC = 0.35
AX_QUEUE_MAXSIZE = 16
AX_MAX_DEPTH = 7
SCREEN_COMPARE_MAX_CHARS = 4000

SECURE_APPS: set[str] = {
    "1password",
    "bitwarden",
    "keychain",
    "keepass",
    "lastpass",
    "passwords",
}

ACTIVITYWATCH_ENRICHER = True
BROWSER_URL_CAPTURE = False
CAPTURE_TRIGGERS_ENABLED = False
SCROLL_COALESCE_ENABLED = False
SCROLL_COALESCE_MS = 400

# F5 closed set — writers use only these when capture_triggers_enabled.
# typing_pause is reserved (F3 v1 must not emit it as a section trigger).
# url_change / scroll_coalesce are reserved for F4 / F6 seal paths.
CAPTURE_TRIGGERS: frozenset[str] = frozenset(
    {
        "app_switch",
        "click",
        "typing_pause",
        "clipboard",
        "file_flush",
        "url_change",
        "scroll_coalesce",
    }
)

if PYNPUT_AVAILABLE:
    _MODIFIER_KEYS = {
        keyboard.Key.cmd: "CMD",
        keyboard.Key.cmd_l: "CMD",
        keyboard.Key.cmd_r: "CMD",
        keyboard.Key.ctrl: "CTRL",
        keyboard.Key.ctrl_l: "CTRL",
        keyboard.Key.ctrl_r: "CTRL",
        keyboard.Key.alt: "OPT",
        keyboard.Key.alt_l: "OPT",
        keyboard.Key.alt_r: "OPT",
        keyboard.Key.alt_gr: "OPT",
        keyboard.Key.shift: "SHIFT",
        keyboard.Key.shift_l: "SHIFT",
        keyboard.Key.shift_r: "SHIFT",
    }
else:
    _MODIFIER_KEYS = {}


def _resolve_log_dir() -> Path:
    """Default log dir when no config applied yet (import-time / tests)."""
    base = os.environ.get("HOME") or Path.home()
    if not Path(base).exists():
        try:
            import pwd

            base = pwd.getpwuid(os.getuid()).pw_dir
        except Exception:
            base = "/tmp"
    log_dir = Path(base) / "scripts" / "activitylogger" / "logs"
    try:
        ensure_log_dir(log_dir)
    except ConfigError:
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(log_dir, 0o700)
        except OSError:
            pass
    return log_dir


LOG_DIR = _resolve_log_dir()

_lock = threading.Lock()
_current_heading = ""
_current_keystrokes: list[str] = []
_current_events: list[str] = []
_sections: list[dict] = []

_last_screen_text = ""
_last_clipboard_count = 0
_last_clipboard_text = ""
_last_emitted_url: str | None = None

_pause_secure_app = False
_pause_secure_field = False
_is_paused = False
_current_modifiers: set[str] = set()

# F3 typing-pause: last buffer-mutating key activity (monotonic). None = idle inert.
_last_key_activity_mono: float | None = None
_last_key_flush_cause: str | None = None
_key_flush_hook = None  # optional Callable[[str], None] for tests

_secure_field_cache = False
_secure_field_cache_at = 0.0

_window_bucket: str | None = None
_ax_jobs: queue.Queue = queue.Queue(maxsize=AX_QUEUE_MAXSIZE)
_scan_pending = False
_ax_meta_lock = threading.Lock()
_instance_lock_file = None

_diag_last: dict[str, float] = {}
_DIAG_MIN_INTERVAL = 30.0
_APP_CONFIG: AppConfig | None = None

# F6 scroll coalesce — open burst (None = no open burst)
_scroll_burst: ScrollBurst | None = None
_scroll_diag_emitted = False

# Alias for tests that stub Listener construction
mouse_Listener = mouse.Listener if PYNPUT_AVAILABLE else None


def apply_config(cfg: AppConfig) -> None:
    """Apply loaded AppConfig to module globals (call once at startup / in tests)."""
    global AW_BASE_URL, WINDOW_CHECK_SEC, FLUSH_INTERVAL_SEC, TYPING_PAUSE_SEC
    global SECURE_FIELD_CACHE_SEC, AX_QUEUE_MAXSIZE, AX_MAX_DEPTH, SCREEN_COMPARE_MAX_CHARS
    global SECURE_APPS, LOG_DIR, _DIAG_MIN_INTERVAL, _ax_jobs, _APP_CONFIG
    global ACTIVITYWATCH_ENRICHER, BROWSER_URL_CAPTURE, CAPTURE_TRIGGERS_ENABLED
    global SCROLL_COALESCE_ENABLED, SCROLL_COALESCE_MS

    AW_BASE_URL = cfg.activitywatch_base_url
    WINDOW_CHECK_SEC = cfg.window_check_sec
    FLUSH_INTERVAL_SEC = cfg.flush_interval_sec
    TYPING_PAUSE_SEC = cfg.typing_pause_sec
    SECURE_FIELD_CACHE_SEC = cfg.secure_field_cache_sec
    AX_QUEUE_MAXSIZE = cfg.ax_queue_maxsize
    AX_MAX_DEPTH = cfg.ax_max_depth
    SCREEN_COMPARE_MAX_CHARS = cfg.screen_compare_max_chars
    SECURE_APPS = set(cfg.secure_apps)
    _DIAG_MIN_INTERVAL = cfg.diag_min_interval_sec
    ACTIVITYWATCH_ENRICHER = cfg.activitywatch_enricher
    BROWSER_URL_CAPTURE = cfg.browser_url_capture
    CAPTURE_TRIGGERS_ENABLED = cfg.capture_triggers_enabled
    SCROLL_COALESCE_ENABLED = cfg.scroll_coalesce_enabled
    SCROLL_COALESCE_MS = cfg.scroll_coalesce_ms
    LOG_DIR = ensure_log_dir(cfg.log_dir)
    _APP_CONFIG = cfg
    # Recreate AX queue if capacity changed and queue is idle (startup / tests).
    if _ax_jobs.maxsize != AX_QUEUE_MAXSIZE and _ax_jobs.empty():
        _ax_jobs = queue.Queue(maxsize=AX_QUEUE_MAXSIZE)


def _recompute_paused_locked() -> None:
    global _is_paused, _last_key_activity_mono, _scroll_burst
    newly = _pause_secure_app or _pause_secure_field
    if newly and not _is_paused:
        _current_modifiers.clear()
        _current_keystrokes.clear()
        # Cancel pending typing-pause idle; do not flush secrets into events.
        _last_key_activity_mono = None
        # F6: discard open scroll burst on pause enter (no flush, no seal).
        _scroll_burst = scroll_discard(_scroll_burst)
    _is_paused = newly


def is_paused() -> bool:
    with _lock:
        return _is_paused


def _set_pause(*, app: bool | None = None, field: bool | None = None) -> None:
    global _pause_secure_app, _pause_secure_field
    with _lock:
        if app is not None:
            _pause_secure_app = app
        if field is not None:
            _pause_secure_field = field
        _recompute_paused_locked()


def _mark_secure_field_cache(focused: bool) -> None:
    global _secure_field_cache, _secure_field_cache_at
    _secure_field_cache = focused
    _secure_field_cache_at = time.monotonic()


def _is_secure_app_name(app: str, title: str = "") -> bool:
    app_l = (app or "").lower()
    title_l = (title or "").lower()
    return any(sec in app_l for sec in SECURE_APPS) or any(sec in title_l for sec in SECURE_APPS)


def _element_looks_secure(element) -> bool:
    try:
        err, role = AXUIElementCopyAttributeValue(element, "AXRole", None)
        role_str = str(role) if err == 0 and role is not None else ""
        err, subrole = AXUIElementCopyAttributeValue(element, "AXSubrole", None)
        subrole_str = str(subrole) if err == 0 and subrole is not None else ""
        return (
            "SecureTextField" in role_str
            or "SecureTextField" in subrole_str
            or "Password" in role_str
        )
    except Exception:
        return False


def get_frontmost_app_name() -> str:
    if not AX_AVAILABLE:
        return ""
    try:
        front_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if not front_app:
            return ""
        name = front_app.localizedName()
        return str(name) if name else ""
    except Exception:
        return ""


def _ax_window_title(app_elem) -> str:
    """Window-level AXTitle only (focused, else main, else first window)."""
    window = None
    for attr in ("AXFocusedWindow", "AXMainWindow"):
        try:
            err, candidate = AXUIElementCopyAttributeValue(app_elem, attr, None)
            if err == 0 and candidate:
                window = candidate
                break
        except Exception:
            continue
    if window is None:
        try:
            err, windows = AXUIElementCopyAttributeValue(app_elem, "AXWindows", None)
            if err == 0 and windows:
                window = windows[0]
        except Exception:
            window = None
    if not window:
        return ""
    try:
        err, title = AXUIElementCopyAttributeValue(window, "AXTitle", None)
        if err == 0 and title:
            return str(title)
    except Exception:
        pass
    return ""


def get_native_window() -> tuple[str, str]:
    """Frontmost app (NSWorkspace) + window title (AX). Returns (app, title)."""
    if not AX_AVAILABLE:
        return "", ""
    try:
        front_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if not front_app:
            return "", ""
        name = front_app.localizedName()
        app = str(name) if name else ""
        app_elem = AXUIElementCreateApplication(front_app.processIdentifier())
        title = _ax_window_title(app_elem)
        return app, title
    except Exception:
        return "", ""


def refresh_secure_field_focus(force: bool = False) -> bool:
    global _secure_field_cache, _secure_field_cache_at
    if not AX_AVAILABLE:
        return False
    now = time.monotonic()
    if not force and (now - _secure_field_cache_at) < SECURE_FIELD_CACHE_SEC:
        return _secure_field_cache
    focused = False
    try:
        system_wide = AXUIElementCreateSystemWide()
        err, element = AXUIElementCopyAttributeValue(system_wide, "AXFocusedUIElement", None)
        if err == 0 and element:
            focused = _element_looks_secure(element)
    except Exception:
        focused = False
    _secure_field_cache = focused
    _secure_field_cache_at = now
    return focused


def sync_secure_field_from_focus(*, force: bool = False) -> bool:
    """Stale cached False must never clear an active field pause (P0)."""
    focused = refresh_secure_field_focus(force=force)
    if focused:
        _set_pause(field=True)
        return True
    if force:
        _set_pause(field=False)
        return False
    return is_paused()


def _find_window_bucket() -> str | None:
    try:
        resp = requests.get(f"{AW_BASE_URL}/api/0/buckets/", timeout=2)
        resp.raise_for_status()
        for b_id in resp.json():
            if "window" in b_id.lower():
                return b_id
    except Exception as e:
        _diag_rate_limited(f"ActivityWatch buckets error: {e}")
    return None


def get_activitywatch_window() -> tuple[str, str]:
    """ActivityWatch enricher source. Returns (app, title); empty on failure."""
    global _window_bucket
    try:
        if not _window_bucket:
            _window_bucket = _find_window_bucket()
        if not _window_bucket:
            return "", ""
        resp = requests.get(
            f"{AW_BASE_URL}/api/0/buckets/{_window_bucket}/events",
            params={"limit": 1},
            timeout=2,
        )
        resp.raise_for_status()
        events = resp.json()
        if not events:
            return "", ""
        d = events[0].get("data", {}) or {}
        app = d.get("app") or ""
        title = d.get("title") or ""
        return str(app), str(title)
    except Exception as e:
        _window_bucket = None
        _diag_rate_limited(f"ActivityWatch events error (bucket cleared): {e}")
        return "", ""


def resolve_window() -> tuple[str, str]:
    """Native-first (app, title); optional AW fills empty fields only."""
    native = get_native_window()
    if not ACTIVITYWATCH_ENRICHER:
        return merge_native_and_aw(native, None, enricher_enabled=False)
    try:
        aw = get_activitywatch_window()
    except Exception as e:
        _diag_rate_limited(f"ActivityWatch enricher error: {e}")
        return merge_native_and_aw(native, None, enricher_enabled=False)
    return merge_native_and_aw(native, aw, enricher_enabled=True)


def get_active_window() -> tuple[str, str]:
    """Production window resolve. Returns (app, title). Prefer resolve_window()."""
    return resolve_window()


def apply_resolved_window(app: str, title: str) -> bool:
    """Apply one resolve pair to heading + secure-app pause. False if both empty."""
    global _pause_secure_app, _pause_secure_field

    body = build_heading_body(app, title)
    if body is None:
        return False

    is_secure_app = _is_secure_app_name(app, title)
    is_secure_field = refresh_secure_field_focus(force=True)

    new_heading = body
    if is_secure_app:
        new_heading = f"🔒 [SECURE APP PAUSED] {body}"
    elif is_secure_field:
        new_heading = f"🔒 [SECURE FIELD PAUSED] {body}"

    with _lock:
        _pause_secure_app = is_secure_app
        _pause_secure_field = is_secure_field
        _recompute_paused_locked()
        _apply_heading_change_locked(new_heading)

    if not is_paused():
        _enqueue_ax(("scan",))
    return True


def format_section_timestamp_line(timestamp: str, trigger: str | None = None) -> str:
    """Format the italic Markdown timestamp line.

    Legacy / no trigger: ``*{HH:MM:SS}*``
    With trigger: ``*{HH:MM:SS} · trigger:{name}*`` (middle dot U+00B7).
    Raises ValueError if ``trigger`` is set and not in CAPTURE_TRIGGERS.
    """
    if trigger is None:
        return f"*{timestamp}*"
    if trigger not in CAPTURE_TRIGGERS:
        raise ValueError(f"unknown capture trigger: {trigger!r}")
    return f"*{timestamp} · trigger:{trigger}*"


def _seal_open_events_locked(trigger: str) -> None:
    """Seal `_current_events` into `_sections`. Caller holds `_lock`.

    When CAPTURE_TRIGGERS_ENABLED, stores ``trigger`` (must be in CAPTURE_TRIGGERS).
    Do not pass ``typing_pause`` from F3 key-flush paths (reserved; unused in F3 v1).
    """
    if not _current_events:
        return
    section: dict = {
        "heading": _current_heading or FALLBACK_HEADING,
        "events": list(_current_events),
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }
    if CAPTURE_TRIGGERS_ENABLED:
        if trigger not in CAPTURE_TRIGGERS:
            raise ValueError(f"unknown capture trigger: {trigger!r}")
        if trigger == "typing_pause":
            raise ValueError("typing_pause is reserved; do not emit as section trigger")
        section["trigger"] = trigger
    _sections.append(section)
    _current_events.clear()


def _flush_keys(*, cause: str = "unknown") -> None:
    """Join key buffer into `_current_events` and clear buffer. Caller holds `_lock`."""
    global _last_key_flush_cause, _last_key_activity_mono
    if not _current_keystrokes:
        return
    _current_events.append("".join(_current_keystrokes))
    _current_keystrokes.clear()
    _last_key_flush_cause = cause
    _last_key_activity_mono = None
    hook = _key_flush_hook
    if hook is not None:
        hook(cause)


def note_key_activity(now: float | None = None) -> None:
    """Record buffer-mutating key activity (monotonic). Used by on_press and tests."""
    with _lock:
        _note_key_activity_locked(now)


def _note_key_activity_locked(now: float | None = None) -> None:
    global _last_key_activity_mono
    _last_key_activity_mono = time.monotonic() if now is None else now


def check_typing_pause_idle(now: float | None = None) -> bool:
    """If idle ≥ typing_pause_sec and buffer non-empty, flush keys → events only.

    Does not seal `_sections` and does not write Markdown.
    `now` is injectable monotonic time for tests.
    """
    with _lock:
        return _check_typing_pause_idle_locked(now)


def _check_typing_pause_idle_locked(now: float | None = None) -> bool:
    if _is_paused:
        return False
    if not _current_keystrokes:
        return False
    if _last_key_activity_mono is None:
        return False
    t = time.monotonic() if now is None else now
    if (t - _last_key_activity_mono) < TYPING_PAUSE_SEC:
        return False
    _flush_keys(cause="typing_pause")
    return True


def _apply_heading_change_locked(new_heading: str) -> None:
    """Flush keys, seal events, set heading. Caller holds `_lock`."""
    global _current_heading, _last_screen_text, _last_key_activity_mono
    if new_heading == _current_heading:
        return
    # F6: flush open scroll into prior section before heading switch.
    _flush_scroll_burst_locked()
    _flush_keys(cause="app_switch")
    _seal_open_events_locked("app_switch")
    _current_heading = new_heading
    _last_screen_text = ""
    _last_key_activity_mono = None


def apply_heading_change(new_heading: str) -> None:
    """Flush keys, seal open events under the old heading, set new heading.

    Resets typing-pause idle state for the new context.
    """
    with _lock:
        _apply_heading_change_locked(new_heading)


def add_event(ev: str, seal_trigger: str | None = None) -> None:
    """Append an event. Optional seal_trigger seals when F5 flag is ON."""
    with _lock:
        if _is_paused:
            return
        cause = seal_trigger or "add_event"
        _flush_keys(cause=cause)
        _current_events.append(ev)
        if seal_trigger and CAPTURE_TRIGGERS_ENABLED:
            _seal_open_events_locked(seal_trigger)


def record_click_event(desc: str) -> None:
    """Append a click line; seal with ``click`` when capture_triggers_enabled."""
    add_event(f"🖱️ **Клік:** {desc}", seal_trigger="click")


def record_clipboard_event(event: str) -> None:
    """Append a clipboard event; seal with ``clipboard`` when capture_triggers_enabled."""
    add_event(event, seal_trigger="clipboard")


def record_url_event(event: str) -> None:
    """Append a URL event; seal with ``url_change`` when capture_triggers_enabled (F4+F5)."""
    add_event(event, seal_trigger="url_change")


def record_scroll_event(line: str) -> None:
    """Append a coalesced scroll line; seal with ``scroll_coalesce`` when F5 is ON."""
    add_event(line, seal_trigger="scroll_coalesce")


def on_scroll_tick(
    *,
    dx: float,
    dy: float,
    now: float | None = None,
    app: str = "",
    heading: str = "",
) -> None:
    """Accumulate one scroll tick when F6 is enabled and not paused."""
    global _scroll_burst
    if not SCROLL_COALESCE_ENABLED:
        return
    with _lock:
        if _is_paused:
            return
        t = time.monotonic() if now is None else now
        app_name = app
        head = heading or _current_heading
        if not app_name and head:
            app_name = head.split(" — ", 1)[0].strip()
        _scroll_burst = scroll_accumulate(
            _scroll_burst,
            dx=dx,
            dy=dy,
            now=t,
            app=app_name,
            heading=head,
        )


def on_scroll(x, y, dx, dy) -> None:
    """pynput scroll callback — no AX scan, no screenshot."""
    if not SCROLL_COALESCE_ENABLED or is_paused():
        return
    heading = ""
    app = ""
    with _lock:
        heading = _current_heading
        if heading:
            app = heading.split(" — ", 1)[0].strip()
    on_scroll_tick(dx=dx, dy=dy, app=app, heading=heading)


def on_mouse_move_stub(x, y) -> None:
    """Test hook: moves are intentionally ignored (F6 must not log trails)."""
    return None


def _flush_scroll_burst_locked() -> bool:
    """Flush open scroll burst → event + seal. Caller holds `_lock`.

    Defense in depth: if paused, discard and return False (T-F6-08).
    """
    global _scroll_burst
    if _scroll_burst is None or not _scroll_burst.is_open:
        return False
    if _is_paused:
        _scroll_burst = scroll_discard(_scroll_burst)
        return False
    line = format_burst_line(_scroll_burst)
    _scroll_burst = None
    # Inline add_event path while holding lock (avoid re-entrant lock).
    # Always seal: F5 ON stores trigger scroll_coalesce; F5 OFF seals with no trigger field.
    _flush_keys(cause="scroll_coalesce")
    _current_events.append(line)
    _seal_open_events_locked("scroll_coalesce")
    return True


def flush_scroll_burst(*, now: float | None = None) -> bool:
    """Flush open scroll burst if any (pause-safe). Used by tests and shutdown."""
    with _lock:
        return _flush_scroll_burst_locked()


def check_scroll_coalesce_idle(now: float | None = None) -> bool:
    """If quiet ≥ scroll_coalesce_ms, flush the open burst and seal."""
    if not SCROLL_COALESCE_ENABLED:
        return False
    with _lock:
        if _is_paused:
            return False
        t = time.monotonic() if now is None else now
        if not scroll_should_flush(
            _scroll_burst, now=t, coalesce_ms=SCROLL_COALESCE_MS
        ):
            return False
        return _flush_scroll_burst_locked()


def flush_scroll_burst_on_shutdown() -> bool:
    """Orderly shutdown / durable path: flush if not paused; discard if paused."""
    global _scroll_burst
    if not SCROLL_COALESCE_ENABLED:
        return False
    with _lock:
        if _is_paused:
            _scroll_burst = scroll_discard(_scroll_burst)
            return False
        return _flush_scroll_burst_locked()


def mouse_listener_kwargs_for_config() -> dict:
    """Listener kwargs for current config. Never includes on_move."""
    on_scroll_cb = on_scroll if SCROLL_COALESCE_ENABLED else None
    return mouse_listener_kwargs(on_click=on_click, on_scroll=on_scroll_cb)


def create_mouse_listener_safe(*, on_click):
    """Create mouse.Listener; soft-fail scroll attach (FR-F6-011).

    Returns ``(listener, diagnostic_or_None)``. Emits at most one scroll
    diagnostic per process (``_scroll_diag_emitted``).
    """
    global _scroll_diag_emitted
    if not PYNPUT_AVAILABLE or mouse_Listener is None:
        return None, "pynput unavailable"
    kwargs = mouse_listener_kwargs(
        on_click=on_click,
        on_scroll=on_scroll if SCROLL_COALESCE_ENABLED else None,
    )
    try:
        return mouse_Listener(**kwargs), None
    except Exception as e:
        if SCROLL_COALESCE_ENABLED and not _scroll_diag_emitted:
            _scroll_diag_emitted = True
            note = f"scroll coalesce unavailable: {e}"
            try:
                _diag(note)
            except Exception:
                pass
            # Fall back to click-only
            try:
                return mouse_Listener(on_click=on_click), note
            except Exception:
                return None, note
        # Already diagnosed, or feature off
        try:
            return mouse_Listener(on_click=on_click), None
        except Exception:
            return None, None


def scroll_coalesce_idle_loop() -> None:
    """Poll quiet expiry for open scroll bursts."""
    while True:
        interval = max(0.02, min(0.05, SCROLL_COALESCE_MS / 1000.0 / 8.0))
        time.sleep(interval)
        if SCROLL_COALESCE_ENABLED:
            check_scroll_coalesce_idle()


def set_url_provider(provider) -> None:
    """Install a BrowserUrlProvider (tests). Pass None to clear."""
    set_browser_url_provider(provider)


def maybe_capture_browser_url(app: str, *, url_provider=None) -> None:
    """When F4 flag ON and app is a browser, observe/emit URL (pause-safe).

    Flag OFF: return without calling ``url_provider`` (no Automation prompts).
    """
    if not BROWSER_URL_CAPTURE:
        return
    if not is_browser_app(app):
        return
    try:
        if url_provider is not None:
            if callable(url_provider) and not hasattr(url_provider, "get_url"):
                raw = url_provider(app)
            else:
                raw = url_provider.get_url(app)
        else:
            raw = get_frontmost_browser_url(app)
    except Exception as e:
        _diag_rate_limited(f"browser url error: {e}")
        return
    record_browser_url_observation(raw)


def process_window_check_cycle(app: str, title: str, *, url_provider=None) -> bool:
    """One window-check iteration: heading/section first, then optional URL (FR-F4-009)."""
    ok = apply_resolved_window(app, title)
    maybe_capture_browser_url(app, url_provider=url_provider)
    return ok

def record_browser_url_observation(url: str) -> None:
    """Test/helper: emit a URL observation through the same path as live capture."""
    global _last_emitted_url
    if not BROWSER_URL_CAPTURE:
        return
    new_last, event = apply_url_observation(
        enabled=True,
        paused=is_paused(),
        candidate=url,
        last_emitted=_last_emitted_url or None,
    )
    _last_emitted_url = new_last
    if event:
        record_url_event(event)


def apply_window_and_url_cycle(app: str, title: str, *, url: str | None = None) -> bool:
    """Apply heading change then optional URL (same cycle order as window loop)."""
    ok = apply_resolved_window(app, title)
    if url is not None:
        record_browser_url_observation(url)
    else:
        maybe_capture_browser_url(app)
    return ok


def run_window_check_iteration(app: str, title: str, *, url_provider=None) -> bool:
    """Alias for process_window_check_cycle (tests)."""
    # url_provider may be a callable get_url(app) — wrap as BrowserUrlProvider
    provider = url_provider
    if callable(url_provider) and not hasattr(url_provider, "get_url"):
        class _FnProvider:
            def get_url(self, app_name: str):
                return url_provider(app_name)
        provider = _FnProvider()
    return process_window_check_cycle(app, title, url_provider=provider)


def on_press(key) -> None:
    force = (time.monotonic() - _secure_field_cache_at) >= SECURE_FIELD_CACHE_SEC
    sync_secure_field_from_focus(force=force)

    with _lock:
        if _is_paused:
            return
        mutated = False
        if isinstance(key, keyboard.Key):
            mod = _MODIFIER_KEYS.get(key)
            if mod:
                _current_modifiers.add(mod)
            elif key == keyboard.Key.enter:
                _current_keystrokes.append("\n[ENTER]\n")
                mutated = True
            elif key == keyboard.Key.tab:
                _current_keystrokes.append("[TAB]")
                mutated = True
            elif key == keyboard.Key.space:
                _current_keystrokes.append(" ")
                mutated = True
            elif key == keyboard.Key.backspace:
                if _current_keystrokes:
                    _current_keystrokes.pop()
                    mutated = True
            elif key == keyboard.Key.esc:
                _current_keystrokes.append("[ESC]")
                mutated = True
        elif hasattr(key, "char"):
            char = key.char
            if char is None and hasattr(key, "vk") and key.vk is not None:
                char = f"VK_{key.vk}"
            if char:
                if _current_modifiers.difference({"SHIFT"}):
                    mods = "+".join(sorted(_current_modifiers))
                    _current_keystrokes.append(f"[{mods}+{char.upper()}]")
                else:
                    _current_keystrokes.append(char)
                mutated = True
        if mutated:
            _note_key_activity_locked()


def on_release(key) -> None:
    with _lock:
        if isinstance(key, keyboard.Key):
            mod = _MODIFIER_KEYS.get(key)
            if mod:
                _current_modifiers.discard(mod)


def extract_text(element, depth=0) -> str:
    if depth > AX_MAX_DEPTH:
        return ""
    try:
        if _element_looks_secure(element):
            return " [SECURE_FIELD_HIDDEN] "

        err, role = AXUIElementCopyAttributeValue(element, "AXRole", None)
        if err != 0:
            return ""

        extracted = []
        if role in ("AXStaticText", "AXTextArea", "AXTextField", "AXHeading", "AXLink", "AXButton"):
            err, val = AXUIElementCopyAttributeValue(element, "AXValue", None)
            if err == 0 and val and isinstance(val, str):
                extracted.append(val)
            else:
                err, title = AXUIElementCopyAttributeValue(element, "AXTitle", None)
                if err == 0 and title and isinstance(title, str):
                    extracted.append(title)

        err, children = AXUIElementCopyAttributeValue(element, "AXChildren", None)
        if err == 0 and children:
            for child in children:
                txt = extract_text(child, depth + 1)
                if txt:
                    extracted.append(txt)
        return " ".join(extracted)
    except Exception:
        return ""


def scan_screen() -> None:
    if not AX_AVAILABLE or is_paused():
        return
    try:
        front_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if not front_app:
            return
        app_elem = AXUIElementCreateApplication(front_app.processIdentifier())
        err, window = AXUIElementCopyAttributeValue(app_elem, "AXFocusedWindow", None)
        if err != 0 or not window:
            return

        text = extract_text(window)
        text = " ".join(text.split())
        if not text:
            return

        global _last_screen_text
        with _lock:
            if _is_paused:
                return
            prev = _last_screen_text
        if prev[:SCREEN_COMPARE_MAX_CHARS] != text[:SCREEN_COMPARE_MAX_CHARS]:
            with _lock:
                if _is_paused:
                    return
                _last_screen_text = text
            add_event(f"💻 **Екран:**\n```text\n{text[:2000]}\n```")
    except Exception as e:
        _diag_rate_limited(f"scan_screen error: {e}")


def _process_click(x, y) -> None:
    if not AX_AVAILABLE or is_paused():
        return
    try:
        system_wide = AXUIElementCreateSystemWide()
        err, element = AXUIElementCopyElementAtPosition(system_wide, float(x), float(y), None)
        if err != 0 or not element:
            return

        if _element_looks_secure(element):
            _mark_secure_field_cache(True)
            _set_pause(field=True)
            return

        _mark_secure_field_cache(False)
        _set_pause(field=False)
        if is_paused():
            return

        err, role = AXUIElementCopyAttributeValue(element, "AXRole", None)
        role = role if err == 0 and role else "Unknown"
        err, title = AXUIElementCopyAttributeValue(element, "AXTitle", None)
        name = title if err == 0 and title and isinstance(title, str) else ""
        if not name:
            err, val = AXUIElementCopyAttributeValue(element, "AXValue", None)
            name = val if err == 0 and val and isinstance(val, str) else ""

        role_clean = str(role).replace("AX", "")
        desc = f"{role_clean} '{name}'" if name else role_clean
        record_click_event(desc)
        if not is_paused():
            _enqueue_ax(("scan",))
    except Exception as e:
        _diag_rate_limited(f"process_click error: {e}")


def _enqueue_ax(job: tuple) -> None:
    global _scan_pending
    if job[0] == "scan":
        with _ax_meta_lock:
            if _scan_pending:
                return
            try:
                _ax_jobs.put_nowait(job)
                _scan_pending = True
            except queue.Full:
                pass
        return
    try:
        _ax_jobs.put_nowait(job)
    except queue.Full:
        pass


def _ax_worker_loop() -> None:
    global _scan_pending
    while True:
        job = _ax_jobs.get()
        try:
            if job[0] == "scan":
                with _ax_meta_lock:
                    _scan_pending = False
                scan_screen()
            elif job[0] == "click":
                _process_click(job[1], job[2])
        except Exception as e:
            _diag_rate_limited(f"ax_worker error: {e}")
        finally:
            _ax_jobs.task_done()


def on_click(x, y, button, pressed) -> None:
    if pressed and not is_paused():
        _enqueue_ax(("click", x, y))


def apply_clipboard_change(
    count: int,
    text: str,
    paused: bool,
    last_count: int,
    last_text: str,
) -> tuple[int, str, str | None]:
    """Testable clipboard update: advance markers while paused; never log paused secrets later."""
    if count == last_count:
        return last_count, last_text, None
    new_text = text if text else last_text
    if paused:
        return count, new_text, None
    if text and text != last_text:
        return count, text, f"> [CLIPBOARD]:\n```text\n{text[:2000]}\n```"
    return count, new_text, None


def clipboard_checker_loop() -> None:
    if not AX_AVAILABLE:
        return
    global _last_clipboard_count, _last_clipboard_text

    try:
        pb = NSPasteboard.generalPasteboard()
        _last_clipboard_count = pb.changeCount()
    except Exception:
        return

    while True:
        time.sleep(1.0)
        try:
            count = pb.changeCount()
            text = pb.stringForType_(NSStringPboardType) or ""
            new_count, new_text, event = apply_clipboard_change(
                count, text, is_paused(), _last_clipboard_count, _last_clipboard_text
            )
            _last_clipboard_count = new_count
            _last_clipboard_text = new_text
            if event:
                record_clipboard_event(event)
        except Exception as e:
            _diag_rate_limited(f"clipboard error: {e}")


def window_checker_loop() -> None:
    while True:
        time.sleep(WINDOW_CHECK_SEC)
        app, title = resolve_window()
        run_window_check_iteration(app=app, title=title)


def typing_pause_idle_loop() -> None:
    """Poll typing-pause idle and flush key buffer into events (no section seal)."""
    while True:
        time.sleep(min(0.05, max(0.01, TYPING_PAUSE_SEC / 10.0)))
        check_typing_pause_idle()


def _diag_rate_limited(msg: str) -> None:
    key = msg.split(":", 1)[0]
    now = time.monotonic()
    if now - _diag_last.get(key, 0.0) < _DIAG_MIN_INTERVAL:
        return
    _diag_last[key] = now
    _diag(msg)


def _diag(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        with open(LOG_DIR / "diagnostics.log", "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    print(line.strip(), file=sys.stderr, flush=True)


def _get_filepath() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(LOG_DIR, 0o700)
    except OSError:
        pass
    return LOG_DIR / f"daily_log_{datetime.now().strftime('%Y-%m-%d')}.md"


def _log_header_lines(*, include_started: bool = False) -> list[str]:
    lines = [
        f"# Work Log — {datetime.now().strftime('%Y-%m-%d')}\n\n",
        f"> Auto-generated by Interleaved Logger v{__version__} "
        f"(AX + Clipboard + Security + Hotkeys)\n\n---\n\n",
    ]
    if include_started:
        lines.append(f"*Logger started at {datetime.now().strftime('%H:%M:%S')}*\n\n---\n\n")
    return lines


def _write_to_file(filepath: Path, lines: list[str], append: bool = True) -> bool:
    try:
        with open(filepath, "a" if append else "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except OSError as e:
        print(f"[ActivityLogger] WRITE ERROR: {filepath}: {e}", file=sys.stderr, flush=True)
        return False


def _restore_sections(to_write: list) -> None:
    global _sections
    if not to_write:
        return
    with _lock:
        _sections = to_write + _sections


def flush_to_file() -> None:
    global _sections, _scroll_burst
    with _lock:
        # F6: do not drop an open scroll burst on durable flush (FR-F6-012).
        if SCROLL_COALESCE_ENABLED:
            if _is_paused:
                _scroll_burst = scroll_discard(_scroll_burst)
            else:
                _flush_scroll_burst_locked()
        _flush_keys(cause="file_flush")
        _seal_open_events_locked("file_flush")
        to_write = list(_sections)
        _sections.clear()

    filepath = _get_filepath()
    is_new = not filepath.exists() or filepath.stat().st_size == 0
    if is_new and not _write_to_file(filepath, _log_header_lines(), append=False):
        _restore_sections(to_write)
        return

    if to_write:
        lines = []
        for section in to_write:
            # Emit trigger only when present on the sealed section (flag ON at seal time).
            trigger = section.get("trigger")
            ts_line = format_section_timestamp_line(section["timestamp"], trigger)
            lines.append(f"## {section['heading']}\n{ts_line}\n\n")
            for ev in section["events"]:
                lines.append(f"{ev.strip()}\n\n")
            lines.append("---\n\n")
        if not _write_to_file(filepath, lines):
            _restore_sections(to_write)


def file_writer_loop() -> None:
    while True:
        time.sleep(FLUSH_INTERVAL_SEC)
        flush_to_file()


def acquire_instance_lock() -> bool:
    global _instance_lock_file
    lock_path = LOG_DIR / ".activitylogger.lock"
    try:
        _instance_lock_file = open(lock_path, "a+", encoding="utf-8")
        fcntl.flock(_instance_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _instance_lock_file.seek(0)
        _instance_lock_file.truncate()
        _instance_lock_file.write(str(os.getpid()))
        _instance_lock_file.flush()
        return True
    except BlockingIOError:
        return False
    except OSError as e:
        _diag(f"instance lock error: {e}")
        return False


def main() -> None:
    try:
        try:
            cfg = load_config(warn=lambda msg: _diag(msg))
        except ConfigError as e:
            # Best-effort before LOG_DIR may be final
            print(f"FATAL config: {e}", file=sys.stderr)
            try:
                _diag(f"FATAL config: {e}")
            except Exception:
                pass
            sys.exit(1)

        apply_config(cfg)
        if cfg.config_path is None:
            _diag("config: using defaults")
        _diag(startup_diag_line(cfg))
        _diag(f"ActivityLogger v{__version__} starting — LOG_DIR={LOG_DIR}")

        if not acquire_instance_lock():
            _diag("FATAL: another ActivityLogger instance holds the lock — exiting")
            sys.exit(1)
        if not PYNPUT_AVAILABLE:
            _diag("FATAL: pynput is not installed")
            sys.exit(1)

        filepath = _get_filepath()
        if not filepath.exists() or filepath.stat().st_size == 0:
            if _write_to_file(filepath, _log_header_lines(include_started=True), append=False):
                _diag(f"Log file created: {filepath}")
            else:
                _diag(f"Failed to create log file at {filepath}")
        else:
            _diag(f"Log file exists: {filepath}")

        app, title = resolve_window()
        body = build_heading_body(app, title)
        if body:
            apply_resolved_window(app, title)
            if app and title:
                _diag(f"Native window OK — current window: {body}")
            elif app:
                _diag(f"Native app OK; window title missing — {body}")
            else:
                _diag(f"Window title from enricher — {body}")
            if ACTIVITYWATCH_ENRICHER:
                _diag(
                    "ActivityWatch enricher enabled "
                    f"(base={AW_BASE_URL})"
                )
            else:
                _diag("ActivityWatch enricher disabled")
        else:
            _diag("No frontmost app detected — events will use fallback heading")
            if ACTIVITYWATCH_ENRICHER:
                _diag("ActivityWatch enricher enabled but no app/title yet")
            else:
                _diag("ActivityWatch enricher disabled; native titles empty")

        threading.Thread(target=_ax_worker_loop, daemon=True, name="ax-worker").start()
        threading.Thread(target=window_checker_loop, daemon=True).start()
        threading.Thread(target=clipboard_checker_loop, daemon=True).start()
        threading.Thread(target=file_writer_loop, daemon=True).start()
        threading.Thread(target=typing_pause_idle_loop, daemon=True, name="typing-pause").start()
        if SCROLL_COALESCE_ENABLED:
            threading.Thread(
                target=scroll_coalesce_idle_loop, daemon=True, name="scroll-coalesce"
            ).start()

        m_listener, scroll_note = create_mouse_listener_safe(on_click=on_click)
        if m_listener is None:
            _diag("FATAL: could not start mouse listener")
            sys.exit(1)
        k_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        m_listener.start()
        k_listener.start()
        _diag("Keyboard and mouse listeners started")

        try:
            k_listener.join()
        except KeyboardInterrupt:
            m_listener.stop()
            k_listener.stop()
            flush_scroll_burst_on_shutdown()
            flush_to_file()
    except Exception as e:
        _diag(f"FATAL: {e}\n{traceback.format_exc()}")


if __name__ == "__main__":
    main()
