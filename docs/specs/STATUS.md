# Specification status

**Closeout date:** 2026-08-21

| Specification | Current status |
|---|---|
| [`00-MASTER.md`](00-MASTER.md) | Current aggregate contract |
| [`F0-constraints-and-non-goals.md`](F0-constraints-and-non-goals.md) | Safety constraints implemented and tested |
| [`F1-window-titles.md`](F1-window-titles.md) | Native-first resolution and local-only ActivityWatch default implemented |
| [`F2-config.md`](F2-config.md) | Schema, trust validation, limits, and unsafe-option warnings implemented |
| [`F3-flush-model.md`](F3-flush-model.md) | Serialized transactional persistence, deadline timers, and lifecycle implemented |
| [`F4-browser-url.md`](F4-browser-url.md) | Opt-in capture and safe total query neutralization implemented |
| [`F5-capture-triggers.md`](F5-capture-triggers.md) | Closed triggers, injection hardening, and ordered click reservations implemented |
| [`F6-scroll-coalescing.md`](F6-scroll-coalescing.md) | Opt-in bounded burst and exact deadline behavior implemented |

## QA gate

- Three primary hardening loops and the final lifecycle, isolation, and Launch Agent loops completed with no remaining runtime or security source finding.
- All 335 source tests passed; the strict deployed codesign test passed separately after the final rebuild.
- Dependency consistency, lint, strict dependency audit, shell syntax, and plist validation passed.
- CI uses `macos-15`, Python 3.11.9, hashed installation, staged signing, exact verification, and tamper rejection.

## Live deployment gate

The interactive identity import, dedicated nonextractable keychain, pinned leaf continuity, staged bundle construction, strict deployed nested and outer verification, exact Apple Events-only entitlement, load containment, and safe tamper rejection passed. Pinned leaf is `0a609d91ba3541a2b9589363974fa460be0f091c`. Hardened Runtime is intentionally not enabled for the retained local self-signed no-Team-ID leaf.

The mandatory final rebuild succeeded. The installed Launch Agent is mode `600` with `KeepAlive=true`, `RunAtLoad=true`, and `Umask=63`. Exact native PID `88019` started at 12:57:05 CEST and remained stable; wrapper PID `85208` was running with one run and no prior exit. A real typing smoke grew the mode `600` daily log to 112,535 bytes at 12:57:44 CEST, and bounded post-rebuild security-log review found no kill, deny-mmap, or library-validation enforcement.

The legacy `.codesign/identity.p12` and any redundant login-keychain identity remain mode `600`. Archival or irreversible deletion requires explicit operator approval. This recovery-asset decision is not a runtime blocker.
