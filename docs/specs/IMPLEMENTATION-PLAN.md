# ActivityLogger implementation and deployment closeout

**Status:** source, signed deployment, lifecycle, and live capture closeout complete.

This plan supersedes the historical F0 through F6 build order. Current contracts live in [`00-MASTER.md`](00-MASTER.md) and the individual feature specifications.

## Completed source phases

1. Enforced fail-closed privacy across synchronous callbacks and asynchronous generation-guarded work.
2. Added bounded queues, buffers, Accessibility traversal, diagnostics, retry loops, and stateful deadline waits.
3. Serialized durable flush, grouped sections by capture date, restored only uncommitted writes, and added lifecycle supervision.
4. Reserved click sequence positions before asynchronous enrichment and blocked persistence at unresolved reservations.
5. Hardened config discovery, file trust, numeric limits, ActivityWatch network defaults, and unsafe-option warnings.
6. Changed safe browser URLs to remove user information and fragments and neutralize the complete query string.
7. Hardened Markdown structure and made compaction atomic, private, non-redacting, and bounded for oversized sections.
8. Pinned exact Python 3.11.9, the hash-locked dependency flow, `macos-15` CI, lint, strict audit, staged signing, and tamper rejection.
9. Separated one-time signing provisioning from normal builds, pinned the deployed leaf, and made identity rotation explicit and warning-bearing.
10. Narrowed the signing policy to the retained local identity without Hardened Runtime, with exact nested and outer signatures, a sole Apple Events entitlement, forbidden-entitlement checks, symlink containment, and Mach-O load-path containment.
11. Added the shared bootout/quiesce and bootstrap lifecycle, fresh stable native-PID proof, unchanged-bundle rollback, and bounded config-restart recovery.
12. Completed the final gate with all 335 source tests and a separate strict deployed codesign pass after the final rebuild.

## Maintainer verification flow

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/ruff check --select E4,E7,E9,F .
.venv/bin/python -m pip_audit --strict
.venv/bin/python -m pytest -q
```

Regenerate `requirements.txt` only with `./scripts/compile_requirements.sh` on the supported macOS Apple silicon environment.

## Production migration status

- [x] Confirmed `dist/ActivityLoggerNative.app` and the private mode `600` legacy PKCS#12.
- [x] Imported the identity with `./scripts/setup_signing_identity.sh --import-p12 .codesign/identity.p12` through native SecurityAgent prompts.
- [x] Confirmed the dedicated keychain, one valid identity, nonextractable private key, and leaf pin `0a609d91ba3541a2b9589363974fa460be0f091c` matching the prior deployed requirement.
- [x] Reconciled the installed mode `600` plist with `install_launch_agent.sh`, then restarted with `restart_logger.sh`; `KeepAlive=true`, `RunAtLoad=true`, and `Umask=63` are enforced.
- [x] Completed the canonical staged rebuild and bootout/bootstrap process handoff.
- [x] Verified strict nested and outer integrity, bundle identifier `com.mk.activitylogger.native`, exact designated requirement, pinned leaf, authority, one-key Automation entitlement, forbidden-entitlement rejection, symlink containment, and Mach-O load-path containment.
- [x] Confirmed intentional no-Hardened-Runtime signing for the local self-signed no-Team-ID leaf.
- [x] Confirmed final exact native PID `88019` started at 12:57:05 CEST and remained stable with Launch Agent wrapper PID `85208` running.
- [x] Confirmed a real typing smoke grew the mode `600` daily log to 112,535 bytes at 12:57:44 CEST.
- [x] Rejected a safely isolated tampered app copy.
- [x] Verified secure-field behavior through deterministic privacy QA without typing a live secret.
- [x] Verified mode `600` logs and installed plist.
- [ ] Archive or delete the legacy PKCS#12 and any redundant login-keychain identity only with explicit operator approval. They remain mode `600` and do not block runtime.

The build script creates a private staging directory, builds and signs an onedir bundle, prevalidates rollback and the installed plist, boots out and quiesces the Launch Agent, promotes atomically, bootstraps, and requires a fresh exact-path PID plus a separate stability observation. Failed proof keeps the service quiesced, restores the unchanged previous bundle, and requires a fresh previous-app PID while still returning failure.

## Data operations

Keep FileVault enabled. Daily logs and compacted files are private plaintext with indefinite retention. There is no automatic deletion. Review and redact compacted output before external LLM use. Archive and delete only through an operator-managed, verified procedure.

## Completion result

Source lifecycle and signed deployment verification are complete. The final source suite passed all 335 tests, and the strict deployed codesign test passed separately after the final rebuild. Ruff critical rules, dependency consistency, strict dependency audit, shell and plist validation, byte compilation, diff checks, and forbidden-dash scans passed.

Production runtime closeout passed: the rebuilt and config-restarted exact-path native processes were proved fresh and stable, the Launch Agent is running with the corrected policy, and the daily log updated after real typing. Bounded security-log review found no enforcement event for the final process.

The unchecked recovery-identity disposition is an explicit operator decision and is not a deployment gate.
