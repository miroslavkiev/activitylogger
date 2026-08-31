# ActivityLogger master specification

**Status:** implemented, source-verified, and live-deployment verified on 2026-08-21.

This document is the cross-feature contract. [`00-SCOPE.md`](00-SCOPE.md) owns product bounds, [`F2-config.md`](F2-config.md) owns config keys, and [`docs/MACOS_TCC.md`](../MACOS_TCC.md) owns production operations.

## Product contract

ActivityLogger is one macOS process that records a private, human-readable activity transcript into daily Markdown. It captures active app and window context, character-level keys and hotkeys, clicks enriched through Accessibility, changed Accessibility text, and clipboard changes. Browser URLs, trigger annotations, and scroll capture are optional.

There is no screenshot, Screen Recording, OCR, audio, video, JSONL, SQLite, network service, or automatic retention service.

## Runtime and build

- Production is `dist/ActivityLoggerNative.app` through `start_logger.sh` -> `open -W`.
- Build and test use exact Python 3.11.9 from `.python-version` in `.venv`.
- Dependencies install from the hashed `requirements.txt` lock.
- The canonical build creates a staged PyInstaller onedir app and signs nested code plus the outer bundle with the pinned local identity and sole Apple Events entitlement. Hardened Runtime is intentionally not enabled for the retained self-signed no-Team-ID leaf. Verification enforces exact nested and outer signatures, leaf and designated requirement, identifier, entitlement allowlist, symlink containment, and Mach-O load-path containment.
- The build validates the installed plist, boots out and quiesces the Launch Agent before promotion, atomically promotes, bootstraps, and requires a fresh stable exact-path native PID. Failed proof restores the unchanged prevalidated bundle and proves a fresh previous-app PID.
- Normal builds use a pre-provisioned dedicated keychain and pinned leaf fingerprint. They never create or rotate an identity.

## Privacy contract

Password-manager matching and Accessibility secure-field detection pause every capture channel. An unknown result is unsafe and fails closed. Key handling performs a synchronous secure-app and secure-field decision before appending. Asynchronous work carries privacy and context generations and is discarded if state changes.

On a pause edge, in-flight keys, modifiers, scroll state, click reservations, and capture context that could cross the boundary are discarded. Clipboard change counts advance during a pause so paused content cannot appear later.

## Capture and persistence contract

- Keys remain character-level. Typing idle joins the key buffer into the current event list but does not seal a section or write a file.
- Window changes flush keys and scroll state under the previous context before moving to the new heading.
- Clicks reserve ordered section position synchronously. Accessibility enrichment fills that reservation only when privacy generation and click context still match. Failed or expired reservations are discarded.
- Clipboard reads use change counts plus digests, retain no unnecessary plaintext state, and retry initialization with bounded backoff.
- Accessibility scans have depth, child, character, global-node, time, queue, and debounce bounds. Unknown or stale results are discarded.
- File, typing, and scroll timers wait on stateful deadlines rather than fixed polling.
- File flush is serialized. It detaches resolved sections, groups them by capture date, writes each group durably, and restores only uncommitted groups after failure. Buffer caps bound retry memory.
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
- Its status view is payload-free. It shows health, last safe write freshness, privacy pause state, fixed-window weekly readiness, and private storage totals.
- Manual pause uses the same fail-closed capture gate as secure apps and secure fields. Resume clears only the manual pause. The state is private, durable, and restored after restart.
- A weekly pack accepts only an exact completed 5-day or 7-day v2 window with valid ready proofs. It never fills a missing day with an older day.
- Weekly output is private and atomic. `INDEX.json` is the completion marker and is published last after source hashes are checked again.
- Review outcomes are explicit local operator notes. The logger does not infer or send them.

Unsafe full-URL mode and remote ActivityWatch access emit startup warnings. Browser URL capture never requires Screen Recording.

## Config and resource limits

Config loads once from the deterministic discovery order in [`F2-config.md`](F2-config.md). It is trusted operator input only after checks for path, file type, ownership, links, and permissions. Malformed or out-of-range known values are fatal; unknown keys warn and are ignored. All numeric values are finite and bounded.

## Data handling

Runtime sets umask `077`. Config directories, log directories, daily files, diagnostics, lock files, and compacted results use private ownership and modes. Logs remain plaintext and are retained indefinitely until the operator archives or deletes them. There is no automatic deletion.

The Markdown compactor restructures plaintext and does not redact. Sections at or below 1 MiB and 10,000 lines receive full transformations. Oversized sections pass through unchanged after a diagnostic, using a spooled temporary file for bounded memory and never silently dropping content. Review and redact output before any external LLM use.

## Validation gate

Source hardening and signed-bundle deployment completed after the original three QA loops plus the final lifecycle and Launch Agent acceptance loops. The final gate is:

- all 335 source tests passed; the strict deployed codesign test passed separately after the final rebuild
- dependency consistency, lint, strict audit, shell syntax, and plist validation passed
- CI pinned to `macos-15`, with staged signing and tamper-rejection coverage

The dedicated keychain import, pinned-leaf continuity, staged non-Hardened construction, strict deployed verification, bootout/bootstrap lifecycle, exact native-process proof, and real typing smoke passed. The installed mode `600` plist enforces `KeepAlive=true`, `RunAtLoad=true`, and `Umask=63`. The legacy PKCS#12 and any redundant login-keychain identity remain private mode `600` pending explicit operator disposition; they do not block runtime.

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
| [`STATUS.md`](STATUS.md) | Current acceptance status |
