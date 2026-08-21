# F6 optional scroll coalescing

**Status:** implemented, opt-in, and source-verified on 2026-08-21.

## Contract

`features.scroll_coalesce_enabled` defaults to `false`. When disabled, the mouse listener registers click handling only. When enabled, scroll callbacks accumulate one bounded burst and mouse movement remains unregistered.

A burst records tick count, net vertical and horizontal movement, first and last monotonic times, and its starting app and heading context. After the configured quiet period, default 400 ms, one event is appended and the section is sealed. If trigger annotations are enabled, the section receives `scroll_coalesce`; otherwise it is sealed without an annotation.

## Deadline and context behavior

The scroll worker waits until the exact last-scroll deadline or a state-change event. It does not poll on a fixed fraction of the configured interval. A new tick moves the deadline and wakes the waiter.

On an app change, an open safe burst is flushed under its original context before the heading changes. A file flush and orderly shutdown also flush a safe open burst. If capture is paused, the burst is discarded instead.

## Privacy and failure behavior

Scroll ticks are ignored while paused. A transition into pause clears the in-flight burst. No later resume can recover it. Scroll capture never triggers an Accessibility text scan, screenshot, or Screen Recording.

If the host pynput version cannot register scroll callbacks, the logger emits a bounded diagnostic, falls back to click-only mouse capture, and stays running.

## Config

```toml
[features]
scroll_coalesce_enabled = false
scroll_coalesce_ms = 400
```

The quiet interval must be an integer from 50 through 5,000 ms. Schema and validation are owned by [`F2-config.md`](F2-config.md).

## Acceptance

Tests cover disabled listener shape, tick accumulation, exact rescheduled deadline, one event per burst, app-switch ownership, pause discard, flush and shutdown behavior, trigger integration, click-only fallback, and the absence of mouse-move or scan behavior.
