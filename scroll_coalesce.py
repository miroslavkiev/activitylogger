"""F6 — optional scroll burst coalescing (pure helpers; no pynput / GUI).

Config keys and defaults live in F2 (`scroll_coalesce_enabled`, `scroll_coalesce_ms`).
This module only owns burst accumulate / quiet / format / pause discard logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ScrollBurst:
    """In-memory open scroll burst (one quiet flush → one Markdown line)."""

    ticks: int = 0
    net_dx: float = 0.0
    net_dy: float = 0.0
    start_mono: float = 0.0
    last_mono: float = 0.0
    app: str = ""
    heading: str = ""

    @property
    def is_open(self) -> bool:
        return self.ticks > 0


def net_direction(net_dx: float, net_dy: float) -> str:
    """Map summed deltas to net up/down/left/right/mixed/none (pynput: +dy=up, +dx=right)."""
    vert = 0
    if net_dy > 0:
        vert = 1
    elif net_dy < 0:
        vert = -1
    horiz = 0
    if net_dx > 0:
        horiz = 1
    elif net_dx < 0:
        horiz = -1
    if vert != 0 and horiz != 0:
        return "mixed"
    if vert > 0:
        return "up"
    if vert < 0:
        return "down"
    if horiz > 0:
        return "right"
    if horiz < 0:
        return "left"
    return "none"


def format_scroll_event(ticks: int, direction: str, app: str | None = None) -> str:
    """One Markdown scroll body line. No cursor coordinates."""
    line = f"🖱️ **Scroll:** {ticks} ticks, net {direction}"
    app_name = (app or "").strip()
    if app_name:
        return f"{line} ({app_name})"
    return line


def format_burst_line(burst: ScrollBurst) -> str:
    """Format an open burst into a scroll Markdown line."""
    return format_scroll_event(
        burst.ticks,
        net_direction(burst.net_dx, burst.net_dy),
        app=burst.app or None,
    )


def accumulate(
    burst: Optional[ScrollBurst],
    *,
    dx: float,
    dy: float,
    now: float,
    app: str = "",
    heading: str = "",
) -> ScrollBurst:
    """Create or update the open burst for one scroll tick."""
    if burst is None or not burst.is_open:
        return ScrollBurst(
            ticks=1,
            net_dx=float(dx),
            net_dy=float(dy),
            start_mono=now,
            last_mono=now,
            app=(app or "").strip(),
            heading=heading or "",
        )
    burst.ticks += 1
    burst.net_dx += float(dx)
    burst.net_dy += float(dy)
    burst.last_mono = now
    return burst


def should_flush(
    burst: Optional[ScrollBurst],
    *,
    now: float,
    coalesce_ms: int,
) -> bool:
    """True when an open burst has been quiet for coalesce_ms."""
    if burst is None or not burst.is_open:
        return False
    # Compare in whole milliseconds to avoid float edge cases (e.g. 0.7-0.3).
    quiet_ms = max(0, int(coalesce_ms))
    elapsed_ms = int(round((now - burst.last_mono) * 1000.0))
    return elapsed_ms >= quiet_ms


def discard_burst(_burst: Optional[ScrollBurst] = None) -> None:
    """Pause / discard path: drop the open burst (no flush, no seal)."""
    return None


def mouse_listener_kwargs(*, on_click, on_scroll=None) -> dict:
    """Build pynput mouse.Listener kwargs. Never includes on_move."""
    kwargs: dict = {"on_click": on_click}
    if on_scroll is not None:
        kwargs["on_scroll"] = on_scroll
    return kwargs
