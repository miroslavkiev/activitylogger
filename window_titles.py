"""F1 window title helpers - heading placeholders and merge rules.

Native resolve and ActivityWatch HTTP live in interleaved_logger (AppKit / requests).
This module stays free of AppKit so unit tests can import merge/heading logic alone.
"""

from __future__ import annotations

from markdown_format import sanitize_markdown_inline

UNKNOWN_WINDOW = "Unknown window"
EM_DASH = " \u2014 "
FALLBACK_HEADING = f"Unknown{EM_DASH}{UNKNOWN_WINDOW}"


def build_heading_body(app: str, title: str) -> str | None:
    """Build one normalized app and title heading body."""
    clean_app = sanitize_markdown_inline(app)
    clean_title = sanitize_markdown_inline(title)
    if not clean_app and not clean_title:
        return None
    display_app = clean_app or "Unknown"
    display_title = clean_title or UNKNOWN_WINDOW
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
