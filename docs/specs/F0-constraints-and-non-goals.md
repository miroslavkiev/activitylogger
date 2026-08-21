# F0 cross-cutting constraints and non-goals

**Status:** implemented, source-verified, and regression-tested on 2026-08-21.

## Required invariants

### Runtime identity

- Production runs only as `dist/ActivityLoggerNative.app` through `start_logger.sh` -> `open -W`.
- Normal builds use the pre-provisioned, pinned certificate identity. Identity creation and rotation are separate operator actions.
- The app must be a staged onedir build signed with the pinned local identity and sole Apple Events entitlement. Hardened Runtime is intentionally not enabled for the retained self-signed no-Team-ID leaf. Verification must cover nested and outer integrity, bundle identifier, designated requirement, exact pinned leaf, entitlement allowlist, symlink containment, and Mach-O load paths.
- A failed build, signature verification, promotion, or fresh-process proof must leave or restore the unchanged previous verified app. The Launch Agent must be booted out and quiesced before promotion; process termination must target only revalidated exact executable paths, never application names; restart must bootstrap and prove a fresh stable native PID.

### Privacy

- Secure-app and secure-field states pause all capture channels.
- Unknown app or Accessibility privacy state is unsafe and fails closed.
- Key capture must make a synchronous privacy decision. Cached state may optimize but never authorize when stale or unknown.
- Asynchronous browser, click, and Accessibility results carry generation and context guards and are discarded after a privacy or window transition.
- A pause edge discards in-flight keys, modifiers, scroll bursts, and pending click work.
- Clipboard state observed during a pause must not be logged after resume.

### Data and resources

- Markdown is the only user-facing capture artifact.
- Runtime and tools create private, user-owned regular files and directories and refuse unsafe links or ownership.
- Buffers, queues, scans, diagnostics, config values, and retry loops are bounded.
- Source timestamps do not decide deployment validity. The signed bundle verifier and smoke test do.
- Logs have indefinite retention until operator-managed archival or deletion. Automatic deletion is out of scope.

### Lifecycle

- One stable per-user lock prevents concurrent logger instances.
- Fatal worker or listener exit stops the process and returns failure.
- SIGTERM and SIGINT coordinate worker and listener shutdown and perform a final flush.
- Persistence failure is visible, retries with bounded backoff, and preserves only bounded uncommitted data.

## Non-goals

- Screenshots, Screen Recording, OCR, camera, microphone, audio, or video
- Mouse-move trails
- JSONL, SQLite, cloud storage, MCP service, or remote collector
- Browser extension capture or helper daemon
- Cleaner-side sanitization or secret redaction
- Automatic deletion or retention policy enforcement
- Hot config reload
- Remote ActivityWatch by default
- Browser URL capture by default

## Operational constraints

Use exact Python 3.11.9 in `.venv` with the hash lock. Provision the signing keychain interactively before the first canonical rebuild. Do not pass signing secrets in environment variables. Keep recovery identities private until an explicit operator archive or irreversible deletion decision.

## Regression evidence

The final source gate passed all 335 tests. The strict deployed codesign test passed separately after the final rebuild. Identity import, pinned-leaf verification, staged construction, strict nested and outer verification, entitlement and load containment, Launch Agent reconciliation, exact native-process replacement, and a real post-restart typing smoke passed. The legacy PKCS#12 and any redundant login-keychain identity remain mode `600` pending explicit operator disposition; this is not a runtime blocker.
