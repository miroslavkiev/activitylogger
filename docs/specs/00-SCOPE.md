# ActivityLogger locked product decisions

**Status:** current product boundary for ActivityLogger 4.6.0.

This file owns the product boundary for all feature specs. [`00-MASTER.md`](00-MASTER.md) owns the full cross-feature contract, and [`IMPL-STATUS.md`](IMPL-STATUS.md) owns current verification.

## Product job

ActivityLogger keeps a private local record of work activity, then helps the operator review completed days to understand work patterns, friction, and possible time-saving improvements.

The main flow is:

1. Capture work context into a private daily Markdown file.
2. Keep exact local integrity records for the canonical day.
3. Create a smaller private review view for an exact completed 5-day or 7-day window.
4. Let the operator review, redact, and use the files with a trusted local tool or a chosen external tool.
5. Record the review outcome and an optional note locally. ActivityLogger does not act on suggestions.

## Canonical and derived artifacts

- Starting on local day 2026-08-27, `logs/daily_log_YYYY-MM-DD.md` is the canonical v2 activity record and the legacy writer is disabled.
- The intent journal, invalid marker, and ready proof are private, payload-free integrity metadata. They do not create a second captured-payload log.
- The pending transaction is private recovery state. While a v2 write is in progress, it temporarily contains encoded planned appends with captured payload. It is removed after exact commit succeeds.
- Canonical v2 Markdown and its intent journal remain authoritative.
- Compact views, v3 workload summaries, historical conversions, and weekly packs are derived review files. They never replace or modify the canonical source.
- A v3 workload summary is intentionally lossy. It keeps exact non-click evidence, groups some clicks, and records its limits.
- A weekly pack accepts only an exact completed 5-day or 7-day v2 window with valid ready proofs. It never fills a missing day with an older day.
- Review files stay outside `logs/`, use private permissions, and may still contain captured text.

## Approved constraints

- Production uses the certificate-signed `.app` through the `open -W` Launch Agent chain.
- Character-level keystrokes and hotkey encoding remain part of the record.
- Configured secure-app matches, secure fields, manual pause, and the visible Review Center pause every capture channel through one fail-closed gate.
- Daily Markdown is the only user-facing live capture file.
- The capture core remains one Python process.
- The Review Center and health commands remain payload-free.
- ActivityLogger may create review files, but it does not analyze them, upload them, contact anyone, or create an automation.
- The operator must review and redact private text before any external use. Prefer local analysis.
- Source logs and integrity evidence have no automatic deletion or retention policy.

## Current feature set

| ID | Feature |
|---|---|
| F1 | Native-first window titles with optional ActivityWatch enrichment |
| F2 | Trusted local config with bounded values and safe defaults |
| F3 | Durable capture-date persistence and authoritative v2 transactions |
| F4 | Optional browser URL capture with safe normalization |
| F5 | Capture-trigger metadata and ordered click enrichment |
| F6 | Optional bounded scroll coalescing |
| V2 | Exact canonical analysis Markdown, intent parity, recovery, and ready proofs |
| Review | Private v3 workload summaries, fixed weekly packs, manual pause, and the native Review Center |

## Explicit non-goals

- Screenshots, Screen Recording, OCR, camera, microphone, audio, or video
- Mouse-move trails
- A second capture daemon
- JSONL or SQLite capture sidecars
- Cloud storage, a query API, an MCP service, or a remote collector
- Automatic upload or automatic online analysis
- Automatic execution of an automation suggestion
- Cleaner-side secret redaction
- Broad app or window ignore lists
- Locale-specific interface labels
- Automatic deletion or retention enforcement
- Hot config reload
- Browser extension capture

## Shared non-negotiables

- Privacy checks must fail closed.
- Manifest-owned v2 data must never be restored to memory and written twice.
- Derived files must state their source, limits, and authority.
- Production rebuild remains `./scripts/rebuild_and_restart.sh` with the pinned certificate identity.
- New behavior needs focused acceptance tests before implementation is called complete.
