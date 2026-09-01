# macOS TCC, signing, launchd, and ActivityLogger

This is the canonical production and recovery guide for ActivityLogger on modern macOS.

## Required runtime chain

```text
launchd -> start_logger.sh -> open -W -> dist/ActivityLoggerNative.app
```

Do not launch `python3 interleaved_logger.py` from launchd. An interactive Terminal grant does not transfer to a Launch Agent, and modern macOS associates TCC authorization with a stable app code requirement.

| Component | Required value |
|---|---|
| Bundle | `dist/ActivityLoggerNative.app` |
| Bundle identifier | `com.mk.activitylogger.native` |
| Launch Agent | `com.mk.activitylogger` |
| Signing store | `.codesign/activitylogger-signing.keychain-db` |
| Certificate pin | `.codesign/leaf.sha1` |
| TCC grants | Accessibility and Input Monitoring |
| Canonical build | `./scripts/rebuild_and_restart.sh` |

## Exact build environment

Use Python 3.11.9 from [`.python-version`](../.python-version) and the project-local `.venv`:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/ruff check --select E4,E7,E9,F .
.venv/bin/python -m pip_audit --strict
.venv/bin/python -m pytest -q
```

`requirements.txt` is the hash-locked macOS Apple silicon environment. Regenerate it only with `./scripts/compile_requirements.sh`.

## One-time migration from the legacy PKCS#12

Provision before rebuilding. The currently deployed app must still exist so the setup can compare its certificate leaf with the imported identity:

```bash
chmod 600 .codesign/identity.p12
./scripts/setup_signing_identity.sh --import-p12 .codesign/identity.p12
```

The `security` command presents native SecurityAgent prompts for the new keychain and PKCS#12 passwords. Do not place either password in a command, environment variable, log, or shell history. The scripts reject `ACTIVITYLOGGER_KEYCHAIN_PASSWORD` and `ACTIVITYLOGGER_P12_PASS`.

Successful provisioning:

1. Creates a dedicated private keychain.
2. Imports the private key as nonextractable and restricts it to signing use.
3. Derives exactly one usable code-signing identity.
4. Compares its leaf SHA-1 fingerprint with the deployed app.
5. Writes the verified fingerprint to `.codesign/leaf.sha1` with mode `600`.

Provisioning refuses an existing keychain or pin instead of replacing it. It also refuses a leaf mismatch. Use `--rotate-identity` only for a deliberate identity rotation. The warning is literal: existing TCC grants will not follow the new leaf.

The migration, canonical rebuild, exact verification, stable restart, and typing smoke test succeeded on 2026-08-21. `.codesign/identity.p12` and any redundant login-keychain identity remain private with mode `600` pending an explicit operator archive or irreversible deletion decision. They are recovery assets, not runtime blockers. Never retire the only recovery copy casually.

## Canonical staged rebuild

```bash
./scripts/rebuild_and_restart.sh
```

The script refuses a missing or wrong-version `.venv`. It then:

1. Builds `ActivityLoggerNative.spec` into a private temporary staging directory as a PyInstaller onedir app.
2. Signs every nested Mach-O and the outer bundle inside-out with the pinned identity. The outer bundle has exactly the Apple Events entitlement.
3. Verifies strict nested and outer integrity, the exact bundle identifier, designated requirement and pinned leaf, the entitlement allowlist, symlink containment, and Mach-O dependency and run-path containment.
4. Prevalidates the installed bundle for rollback and validates the installed Launch Agent plist.
5. Boots out the Launch Agent, snapshots exact deployed-executable PIDs before and after bootout, and terminates only revalidated residual processes using TERM and bounded KILL escalation. It never uses an application-name-only kill.
6. Promotes the staged app atomically, bootstraps the Launch Agent through `start_logger.sh` -> `open -W`, and requires a fresh exact-path native PID plus a separate stability observation.
7. On failed proof, keeps the service quiesced, restores and verifies the unchanged previous bundle, bootstraps it, and requires a fresh previous-app PID. The rebuild still exits nonzero after a successful rollback.

Normal builds cannot create or rotate an identity. Never leave an ad-hoc-signed or unverified app in `dist`.

Hardened Runtime is intentionally not enabled. The retained local CA:FALSE self-signed leaf has no Team ID and preserves the existing designated-requirement identity, but macOS rejected its certificate chain when Hardened Runtime was applied. The accepted compensating controls are exact pinned signing of all nested and outer code, strict signature checks, the one-key entitlement allowlist, explicit rejection of `disable-library-validation` and other dangerous code-signing entitlements, bundle symlink containment, and Mach-O load-path containment.

## Install the Launch Agent

Generate or reconcile the machine-specific plist from the committed template, then use the verified restart path:

```bash
./scripts/install_launch_agent.sh
./scripts/restart_logger.sh
```

The shared validator requires a mode `600` regular plist owned by the current user, the exact label and wrapper path, boolean `KeepAlive=true`, boolean `RunAtLoad=true`, and integer `Umask=63`. Do not replace this sequence with manual launchctl commands.

Do not add the same app as a Login Item. The stable per-user instance lock also prevents concurrent logger processes.

## TCC grants and smoke test

After the first certificate-signed build:

1. Add `dist/ActivityLoggerNative.app` under System Settings -> Privacy & Security -> Accessibility.
2. Add the same app under Input Monitoring.
3. Type outside a secure field.
4. Confirm `logs/daily_log_*.md` updates within about 30 seconds.

An unchanged pinned leaf should preserve the code requirement across rebuilds. The same leaf should not need TCC refresh. Do not ask for a TCC re-grant after a successful rebuild with the same identity.

Base capture does not require Screen Recording. Browser URL capture is off by default. When enabled, a browser may trigger a native Automation prompt for Apple Events. Approve only the browsers the operator intends to capture.

## Review Center and manual privacy control

The signed app is a menu-bar style background app without a Dock icon. Normal Launch Agent startup keeps its Review Center hidden. Open `dist/ActivityLoggerNative.app` in Finder while it is already running to show the window. ActivityLogger creates private review files, but it does not analyze them or send them anywhere.

Use the Review Center in three steps:

1. Choose an end date and either 5 or 7 completed calendar days. Select **Create review files**.
2. Select **Show review files in Finder** and start with `REVIEW_PROMPT.md`. Prefer a trusted local tool. Review and redact private text before using any online tool.
3. Record what happened and save the result locally.

Capture stays paused while the Review Center is visible. Closing or minimizing the window resumes capture unless manual pause, a secure app, or a secure field still requires a pause.

The Review Center uses the same local control functions as these commands:

```bash
.venv/bin/python scripts/activityloggerctl.py health
.venv/bin/python scripts/activityloggerctl.py storage
.venv/bin/python scripts/activityloggerctl.py pause
.venv/bin/python scripts/activityloggerctl.py resume
```

Manual pause stops every capture channel through the shared privacy gate. Manual resume clears only the manual pause and never clears a secure-app or secure-field pause. A paused clipboard change is consumed and is not written later. The manual state is stored with private permissions and survives a restart. An unreadable existing state keeps capture paused.

The Review Center and command output do not show captured payloads. Weekly packs are stored under `~/Library/Application Support/ActivityLogger/private_analysis_review/`. They are private plaintext and may contain captured text. Review and redact them before any external use.

## Config trust and privacy defaults

Create the optional config with private permissions:

```bash
mkdir -p ~/.config/activitylogger
cp config.example.toml ~/.config/activitylogger/config.toml
chmod 700 ~/.config/activitylogger
chmod 600 ~/.config/activitylogger/config.toml
```

Config loads once at startup. The loader rejects symlinks, unsafe ownership or permissions, malformed values, non-finite numbers, and values beyond bounded resource limits.

Privacy-sensitive defaults:

- `features.browser_url_capture = false`
- `privacy.unsafe_full_browser_urls = false`
- `window_titles.activitywatch_enricher = false`
- `window_titles.activitywatch_allow_remote = false`

Safe browser URL mode always removes user information and fragments and neutralizes the full query string before length capping. Unsafe full-URL mode remains an explicit warning-bearing opt-in, but still removes user information and fragments. ActivityWatch accepts loopback endpoints unless remote access is explicitly enabled with a warning.

For a config-only change:

```bash
./scripts/restart_logger.sh
```

The restart wrapper validates the plist, boots out the Launch Agent, snapshots exact executable-path PIDs before and after bootout, terminates only revalidated residual processes with bounded escalation, bootstraps the Launch Agent, and requires a fresh exact-path PID plus a separate stability observation. A failed config restart performs one bounded recovery cycle for the unchanged app and still exits nonzero. Use the canonical rebuild only after binary or source changes.

## Private data and retention

Daily logs and compacted outputs are mode `600`; their directories are mode `700`. They remain plaintext and are retained indefinitely until the operator archives or deletes them. Keep FileVault enabled and avoid shared backups.

`compact_markdown_log.py` restructures plaintext. It does not sanitize or redact. Oversized sections pass through unchanged after a warning to preserve content with bounded memory. Review and redact every output before sending it to an external LLM. Prefer local analysis. There is no automatic deletion, so archival and deletion must be operator-managed and verified.

## Deployment verification state on 2026-08-21

The interactive setup imported `.codesign/identity.p12` nonextractably into `.codesign/activitylogger-signing.keychain-db`. Pinned leaf `0a609d91ba3541a2b9589363974fa460be0f091c` matches both the prior and deployed designated requirement. Staged construction, canonical rebuild, and strict deployed verification succeeded.

Strict external verification confirms bundle identifier `com.mk.activitylogger.native`, authority `ActivityLogger Code Signing`, the exact pinned leaf, the sole Apple Events entitlement, no Hardened Runtime, no `disable-library-validation`, and `NSAppleEventsUsageDescription`. Nested code, symlink containment, and load paths passed. A safely isolated tampered copy was rejected. The installed plist and logs are mode `600`.

The final source suite passed all 335 tests. The strict deployed codesign test passed separately after the final rebuild and is not added again to that count. Ruff critical rules, dependency consistency, strict dependency audit, shell syntax, plist validation, byte compilation, diff checks, and forbidden-dash scans passed. CI remains pinned to `macos-15`.

The final native PID `88019` started at 12:57:05 CEST from the exact deployed executable and remained stable. Launch Agent wrapper PID `85208` was running with one run and no prior exit. Diagnostics recorded the expected privacy-neutral SIGTERM at 12:56:46 CEST for the replaced process and successful native context plus listener initialization for the final process. A real typing smoke grew the mode `600` daily log to 112,535 bytes at 12:57:44 CEST. A bounded 12:56:40 through 12:58:00 security-log query found no kill, deny-mmap, or library-validation enforcement.

The installed Launch Agent was reconciled through `install_launch_agent.sh` and `restart_logger.sh`; it now enforces `KeepAlive=true`, `RunAtLoad=true`, and `Umask=63`. The legacy PKCS#12 and any redundant login-keychain identity remain mode `600` pending explicit operator disposition. That recovery-asset decision is the only open operational item and does not block capture.

## Anti-patterns

- Do not launch Python directly from launchd.
- Do not sign ad hoc or bypass the canonical rebuild.
- Do not create or rotate an identity during a normal build.
- Do not use password environment variables.
- Do not use `--rotate-identity` merely to bypass continuity failure.
- Do not grant only Terminal, Python, or `/usr/bin/python3` for production capture.
- Do not execute `Contents/MacOS/ActivityLoggerNative` directly from the plist.
- Do not run a Login Item and Launch Agent together.
- Do not manually kickstart or reconstruct the installed plist. Use `install_launch_agent.sh` followed by `restart_logger.sh`.
- Do not claim a future deployment passed until its migration, verification, restart, and smoke tests complete.

For interactive diagnosis only, `.venv/bin/python interleaved_logger.py` uses Terminal's TCC context and is not the production path.
