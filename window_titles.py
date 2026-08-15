"""F1 window title helpers — heading placeholders and merge rules.

Native resolve and ActivityWatch HTTP live in interleaved_logger (AppKit / requests).
This module stays free of AppKit so unit tests can import merge/heading logic alone.
"""

from __future__ import annotations

UNKNOWN_WINDOW = "Unknown window"
FALLBACK_HEADING = f"Unknown — {UNKNOWN_WINDOW}"
EM_DASH = " — "  # U+2014 with surrounding spaces


def build_heading_body(app: str, title: str) -> str | None:
    """Build `{app} — {title}` body. Return None when both fields are empty."""
    if not app and not title:
        return None
    display_app = app if app else "Unknown"
    display_title = title if title else UNKNOWN_WINDOW
    return f"{display_app}{EM_DASH}{display_title}"


def merge_native_and_aw(
    native: tuple[str, str],
    aw: tuple[str, str] | None,
    *,
    enricher_enabled: bool,
) -> tuple[str, str]:
    """Native wins on non-empty fields; AW fills empty fields only when enabled."""
    app, title = native[0] or "", native[1] or ""
    if not enricher_enabled or aw is None:
        return app, title
    aw_app, aw_title = aw[0] or "", aw[1] or ""
    if not app and aw_app:
        app = aw_app
    if not title and aw_title:
        title = aw_title
    return app, title
