# F3 buffers, deadlines, flush, and lifecycle

**Status:** current persistence contract for ActivityLogger 4.5.1. Current acceptance evidence is in [`IMPL-STATUS.md`](IMPL-STATUS.md).

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
4. Selects only sections before the unresolved-click barrier for persistence.

Selected sections are grouped by their capture date and written in order. Writes refuse links, non-regular files, and foreign ownership and enforce mode `600`.

For days before 2026-08-27, the legacy writer adds one header to a new daily file. A failed legacy group restores that group and all later uncommitted legacy groups, never groups already written.

For local day 2026-08-27 and later, `daily_log_YYYY-MM-DD.md` is the strict v2 canonical file and the legacy writer is disabled. The v2 path is one authoritative transaction:

1. Recover any existing pending transaction before new capture data is prepared.
2. Build exact planned appends for the canonical v2 Markdown and its intent journal.
3. Publish a private pending manifest while the records are still in memory.
4. After manifest publication, remove only the records now owned by that transaction from memory.
5. Write and verify the exact planned outputs, then remove the pending manifest.

A failure before manifest publication leaves v2 records in memory for a later retry. Once the manifest exists, its records must never return to memory because that could write them twice. An uncertain prepare or any finalization failure stops capture and leaves recovery evidence for the next startup. Startup recovery completes a valid recoverable transaction and validates canonical-to-intent parity before capture continues. If a target no longer matches a safe planned state, startup refuses to capture and requires repair.

The first valid next-day heartbeat may publish `.daily_log_YYYY-MM-DD.ready.json` for the completed day. This payload-free proof binds the canonical and intent hashes. It proves source integrity, not full-day capture coverage.

The file writer waits on its deadline or an explicit wake event. Failure uses bounded exponential backoff up to 60 seconds. It does not busy-poll.

## Shutdown and worker supervision

SIGTERM and SIGINT handlers are installed before config loading, record only the first signal name, request stop, and wake every deadline waiter. The main thread emits the privacy-neutral shutdown diagnostic during cleanup. Worker wrappers treat unexpected exit as fatal. The main thread monitors key and mouse listeners, stops and joins listeners and workers, discards unresolved click placeholders, handles the final scroll burst, performs one final durable flush, closes the instance lock, restores prior signal handlers, and returns nonzero on fatal or final-flush failure.

Production rebuild and config restart share one process lifecycle. They validate the installed plist, boot out the Launch Agent, snapshot exact executable-path processes before and after bootout, and terminate only revalidated residual PIDs. Restart uses launchd bootstrap and requires a fresh native PID plus a separate stability observation. Rebuild rollback restores the unchanged prevalidated app. A failed config restart performs one bounded recovery bootstrap for the unchanged app and still reports failure.

## Acceptance

Tests cover exact typing deadlines, no typing-pause seal, concurrent flush serialization, legacy partial-write restoration, midnight routing, authoritative ownership before detach, exact commit, partial recovery, no restore after ownership, ready-proof publication, bounded retries, pending-click barriers, signal shutdown, listener and worker failure, final-flush exit status, bootout-before-termination ordering, slow launch discovery, config-restart recovery, rollback, and fresh-PID exclusion.
