# ActivityLogger for macOS

ActivityLogger records active windows, keystrokes, clicks, Accessibility text, optional browser URLs, and clipboard changes into private daily Markdown logs for local analysis.

**Version:** 4.4.0 | **Runtime:** `dist/ActivityLoggerNative.app` | **Operations:** [`docs/MACOS_TCC.md`](docs/MACOS_TCC.md)

## Safety model

- Password managers and Accessibility secure fields pause every capture channel. Unknown privacy state fails closed.
- Clipboard changes observed during a pause are consumed and are not logged later.
- Browser URL capture is off by default. Safe mode removes user information and fragments and neutralizes the complete query string. The unsafe full-URL option is an explicit privacy-risk opt-in.
- ActivityWatch enrichment is optional and accepts only loopback endpoints by default. Remote access requires an explicit unsafe opt-in.
- Config, log, and generated output paths are checked and created with private permissions.
- Logs are retained indefinitely until the operator archives or deletes them. There is no automatic deletion.

## Canonical environment

Use the exact interpreter in [`.python-version`](.python-version), currently Python 3.11.9, and the project-local `.venv`:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/ruff check --select E4,E7,E9,F .
.venv/bin/python -m pip_audit --strict
.venv/bin/python -m pytest -q
```

`requirements.txt` is the hash-locked macOS Apple silicon environment. Regenerate it only with `./scripts/compile_requirements.sh`.

## One-time signing migration

Before the first canonical rebuild, provision the dedicated signing keychain while the currently deployed app and legacy PKCS#12 file still exist:

```bash
./scripts/setup_signing_identity.sh --import-p12 .codesign/identity.p12
```

Use the native SecurityAgent prompts. Password environment variables are rejected. Provisioning verifies the supplied certificate against the deployed app, imports a nonextractable private key into the dedicated keychain, and pins the leaf SHA-1 fingerprint. `--rotate-identity` is only for an intentional identity change and warns that existing TCC grants will not follow.

The 2026-08-21 migration, rebuild, exact-process restart, and capture smoke test succeeded. The legacy PKCS#12 and any redundant login-keychain copy remain private with mode `600` because deleting recovery identities is irreversible and requires explicit operator approval. They are not runtime blockers. Keep them out of shared backups until the operator archives or removes them deliberately.

## Build, install, and TCC

After provisioning, use only the canonical build:

```bash
./scripts/rebuild_and_restart.sh
```

It creates a staged PyInstaller onedir app and signs every nested Mach-O plus the outer bundle with the pinned identity and the sole Apple Events entitlement. Hardened Runtime is intentionally not enabled for the retained local self-signed leaf because macOS rejected that untrusted chain under Hardened Runtime. Verification instead enforces strict nested and outer signatures, the exact leaf and designated requirement, the bundle identifier, an exact entitlement allowlist, symlink containment, and Mach-O load-path containment.

Before promotion, the build validates the installed Launch Agent, boots it out, proves exact-path processes are quiesced, and terminates only revalidated residual PIDs with bounded TERM then KILL escalation. After atomic promotion it bootstraps the Launch Agent and requires a fresh stable exact-path process. Failed proof restores the unchanged prevalidated bundle and bootstraps a fresh previous-app process.

Install or reconcile the Launch Agent, then restart through the verified lifecycle:

```bash
./scripts/install_launch_agent.sh
./scripts/restart_logger.sh
```

The installed plist is mode `600` and requires `KeepAlive=true`, `RunAtLoad=true`, and `Umask=63`.

Grant `dist/ActivityLoggerNative.app` Accessibility and Input Monitoring. Optional browser Apple Events may prompt for Automation only when browser URL capture is enabled. Do not add the app as both a Login Item and a Launch Agent.

## Config

```bash
mkdir -p ~/.config/activitylogger
cp config.example.toml ~/.config/activitylogger/config.toml
chmod 700 ~/.config/activitylogger
chmod 600 ~/.config/activitylogger/config.toml
```

Config is trusted local operator input and loads once at process start. The loader rejects unsafe file ownership, links, permissions, malformed values, and out-of-range resource limits. For a config-only edit, run:

```bash
./scripts/restart_logger.sh
```

Use `./scripts/rebuild_and_restart.sh` after source changes.

## Logs and compaction

Daily logs live at `logs/daily_log_YYYY-MM-DD.md` in a mode `700` directory with mode `600` files. Starting on 2026-08-27 in Europe/Zagreb, this canonical file uses `activitylogger-analysis-v2` as the only live Markdown format. The fixed local-day boundary prevents one daily file from mixing formats. Older daily logs and the completed comparison data under `logs/analysis_shadow/` stay unchanged.

V2 keeps the exact event records and intent digests while reducing timeline overhead. It uses stable event names, one context heading per change, reversible adjacent-repeat counts, focus and idle transitions, session markers, and hourly continuity markers. Local Python code generates it. It does not call an LLM or a network service.

Each v2 flush first publishes a private pending transaction, then writes and verifies the canonical Markdown and integrity journal. The pending transaction is removed after exact parity passes. The first next-day heartbeat publishes a payload-free `.daily_log_YYYY-MM-DD.ready.json` proof. ContextAggregator requires this proof before it can upload a v2 day.

To check strict parsing, intent parity, invalid-marker state, and payload-free event counts during an active day, run:

```bash
.venv/bin/python scripts/check_analysis_day.py --day YYYY-MM-DD
```

This integrity check selects the historical shadow source before the cutover and the canonical daily log after the cutover. It does not assert that the day is complete or that heartbeat coverage is sufficient. It does not print headings or payloads.

After one complete calendar day, run the payload-free gate:

```bash
.venv/bin/python scripts/review_analysis_trial.py --day YYYY-MM-DD
```

The rollout used this gate and an independent review before the cutover. It remains available for completed comparison days.

To create a smaller local review view for one completed analysis day, run the explicit day-scoped exporter:

```bash
.venv/bin/python scripts/export_compact_analysis.py --day YYYY-MM-DD
```

It writes `private_analysis_review/compact_analysis_YYYY-MM-DD.md` with private permissions. This directory is outside `logs/`, and the filename does not match ContextAggregator's daily-log discovery pattern. The original dated analysis file and its intent journal remain authoritative. The exporter verifies their exact agreement and verifies that the compact view reconstructs the same records. It does not assert that the day has enough heartbeat coverage for cutover. Run the payload-free gate separately for that decision.

The compact view is local plaintext restructuring. It does not redact payloads, call an LLM, or use the network. Manually review and redact it before any external use.

For a smaller, task-focused v3 pilot, run:

```bash
.venv/bin/python scripts/export_workload_v3_pilot.py --day YYYY-MM-DD
```

It writes `private_analysis_review/v3_pilot_YYYY-MM-DD.md`. The exporter accepts only a completed canonical v2 day with a valid ready proof. It keeps typed text, clipboard, screen, URL, scroll, and generic event evidence exactly. It groups clicks by target within short work spans and summarizes focus, heartbeat, privacy, idle, and session markers. Hourly focus-context buckets keep passive reading and review work visible. The file includes source hashes, exact event accounting, and an explicit loss ledger.

This pilot is intentionally lossy and is not a replacement for v2. It uses private atomic output outside `logs/`, does not match the daily-log upload filename, does not call an LLM, and does not use the network. V2 and its intent journal remain the only authority. Review at least three completed days before deciding if a later format should change live logging.

The old compactor remains available for legacy logs:

```bash
.venv/bin/python compact_markdown_log.py logs/daily_log_YYYY-MM-DD.md
```

It writes a mode `600` result atomically. It rejects analysis-format logs because v2 is already compact. Oversized legacy sections pass through unchanged after a warning so memory stays bounded and content is not silently lost. Manually review and redact every result before sending it to an external LLM. Prefer local processing and keep FileVault enabled. Archive or delete old logs only through an operator-managed, verified workflow.

To review completed legacy days in the new analysis shape, run:

```bash
.venv/bin/python historical_analysis.py
```

This local program converts every completed legacy day into `private_historical_review/`. It skips declared analysis-format canonical logs and never changes any source log. The private output directory is outside `logs/`, and its filenames do not match ContextAggregator's `daily_log_YYYY-MM-DD.md` discovery rule. The converter requires separate input and output trees. It marks timestamps as legacy section-seal times, infers only stable event wrappers and section boundaries, preserves ambiguous content as exact text, and verifies that every generated file parses back to its projected records. This is a content-preserving projection, not a byte-for-byte reconstruction of source structure. The old format did not retain true event times or unambiguous event boundaries, so the unchanged daily logs remain the raw reference. Review `conversion_summary.json` for payload-free size, repeat, inference, and DST metrics. Do not trust a run while `conversion_incomplete.json` exists. Deleted source days are reported as orphaned outputs and are never deleted automatically.

## Current verification

The 2026-08-21 signing import, leaf continuity, canonical rebuild, strict deployed verification, bundle identifier, exact Apple Events-only entitlement, Automation purpose metadata, safe tamper rejection, load containment, and private modes were verified. Pinned leaf is `0a609d91ba3541a2b9589363974fa460be0f091c`.

The 2026-08-23 version 4.2.0 soak build passed all 357 tests. Ruff critical rules, dependency consistency, strict dependency audit, byte compilation, diff checks, and forbidden-dash scans passed. CI is pinned to `macos-15`.

The mandatory rebuild passed staged construction, signing, old-app prevalidation, atomic promotion, Launch Agent bootstrap, and fresh-process health proof. The legacy log, analysis Markdown, and intent journal updated together after restart. Every live intent count and digest matched the analysis records, and no invalid marker existed.
