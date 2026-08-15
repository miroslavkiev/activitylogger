"""F4 — optional browser URL capture helpers (no Screen Recording / OCR).

Pure observation logic plus a mockable URL provider port. Production I/O
(AX then Apple Events) stays behind ``MacBrowserUrlProvider`` /
``get_frontmost_browser_url``.
"""

from __future__ import annotations

import re
import subprocess
from typing import Callable, Optional, Protocol

MAX_URL_LEN = 2000

# Display-name substrings (case-insensitive). Keep narrow; tests lock the table.
_BROWSER_NAME_MARKERS: tuple[str, ...] = (
    "safari",
    "google chrome",
    "chrome",
    "chromium",
    "brave",
    "microsoft edge",
    "edge",
    "arc",
    "firefox",
)

UrlFetcher = Callable[[str], Optional[str]]


class BrowserUrlProvider(Protocol):
    """Narrow port so unit tests never need live Safari/Chrome."""

    def get_url(self, app_name: str) -> Optional[str]:
        ...


class NullBrowserUrlProvider:
    """No-op provider (non-macOS / AX unavailable)."""

    def get_url(self, app_name: str) -> Optional[str]:
        return None


class MacBrowserUrlProvider:
    """AX first, then Apple Events. Never raises out of get_url."""

    def get_url(self, app_name: str) -> Optional[str]:
        return resolve_browser_url_sources(app_name)


def is_browser_app(app_name: str) -> bool:
    """True when frontmost app name looks like a supported browser."""
    name = (app_name or "").strip().lower()
    if not name:
        return False
    for marker in _BROWSER_NAME_MARKERS:
        if " " in marker or len(marker) > 4:
            if marker in name:
                return True
        else:
            # Short tokens (arc, edge): whole-word only — avoid Archive / Knowledge.
            parts = name.replace("-", " ").split()
            if marker in parts:
                return True
    return False


def normalize_url_candidate(raw: str | None) -> str | None:
    """Strip whitespace; reject empty; cap at MAX_URL_LEN."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if len(text) > MAX_URL_LEN:
        text = text[:MAX_URL_LEN]
    return text


def format_url_event(url: str) -> str:
    """Stable Markdown event line for Gemini / cleaner."""
    return f"> [URL]: {url}"


def should_emit_url(
    *,
    enabled: bool,
    paused: bool,
    candidate: str | None,
    last_emitted: str | None,
) -> bool:
    """Gate + dedup without mutating state."""
    if not enabled or paused:
        return False
    normalized = normalize_url_candidate(candidate)
    if not normalized:
        return False
    prior = last_emitted if last_emitted else None
    return normalized != prior


def apply_url_observation(
    *,
    enabled: bool,
    paused: bool,
    candidate: str | None,
    last_emitted: str | None,
) -> tuple[str | None, str | None]:
    """Pause-safe observe + optional emit (clipboard parallel).

    Returns ``(new_last_emitted, event_or_none)``.
    While paused, absorbs a non-empty candidate into ``last_emitted`` without
    emitting so the same URL is not flushed after resume.
    """
    # Treat empty string like unset for dedup (logger may use "").
    prior = last_emitted if last_emitted else None
    if not enabled:
        return prior, None
    normalized = normalize_url_candidate(candidate)
    if not normalized:
        return prior, None
    if paused:
        return normalized, None
    if normalized == prior:
        return prior, None
    return normalized, format_url_event(normalized)


# Injectable production provider (tests patch via set_url_provider).
_url_provider: BrowserUrlProvider | None = None


def set_url_provider(provider: BrowserUrlProvider | None) -> None:
    """Replace the production provider (tests). Pass None to restore default."""
    global _url_provider
    _url_provider = provider


def resolve_browser_url(app_name: str, provider: BrowserUrlProvider) -> str | None:
    """Call provider and normalize. Never raises."""
    if not is_browser_app(app_name):
        return None
    try:
        raw = provider.get_url(app_name)
    except Exception:
        return None
    return normalize_url_candidate(raw)


def resolve_browser_url_sources(
    app_name: str,
    *,
    ax_fetch: UrlFetcher | None = None,
    ae_fetch: UrlFetcher | None = None,
) -> str | None:
    """Prefer AX URL; fall back to Apple Events. Never raises."""
    if not is_browser_app(app_name):
        return None
    ax = ax_fetch or _fetch_url_via_ax
    ae = ae_fetch or _fetch_url_via_apple_events
    try:
        via_ax = ax(app_name)
    except Exception:
        via_ax = None
    normalized = normalize_url_candidate(via_ax)
    if normalized:
        return normalized
    try:
        via_ae = ae(app_name)
    except Exception:
        via_ae = None
    return normalize_url_candidate(via_ae)


def get_frontmost_browser_url(app_name: str) -> str | None:
    """Return active-tab URL for a supported browser, or None.

    Uses ``set_url_provider`` override when set; else Mac AX→AE provider.
    """
    if _url_provider is not None:
        return resolve_browser_url(app_name, _url_provider)
    return MacBrowserUrlProvider().get_url(app_name)


def _ax_attr(element, name: str):
    try:
        from ApplicationServices import AXUIElementCopyAttributeValue

        err, value = AXUIElementCopyAttributeValue(element, name, None)
        if err == 0 and value is not None:
            return value
    except Exception:
        return None
    return None


def _fetch_url_via_ax(app_name: str) -> str | None:
    """Best-effort AX document / address URL (no Screen Recording)."""
    try:
        from AppKit import NSWorkspace
        from ApplicationServices import AXUIElementCreateApplication
    except ImportError:
        return None
    try:
        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if not front:
            return None
        localized = str(front.localizedName() or "")
        if localized and app_name and localized.lower() != app_name.strip().lower():
            if not (is_browser_app(localized) and is_browser_app(app_name)):
                return None
        app_elem = AXUIElementCreateApplication(front.processIdentifier())
        windows = _ax_attr(app_elem, "AXWindows")
        if not windows:
            win = _ax_attr(app_elem, "AXFocusedWindow")
            windows = [win] if win is not None else []
        for win in windows[:3]:
            if win is None:
                continue
            for attr in ("AXDocument", "AXURL", "AXValue"):
                raw = _ax_attr(win, attr)
                if raw is None:
                    continue
                text = str(raw).strip()
                if text.startswith("http://") or text.startswith("https://"):
                    return text
            found = _ax_find_url_in_tree(win, depth=0, max_depth=4)
            if found:
                return found
    except Exception:
        return None
    return None


def _ax_find_url_in_tree(element, depth: int, max_depth: int) -> str | None:
    if depth > max_depth or element is None:
        return None
    for attr in ("AXURL", "AXDocument", "AXValue"):
        raw = _ax_attr(element, attr)
        if raw is None:
            continue
        text = str(raw).strip()
        if text.startswith("http://") or text.startswith("https://"):
            return text
    children = _ax_attr(element, "AXChildren")
    if not children:
        return None
    for child in list(children)[:12]:
        found = _ax_find_url_in_tree(child, depth + 1, max_depth)
        if found:
            return found
    return None


def _apple_script_for_browser(app_name: str) -> str | None:
    """Return osascript source for the active-tab URL, or None if unsupported."""
    name = (app_name or "").strip().lower()
    if "safari" in name:
        return 'tell application "Safari" to get URL of current tab of front window'
    if "firefox" in name:
        return 'tell application "Firefox" to get URL of active tab of front window'
    process = None
    if "brave" in name:
        process = "Brave Browser"
    elif "edge" in name:
        process = "Microsoft Edge"
    elif "arc" in name:
        process = "Arc"
    elif "chromium" in name:
        process = "Chromium"
    elif "chrome" in name:
        process = "Google Chrome"
    if process is None:
        return None
    return f'tell application "{process}" to get URL of active tab of front window'


def _fetch_url_via_apple_events(app_name: str) -> str | None:
    """Apple Events / osascript fallback for active-tab URL."""
    script = _apple_script_for_browser(app_name)
    if not script:
        return None
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    out = (proc.stdout or "").strip()
    if not out:
        return None
    if re.search(r"(?i)error|can.?t get|execution error", out):
        return None
    return out


def module_source_path() -> str:
    """Path to this module (grep-guard tests)."""
    return __file__
