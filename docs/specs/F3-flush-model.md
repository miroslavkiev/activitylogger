# F3 buffers, deadlines, flush, and lifecycle

**Status:** implemented and source-verified on 2026-08-21.

## Buffer model

- `_current_keystrokes` holds character-level key units.
- `_current_events` holds the open section body.
- `_sections` holds sealed sections with heading, events, display timestamp, and timezone-aware `captured_at`.
- Pending click reservations occupy ordered section positions but cannot be persisted until enrichment resolves or the reservation expires.

The configured soft caps are 2,000 key units, 500 events, and 200 sections. Hitting a cap forces joining or durable flush. On a repeated write failure, restoration keeps the newest bounded sections and emits a diagnostic if older entries must be dropped.

## Keys and typing idle

Printable characters are stored at character level. Enter, Tab, Escape, and hotkeys retain their established tokens. Backspace removes the last buffered unit.

The typing timer waits until the exact last-key deadline or a state-change event. After `typing_pause_sec`, it joins the key buffer into `_current_events`. It does not seal a section and does not write Markdown. `typing_pause` remains reserved and is never emitted as a trigger.

Before accepting a key, the logger synchronously verifies secure-app context and Accessibility secure-field state. Unknown is unsafe. A pause clears pending key and modifier state.

## Section transitions

On a heading change, the logger flushes an open scroll burst under the old context, joins keys, seals old events with the `app_switch` cause, then changes heading. Each sealed section records its capture time so a delayed flush writes it to the correct daily file across midnight.

Clicks reserve their section order immediately, then resolve Accessibility details asynchronously. Persistence stops at the first unresolved reservation. A generation mismatch, context mismatch, pause, failure, or expiry removes the reservation rather than writing misleading content.

## Durable flush

`flush_to_file()` is serialized by a dedicated flush lock. Under the state lock it:

1. Flushes or discards scroll state according to privacy.
2. Joins keys and seals open events.
3. Expires unresolved clicks.
4. Detaches only sections before the unresolved-click barrier.

Detached sections are grouped by their capture date and written in order. New files receive one header. A failed group restores that group and all later uncommitted groups, never groups already written. Writes refuse links, non-regular files, and foreign ownership and enforce mode `600`.

The file writer waits on its deadline or an explicit wake event. Failure uses bounded exponential backoff up to 60 seconds. It does not busy-poll.

## Shutdown and worker supervision

SIGTERM and SIGINT handlers are installed before config loading, record only the first signal name, request stop, and wake every deadline waiter. The main thread emits the privacy-neutral shutdown diagnostic during cleanup. Worker wrappers treat unexpected exit as fatal. The main thread monitors key and mouse listeners, stops and joins listeners and workers, discards unresolved click placeholders, handles the final scroll burst, performs one final durable flush, closes the instance lock, restores prior signal handlers, and returns nonzero on fatal or final-flush failure.

Production rebuild and config restart share one process lifecycle. They validate the installed plist, boot out the Launch Agent, snapshot exact executable-path processes before and after bootout, and terminate only revalidated residual PIDs. Restart uses launchd bootstrap and requires a fresh native PID plus a separate stability observation. Rebuild rollback restores the unchanged prevalidated app. A failed config restart performs one bounded recovery bootstrap for the unchanged app and still reports failure.

## Acceptance

Tests cover exact typing deadlines, no typing-pause seal, concurrent flush serialization, partial-write restoration, midnight routing, bounded retries, pending-click barriers, early and ordinary signal shutdown, listener and worker failure, final-flush exit status, bootout-before-termination ordering, slow launch discovery, config-restart recovery, rollback, and fresh-PID exclusion.
