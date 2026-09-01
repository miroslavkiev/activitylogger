# Implementation status

**Verdict:** source, signed deployment, process replacement, and real capture smoke accepted.

| Area | Result | Operational note |
|---|---|---|
| Runtime privacy | Complete | Unknown state fails closed across keys, clicks, URLs, clipboard, and Accessibility work. |
| Buffers and persistence | Complete | Serialized grouped flush, bounded restoration, capture-date routing, and deadline waits. |
| Click ordering | Complete | Ordered reservations with generation, context, expiry, and persistence barriers. |
| Lifecycle | Complete | SIGTERM/SIGINT shutdown, worker supervision, listener health, final flush, nonzero fatal exit. |
| Config | Complete | Trusted-file checks, finite upper bounds, safe network defaults, warnings for unsafe opt-ins. |
| Browser URLs | Complete | Default off; safe user information and fragment removal plus total query neutralization. |
| Cleaner | Complete | Plaintext non-redacting compaction, atomic mode `600` output, bounded oversized-section pass-through. |
| Dependency and CI | Complete | Exact Python 3.11.9, hashed lock, `macos-15`, lint, audit, staged signing and tamper tests. |
| Signing source | Complete | Dedicated keychain, nonextractable import, deployed-leaf continuity, pin, explicit rotation warning, one-key entitlement allowlist. |
| Signed bundle mechanics | Complete | Pinned nested and outer signatures, exact requirement, entitlement and load containment, staged promotion, and tamper rejection passed. Hardened Runtime is intentionally not enabled for the retained local leaf. |
| Launch Agent lifecycle | Complete | Private canonical plist, bootout/quiesce, bootstrap, rollback or bounded config recovery, and fresh stable exact-PID proof. |
| Live runtime launch | Complete | Final exact native process remained stable and a real post-restart typing smoke updated the daily log. |
| Review Center | Source complete, deployment pending | Version 4.5.1 adds a guided three-step flow, direct Finder access to prepared files, plain-language privacy guidance, and local outcomes. Canonical rebuild and live checks are pending. |

## Verification

The final source gate passed all 335 tests. The strict deployed codesign test passed separately after the final rebuild.

The pinned leaf is `0a609d91ba3541a2b9589363974fa460be0f091c` and bundle identifier is `com.mk.activitylogger.native`. Exact Apple Events-only entitlement, Automation metadata, nested and outer signatures, load containment, safe tamper rejection, and private modes were externally verified. Final native PID `88019` started at 12:57:05 CEST, and the mode `600` daily log grew to 112,535 bytes at 12:57:44 CEST.

The legacy `.codesign/identity.p12` and any redundant login-keychain identity remain mode `600` because irreversible deletion requires explicit operator approval. They do not block runtime.

The previous 2026-09-01 version 4.5.0 gate passed 466 tests, lint, dependency consistency, and the strict dependency audit. The canonical rebuild verified and promoted the signed bundle with the unchanged pinned identity. Native PID `81216` started from the exact deployed path. Payload-free health confirmed v2 format, matching intent, no invalid marker, private modes, manual pause off, and capture active. Live pause and resume both confirmed, the strict deployed signature test passed, and the daily v2 log continued to update safely.

Version 4.5.1 is prepared in source. Its canonical rebuild and live Review Center verification are pending.
