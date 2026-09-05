# ActivityLogger master specification

**Status:** current contract for ActivityLogger 4.6.0. See [`IMPL-STATUS.md`](IMPL-STATUS.md) for the latest accepted source and live deployment proof.

This document is the cross-feature contract. [`00-SCOPE.md`](00-SCOPE.md) owns product bounds, [`F2-config.md`](F2-config.md) owns config keys, and [`docs/MACOS_TCC.md`](../MACOS_TCC.md) owns production operations.

## Product contract

ActivityLogger is one macOS process that records a private, human-readable activity transcript into daily Markdown. It captures active app and window context, character-level keys and hotkeys, clicks enriched through Accessibility, changed Accessibility text, and clipboard changes. Browser URLs, trigger annotations, and scroll capture are optional.

There is no screenshot, Screen Recording, OCR, audio, video, SQLite, network service, or automatic retention service. Canonical activity and private review outcomes use Markdown.

## Runtime and build

- Production is `dist/ActivityLoggerNative.app` through `start_logger.sh` -> `open -W`.
- Build and test use exact Python 3.11.9 from `.python-version` in `.venv`.
- Dependencies install from the hashed `requirements.txt` lock.
- The canonical build creates a staged PyInstaller onedir app and signs nested code plus the outer bundle with the pinned local identity and sole Apple Events entitlement. Hardened Runtime is intentionally not enabled for the retained self-signed no-Team-ID leaf. Verification enforces exact nested and outer signatures, leaf and designated requirement, identifier, entitlement allowlist, symlink containment, and Mach-O load-path containment.
- The build validates the installed plist, boots out and quiesces the Launch Agent before promotion, atomically promotes, bootstraps, and requires a fresh stable exact-path native PID. Failed proof restores the unchanged prevalidated bundle and proves a fresh previous-app PID.
- Normal builds use a pre-provisioned dedicated keychain and pinned leaf fingerprint. They never create or rotate an identity.

## Privacy contract

Configured secure-app matching and Accessibility secure-field detection pause every capture channel. An unknown result is unsafe and fails closed. Capture admission verifies the current app and secure field before taking data and aligns the event heading with that context. Queued Accessibility work checks that context before reading and again before keeping the result. Asynchronous work carries privacy and context generations and is discarded if state changes.

On a pause edge, in-flight keys, modifiers, scroll state, click reservations, and capture context that could cross the boundary are discarded. Clipboard change counts advance during a pause so paused content cannot appear later.

## Capture and persistence contract

- Keys remain character-level. Typing idle joins the key buffer into the current event list but does not seal a section or write a file.
- Window changes flush keys and scroll state under the previous context before moving to the new heading.
- Clicks reserve ordered section position synchronously. Accessibility enrichment fills that reservation only when privacy generation and click context still match. Failed or expired reservations are discarded.
- Clipboard reads use change counts plus digests, retain no unnecessary plaintext state, and retry initialization with bounded backoff.
- Accessibility scans have depth, child, character, global-node, time, queue, and debounce bounds. Unknown or stale results are discarded.
- File, typing, and scroll timers wait on stateful deadlines rather than fixed polling.
- File flush is serialized and groups records by capture date. Before the v2-only cutover, the legacy writer restores only groups that were not written. On a known prepare failure, admission stops while accepted records stay in memory for bounded retries. This storage block is separate from privacy pause, so it does not discard accepted data. A successful recovery records one payload-free storage gap marker. Frequent wakeups do not move the file deadline.
- Starting on local day 2026-08-27, the canonical daily file is strict `activitylogger-analysis-v2` Markdown and the legacy writer is disabled for that day and later.
- Each v2 flush publishes a private pending transaction before its records leave memory. The transaction owns exact planned appends to the canonical Markdown and its intent journal. Commit verifies both outputs before removing the pending transaction.
- Once a pending transaction owns v2 records, those records are never restored to the in-memory buffer. An uncertain prepare or commit fails closed and stops capture so startup recovery can finish the same transaction without writing a duplicate.
- Startup completes a valid recoverable pending transaction, then validates the current canonical v2 day and its complete intent stream before capture continues. If saved files no longer match a safe planned state, startup refuses to capture and requires repair.
- A healthy later commit triggers startup or day-change checks of existing completed days, including days before an offline gap, and may publish missing ready proofs. Missing or invalid days are never invented or repaired by this check. A ready proof binds hashes for the canonical file and intent journal. It proves integrity, not continuous capture coverage.
- SIGTERM and SIGINT request coordinated shutdown. Listeners and workers stop, a final flush runs, and fatal worker or persistence failure returns a nonzero status.

## Optional features

| Feature | Default | Current behavior |
|---|---:|---|
| ActivityWatch enrichment | on | Native fields win. Only loopback endpoints are allowed unless unsafe remote access is explicitly enabled. Source failures use backoff. |
| Browser URL capture | off | Accessibility first, Apple Events fallback. Safe mode strips user information and fragment and neutralizes every query name and value. |
| Capture trigger annotations | off | When enabled, sealed sections receive one closed-set trigger token. |
| Scroll coalescing | off | One bounded burst becomes one event after the exact quiet deadline. It seals a section even when annotations are off. |

## Local review and operator controls

- The native Review Center stays hidden during Launch Agent startup and opens when the running app is opened again.
- The native Daily status and Weekly review tabs share one whole-window privacy pause. Switching tabs never clears it.
- Its status view is payload-free. It shows health, last safe write freshness, privacy pause state, fixed-window weekly readiness, and private storage totals. ActivityLogger creates private review files but does not analyze or send them.
- The guided flow is to choose an exact completed 5-day or 7-day window, create the files, show them in Finder and start with `REVIEW_PROMPT.md`, then record the local result. Private text must be reviewed and redacted before any online use.
- Capture stays paused while the Review Center is visible. Closing or minimizing it clears only that window pause. Manual, secure-app, and secure-field pauses remain in force.
- Manual pause uses the same fail-closed capture gate as secure apps and secure fields. Resume clears only the manual pause. The state is private, durable, and restored after restart.
- A weekly pack accepts only an exact completed 5-day or 7-day v2 window with valid ready proofs. It never fills a missing day with an older day.
- Weekly output is private and atomic. `INDEX.json` is the completion marker and is published last after source hashes are checked again.
- Review outcomes are explicit local operator notes with exact start, end, day count and pack identity. A draft cannot silently move to another window. Each text field is limited to 4,000 characters. The logger does not infer or send outcomes.
- One request shares day inspections across health, storage and weekly readiness. Export always checks the sources again. Prepared packs reopen from their private completion index without requiring the sources to be present.
- Context labels, workload counts and heartbeat gaps are quality warnings, separate from integrity. The bundled offline recovery guide describes safe next steps.

Unsafe full-URL mode and remote ActivityWatch access emit startup warnings. Browser URL capture never requires Screen Recording.

## Config and resource limits

Config loads once from the deterministic discovery order in [`F2-config.md`](F2-config.md). It is trusted operator input only after checks for path, file type, ownership, links, and permissions. Malformed or out-of-range known values are fatal; unknown keys warn and are ignored. All numeric values are finite and bounded.

## Data handling

Runtime sets umask `077`. Config directories, log directories, daily files, diagnostics, lock files, and compacted results use private ownership and modes. Logs remain plaintext and are retained indefinitely until the operator archives or deletes them. There is no automatic deletion.

The Markdown compactor is only for legacy logs. It restructures plaintext and does not redact. Sections at or below 1 MiB and 10,000 lines receive full transformations. Oversized legacy sections pass through unchanged after a diagnostic, using a spooled temporary file for bounded memory and never silently dropping content. The compactor rejects analysis-format logs because v2 is already compact.

Compact views, v3 workload summaries, historical conversions, and weekly packs are derived private files. They never replace or modify canonical v2 Markdown or its intent journal. They may contain captured text and must be reviewed and redacted before any external use.

## Validation gate

The single current verification record is [`IMPL-STATUS.md`](IMPL-STATUS.md). It owns the latest test count, signed deployment proof, exact process evidence, and live Review Center result. Historical F0 through F6 evidence remains in [`STATUS.md`](STATUS.md) and [`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md).

## Specification map

| Document | Authority |
|---|---|
| [`F0-constraints-and-non-goals.md`](F0-constraints-and-non-goals.md) | Safety constraints and exclusions |
| [`F1-window-titles.md`](F1-window-titles.md) | Native and ActivityWatch resolution |
| [`F2-config.md`](F2-config.md) | Schema, discovery, trust, and bounds |
| [`F3-flush-model.md`](F3-flush-model.md) | Buffers, timers, lifecycle, and durability |
| [`F4-browser-url.md`](F4-browser-url.md) | URL sources and privacy normalization |
| [`F5-capture-triggers.md`](F5-capture-triggers.md) | Section triggers and click ordering |
| [`F6-scroll-coalescing.md`](F6-scroll-coalescing.md) | Scroll burst lifecycle |
| [`IMPL-STATUS.md`](IMPL-STATUS.md) | Current source and live acceptance status |
| [`STATUS.md`](STATUS.md) | Historical F0 through F6 closeout record |
| [`IMPLEMENTATION-PLAN.md`](IMPLEMENTATION-PLAN.md) | Historical version 4.1.0 implementation closeout |
