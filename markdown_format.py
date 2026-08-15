"""Shared Markdown line formats for the activity logger and cleaner.

Single source of truth for capture-trigger names, timestamp lines, and the
stable F4 URL event prefix.
"""

from __future__ import annotations

import re

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

# F4 stable token for Gemini / cleaner (leading prefix only).
URL_EVENT_PREFIX = "> [URL]: "

_TRIGGER_ALT = "|".join(sorted(CAPTURE_TRIGGERS))
# Legacy: *HH:MM:SS*  |  F5: *HH:MM:SS · trigger:{closed-set-name}*
RE_TIMESTAMP_LINE = re.compile(
    rf"^\*\d{{2}}:\d{{2}}:\d{{2}}(?: · trigger:(?:{_TRIGGER_ALT}))?\*\s*$"
)


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


def is_timestamp_line(line: str) -> bool:
    """True for legacy or F5 timestamp lines with a closed-set trigger name."""
    return bool(RE_TIMESTAMP_LINE.match(line))
