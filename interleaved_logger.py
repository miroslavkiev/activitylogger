#!/usr/bin/env python3
"""
Interleaved Work Log — macOS (v4)
Логує клавіатуру (з хоткеями), кліки, екран, буфер обміну + ЗАХИСТ ПАРОЛІВ.
"""

from __future__ import annotations
import os
import socket
import sys
import threading
import time
import traceback
import difflib
from datetime import datetime
from pathlib import Path

import requests
from pynput import keyboard, mouse

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

AW_BASE_URL        = "http://localhost:5600"
WINDOW_CHECK_SEC   = 5     
FLUSH_INTERVAL_SEC = 30

# Resolve log dir: prefer HOME, fallback to getpwuid; ensure we can write
def _resolve_log_dir() -> Path:
    base = os.environ.get("HOME")
    if not base or not Path(base).exists():
        try:
            import pwd
            base = pwd.getpwuid(os.getuid()).pw_dir
        except Exception:
            base = os.path.expanduser("~")
    log_dir = Path(base or "/tmp") / "scripts" / "activitylogger" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir

LOG_DIR            = _resolve_log_dir()
HOSTNAME           = socket.gethostname()

# Fallback heading when ActivityWatch is not running (so we still write keyboard/mouse events)
FALLBACK_HEADING   = "Unknown — (ActivityWatch not running; start ActivityWatch for window titles)"

# Чорний список додатків, де логер ставить себе на паузу
SECURE_APPS = {"1password", "bitwarden", "keychain", "keepass", "lastpass", "passwords"}

_lock                 = threading.Lock()
_current_heading      = ""
_current_keystrokes   = []
_current_events       = []  
_sections             = []

_last_screen_text     = ""
_last_clipboard_count = 0
_last_clipboard_text  = ""

_is_paused            = False
_current_modifiers    = set()

_window_bucket: str | None = None

def _find_window_bucket() -> str | None:
    try:
        resp = requests.get(f"{AW_BASE_URL}/api/0/buckets/", timeout=2)
        resp.raise_for_status()
        for b_id in resp.json():
            if "window" in b_id.lower(): return b_id
    except Exception: pass
    return None

def get_active_window() -> tuple[str, str]:
    global _window_bucket
    try:
        if not _window_bucket: _window_bucket = _find_window_bucket()
        if not _window_bucket: return "", ""
        resp = requests.get(f"{AW_BASE_URL}/api/0/buckets/{_window_bucket}/events", params={"limit": 1}, timeout=2)
        events = resp.json()
        if not events: return "", ""
        d = events[0].get("data", {})
        return d.get("title", "Unknown Window"), d.get("app", "Unknown App")
    except Exception:
        return "", ""

def _flush_keys():
    if _current_keystrokes:
        _current_events.append("".join(_current_keystrokes))
        _current_keystrokes.clear()

def add_event(ev: str):
    with _lock:
        _flush_keys()
        _current_events.append(ev)

def on_press(key):
    global _is_paused
    if _is_paused: return
    
    with _lock:
        if isinstance(key, keyboard.Key):
            if key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r): _current_modifiers.add('CMD')
            elif key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r): _current_modifiers.add('CTRL')
            elif key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr): _current_modifiers.add('OPT')
            elif key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r): _current_modifiers.add('SHIFT')
            elif key == keyboard.Key.enter: _current_keystrokes.append("\n[ENTER]\n")
            elif key == keyboard.Key.tab: _current_keystrokes.append("[TAB]")
            elif key == keyboard.Key.space: _current_keystrokes.append(" ")
            elif key == keyboard.Key.backspace:
                if _current_keystrokes: _current_keystrokes.pop()
            elif key == keyboard.Key.esc: _current_keystrokes.append("[ESC]")
        elif hasattr(key, "char"):
            char = key.char
            if char is None and hasattr(key, "vk") and key.vk is not None:
                char = f"VK_{key.vk}"
            
            if char:
                # Якщо затиснуті CMD/CTRL/OPT
                if _current_modifiers.difference({'SHIFT'}):
                    mods = "+".join(sorted(_current_modifiers))
                    _current_keystrokes.append(f"[{mods}+{char.upper()}]")
                else:
                    _current_keystrokes.append(char)

def on_release(key):
    with _lock:
        if isinstance(key, keyboard.Key):
            if key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r): _current_modifiers.discard('CMD')
            elif key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r): _current_modifiers.discard('CTRL')
            elif key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr): _current_modifiers.discard('OPT')
            elif key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r): _current_modifiers.discard('SHIFT')

def extract_text(element, depth=0):
    if depth > 7: return ""
    try:
        err, role = AXUIElementCopyAttributeValue(element, 'AXRole', None)
        if err != 0: return ""
        err, subrole = AXUIElementCopyAttributeValue(element, 'AXSubrole', None)
        
        role_str = str(role)
        subrole_str = str(subrole) if err == 0 else ""
        
        # Захист паролів
        if "SecureTextField" in role_str or "SecureTextField" in subrole_str or "Password" in role_str:
            return " [SECURE_FIELD_HIDDEN] "
            
        extracted = []
        if role in ('AXStaticText', 'AXTextArea', 'AXTextField', 'AXHeading', 'AXLink', 'AXButton'):
            err, val = AXUIElementCopyAttributeValue(element, 'AXValue', None)
            if err == 0 and val and isinstance(val, str): extracted.append(val)
            else:
                err, title = AXUIElementCopyAttributeValue(element, 'AXTitle', None)
                if err == 0 and title and isinstance(title, str): extracted.append(title)
        
        err, children = AXUIElementCopyAttributeValue(element, 'AXChildren', None)
        if err == 0 and children:
            for child in children:
                txt = extract_text(child, depth + 1)
                if txt: extracted.append(txt)
        return " ".join(extracted)
    except Exception: return ""

def scan_screen():
    global _is_paused
    if not AX_AVAILABLE or _is_paused: return
    try:
        front_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if not front_app: return
        app_elem = AXUIElementCreateApplication(front_app.processIdentifier())
        err, window = AXUIElementCopyAttributeValue(app_elem, 'AXFocusedWindow', None)
        if err != 0 or not window: return
        
        text = extract_text(window)
        text = " ".join(text.split())
        if not text: return
        
        global _last_screen_text
        ratio = difflib.SequenceMatcher(None, _last_screen_text, text).ratio()
        if ratio < 0.9:
            _last_screen_text = text
            add_event(f"💻 **Екран:**\n```text\n{text[:2000]}\n```")
    except Exception: pass

def _process_click(x, y):
    global _is_paused
    if not AX_AVAILABLE or _is_paused: return
    try:
        system_wide = AXUIElementCreateSystemWide()
        err, element = AXUIElementCopyElementAtPosition(system_wide, float(x), float(y), None)
        if err != 0 or not element: return
        
        err, role = AXUIElementCopyAttributeValue(element, 'AXRole', None)
        role = role if err == 0 and role else "Unknown"
        err, title = AXUIElementCopyAttributeValue(element, 'AXTitle', None)
        name = title if err == 0 and title and isinstance(title, str) else ""
        if not name:
            err, val = AXUIElementCopyAttributeValue(element, 'AXValue', None)
            name = val if err == 0 and val and isinstance(val, str) else ""
            
        role_clean = str(role).replace('AX', '')
        desc = f"{role_clean} '{name}'" if name else role_clean
        add_event(f"🖱️ **Клік:** {desc}")
        
        time.sleep(0.5)
        scan_screen()
    except Exception: pass

def on_click(x, y, button, pressed):
    global _is_paused
    if pressed and not _is_paused:
        threading.Thread(target=_process_click, args=(x, y), daemon=True).start()

def clipboard_checker_loop():
    if not AX_AVAILABLE: return
    global _last_clipboard_count, _last_clipboard_text, _is_paused
    
    try:
        pb = NSPasteboard.generalPasteboard()
        _last_clipboard_count = pb.changeCount()
    except Exception:
        return

    while True:
        time.sleep(1.0)
        if _is_paused: continue
        
        try:
            count = pb.changeCount()
            if count != _last_clipboard_count:
                _last_clipboard_count = count
                text = pb.stringForType_(NSStringPboardType)
                if text and text != _last_clipboard_text:
                    _last_clipboard_text = text
                    add_event(f"> [CLIPBOARD]:\n```text\n{text[:2000]}\n```")
        except Exception:
            pass

def window_checker_loop():
    global _current_heading, _last_screen_text, _is_paused
    while True:
        time.sleep(WINDOW_CHECK_SEC)
        title, app = get_active_window()
        if not title: continue
        
        is_secure = any(sec in app.lower() for sec in SECURE_APPS) or any(sec in title.lower() for sec in SECURE_APPS)
        
        new_heading = f"{app} — {title}"
        if is_secure:
            new_heading = f"🔒 [SECURE APP PAUSED] {app} — {title}"
        
        with _lock:
            if is_secure != _is_paused:
                _is_paused = is_secure
                if is_secure:
                    _current_modifiers.clear()
            
            if new_heading != _current_heading:
                _flush_keys()
                if _current_events:
                    _sections.append({
                        "heading": _current_heading or FALLBACK_HEADING,
                        "events": list(_current_events),
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                    })
                    _current_events.clear()
                _current_heading = new_heading
                _last_screen_text = "" 
        
        if not _is_paused:
            threading.Thread(target=scan_screen, daemon=True).start()

def _diag(msg: str) -> None:
    """Write a diagnostic line to logs/diagnostics.log (and stderr) for debugging when app doesn't seem to work."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        d = LOG_DIR / "diagnostics.log"
        with open(d, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        try:
            with open("/tmp/activitylogger_diagnostics.log", "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass
    print(line.strip(), file=sys.stderr, flush=True)

def _get_filepath() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    return LOG_DIR / f"daily_log_{date_str}.md"

def _write_to_file(filepath: Path, lines: list[str], append: bool = True) -> bool:
    """Write lines to file. Returns True on success, False on error (logs to stderr)."""
    try:
        with open(filepath, "a" if append else "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line)
        return True
    except OSError as e:
        import sys
        print(f"[ActivityLogger] WRITE ERROR: {filepath}: {e}", file=sys.stderr, flush=True)
        return False

def flush_to_file(final: bool = False):
    global _sections
    with _lock:
        _flush_keys()
        # Write events even when ActivityWatch isn't running (use fallback heading)
        if _current_events:
            heading = _current_heading or FALLBACK_HEADING
            _sections.append({
                "heading": heading,
                "events": list(_current_events),
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            })
            _current_events.clear()

        to_write = list(_sections)
        _sections.clear()

    filepath = _get_filepath()
    is_new = not filepath.exists() or filepath.stat().st_size == 0

    # Always ensure today's log file exists with at least a header (so path/permissions are verified)
    if is_new:
        header = [
            f"# Work Log — {datetime.now().strftime('%Y-%m-%d')}\n\n",
            "> Auto-generated by Interleaved Logger v4 (AX + Clipboard + Security + Hotkeys)\n\n---\n\n",
        ]
        if not _write_to_file(filepath, header, append=False):
            return

    if to_write:
        lines = []
        for section in to_write:
            lines.append(f"## {section['heading']}\n*{section['timestamp']}*\n\n")
            for ev in section["events"]:
                lines.append(f"{ev.strip()}\n\n")
            lines.append("---\n\n")
        _write_to_file(filepath, lines)

def file_writer_loop():
    while True:
        time.sleep(FLUSH_INTERVAL_SEC)
        flush_to_file()

def main():
    _diag(f"ActivityLogger starting — LOG_DIR={LOG_DIR}")
    try:
        filepath = _get_filepath()
        # Create log file at startup so path/permissions are verified and file exists even if no events yet
        if not filepath.exists() or filepath.stat().st_size == 0:
            header = [
                f"# Work Log — {datetime.now().strftime('%Y-%m-%d')}\n\n",
                "> Auto-generated by Interleaved Logger v4 (AX + Clipboard + Security + Hotkeys)\n\n---\n\n",
                f"*Logger started at {datetime.now().strftime('%H:%M:%S')}*\n\n---\n\n",
            ]
            if not _write_to_file(filepath, header, append=False):
                _diag(f"Failed to create log file at {filepath}")
            else:
                _diag(f"Log file created: {filepath}")
        else:
            _diag(f"Log file exists: {filepath}")

        title, app = get_active_window()
        if title:
            with _lock: globals()["_current_heading"] = f"{app} — {title}"
            _diag(f"ActivityWatch OK — current window: {app} — {title}")
        else:
            _diag("ActivityWatch not running or no window — events will use fallback heading")

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
            flush_to_file(final=True)
    except Exception as e:
        _diag(f"FATAL: {e}\n{traceback.format_exc()}")

if __name__ == "__main__":
    main()
