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

__version__ = "4.1.0"

AW_BASE_URL = "http://localhost:5600"
WINDOW_CHECK_SEC = 5
FLUSH_INTERVAL_SEC = 30
SECURE_FIELD_CACHE_SEC = 0.35
AX_QUEUE_MAXSIZE = 16
SCREEN_COMPARE_MAX_CHARS = 4000

SECURE_APPS = {"1password", "bitwarden", "keychain", "keepass", "lastpass", "passwords"}

AW_HINT = "(ActivityWatch not running; start ActivityWatch for window titles)"
FALLBACK_HEADING = f"Unknown — {AW_HINT}"

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
    base = os.environ.get("HOME") or Path.home()
    if not Path(base).exists():
        try:
            import pwd

            base = pwd.getpwuid(os.getuid()).pw_dir
        except Exception:
            base = "/tmp"
    log_dir = Path(base) / "scripts" / "activitylogger" / "logs"
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

_pause_secure_app = False
_pause_secure_field = False
_is_paused = False
_current_modifiers: set[str] = set()

_secure_field_cache = False
_secure_field_cache_at = 0.0

_window_bucket: str | None = None
_ax_jobs: queue.Queue = queue.Queue(maxsize=AX_QUEUE_MAXSIZE)
_scan_pending = False
_ax_meta_lock = threading.Lock()
_instance_lock_file = None

_diag_last: dict[str, float] = {}
_DIAG_MIN_INTERVAL = 30.0


def _recompute_paused_locked() -> None:
    global _is_paused
    newly = _pause_secure_app or _pause_secure_field
    if newly and not _is_paused:
        _current_modifiers.clear()
        _current_keystrokes.clear()
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


def get_active_window() -> tuple[str, str]:
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
        d = events[0].get("data", {})
        return d.get("title", "Unknown Window"), d.get("app", "Unknown App")
    except Exception as e:
        _window_bucket = None
        _diag_rate_limited(f"ActivityWatch events error (bucket cleared): {e}")
        return "", ""


def _flush_keys() -> None:
    if _current_keystrokes:
        _current_events.append("".join(_current_keystrokes))
        _current_keystrokes.clear()


def add_event(ev: str) -> None:
    with _lock:
        if _is_paused:
            return
        _flush_keys()
        _current_events.append(ev)


def on_press(key) -> None:
    force = (time.monotonic() - _secure_field_cache_at) >= SECURE_FIELD_CACHE_SEC
    sync_secure_field_from_focus(force=force)

    with _lock:
        if _is_paused:
            return
        if isinstance(key, keyboard.Key):
            mod = _MODIFIER_KEYS.get(key)
            if mod:
                _current_modifiers.add(mod)
            elif key == keyboard.Key.enter:
                _current_keystrokes.append("\n[ENTER]\n")
            elif key == keyboard.Key.tab:
                _current_keystrokes.append("[TAB]")
            elif key == keyboard.Key.space:
                _current_keystrokes.append(" ")
            elif key == keyboard.Key.backspace:
                if _current_keystrokes:
                    _current_keystrokes.pop()
            elif key == keyboard.Key.esc:
                _current_keystrokes.append("[ESC]")
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


def on_release(key) -> None:
    with _lock:
        if isinstance(key, keyboard.Key):
            mod = _MODIFIER_KEYS.get(key)
            if mod:
                _current_modifiers.discard(mod)


def extract_text(element, depth=0) -> str:
    if depth > 7:
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
        add_event(f"🖱️ **Клік:** {desc}")
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
                add_event(event)
        except Exception as e:
            _diag_rate_limited(f"clipboard error: {e}")


def window_checker_loop() -> None:
    global _current_heading, _last_screen_text, _pause_secure_app, _pause_secure_field
    while True:
        time.sleep(WINDOW_CHECK_SEC)
        title, app = get_active_window()
        if not app:
            app = get_frontmost_app_name()
        if not title and not app:
            continue
        if not title:
            title = AW_HINT

        is_secure_app = _is_secure_app_name(app, title)
        is_secure_field = refresh_secure_field_focus(force=True)

        new_heading = f"{app} — {title}"
        if is_secure_app:
            new_heading = f"🔒 [SECURE APP PAUSED] {app} — {title}"
        elif is_secure_field:
            new_heading = f"🔒 [SECURE FIELD PAUSED] {app} — {title}"

        with _lock:
            _pause_secure_app = is_secure_app
            _pause_secure_field = is_secure_field
            _recompute_paused_locked()

            if new_heading != _current_heading:
                _flush_keys()
                if _current_events:
                    _sections.append(
                        {
                            "heading": _current_heading or FALLBACK_HEADING,
                            "events": list(_current_events),
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                        }
                    )
                    _current_events.clear()
                _current_heading = new_heading
                _last_screen_text = ""

        if not is_paused():
            _enqueue_ax(("scan",))


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
    global _sections
    with _lock:
        _flush_keys()
        if _current_events:
            _sections.append(
                {
                    "heading": _current_heading or FALLBACK_HEADING,
                    "events": list(_current_events),
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                }
            )
            _current_events.clear()
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
            lines.append(f"## {section['heading']}\n*{section['timestamp']}*\n\n")
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
    _diag(f"ActivityLogger v{__version__} starting — LOG_DIR={LOG_DIR}")
    try:
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

        title, app = get_active_window()
        if not app:
            app = get_frontmost_app_name()
        if title or app:
            display_title = title or AW_HINT
            display_app = app or "Unknown"
            with _lock:
                global _current_heading
                _current_heading = f"{display_app} — {display_title}"
            if title:
                _diag(f"ActivityWatch OK — current window: {display_app} — {display_title}")
            else:
                _diag(f"ActivityWatch unavailable — using frontmost app: {display_app}")
            if _is_secure_app_name(display_app, display_title):
                _set_pause(app=True)
        else:
            _diag("No frontmost app detected — events will use fallback heading")

        threading.Thread(target=_ax_worker_loop, daemon=True, name="ax-worker").start()
        threading.Thread(target=window_checker_loop, daemon=True).start()
        threading.Thread(target=clipboard_checker_loop, daemon=True).start()
        threading.Thread(target=file_writer_loop, daemon=True).start()

        m_listener = mouse.Listener(on_click=on_click)
        k_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        m_listener.start()
        k_listener.start()
        _diag("Keyboard and mouse listeners started")

        try:
            k_listener.join()
        except KeyboardInterrupt:
            m_listener.stop()
            k_listener.stop()
            flush_to_file()
    except Exception as e:
        _diag(f"FATAL: {e}\n{traceback.format_exc()}")


if __name__ == "__main__":
    main()
