# ActivityLogger comprehensive application review and closeout

Date: 2026-08-21

Historical evidence note: This report records commit `ab4ccbe`, ActivityLogger 4.1.0. Its relative source links and line numbers match that commit and may not point to the same code on current HEAD. Keep the report as closeout evidence. See [`specs/IMPL-STATUS.md`](specs/IMPL-STATUS.md) for current acceptance status.

Scope: capture runtime, privacy controls, persistence, configuration, browser integration, Markdown compaction, macOS launch and signing, dependencies, CI, tests, performance, data handling, and documentation.

## Executive outcome

The original read-only audit identified 28 findings: 8 P1, 12 P2, and 8 P3. The implementation, three primary QA loops, and the final lifecycle, isolation, and Launch Agent acceptance loops cleared every runtime and security finding without changing the single-process product architecture.

Source, signed deployment, process replacement, and live capture are accepted. The final source suite passed all 335 tests, and the strict deployed codesign test passed separately after the final rebuild.

The interactive setup imported the legacy identity nonextractably into the dedicated keychain. Pinned leaf `0a609d91ba3541a2b9589363974fa460be0f091c` matches the prior and deployed designated requirement. Staged construction, strict nested and outer verification, bundle identifier, exact Apple Events-only entitlement, Automation purpose metadata, safe tamper rejection, load containment, and private file modes passed. Hardened Runtime is intentionally not enabled for this retained local self-signed no-Team-ID leaf after macOS rejected its chain under that policy.

The mandatory final rebuild succeeded through the new bootout/bootstrap lifecycle. Final exact native PID `88019` started at 12:57:05 CEST and remained stable with Launch Agent wrapper PID `85208` running. A real typing smoke grew the private daily log to 112,535 bytes at 12:57:44 CEST. Bounded security-log review found no kill, deny-mmap, or library-validation enforcement for the final process.

The original audit evidence is preserved below by finding ID, affected source area, and condition. Each entry adds current source evidence, regression evidence, the narrowed product decision where relevant, and any remaining operational work.

## Review boundaries

- Runtime log contents were not inspected.
- No external capture or upload service was introduced.
- Logs remain private plaintext with indefinite retention.
- The compactor remains a non-redacting plaintext transformer.
- Live signing prompts, TCC-sensitive bundle deployment, exact-process replacement, Launch Agent reconciliation, and real typing smoke were completed by the root operator.

## Resolution status

| Code | Meaning |
|---|---|
| Resolved | Source behavior and regression coverage complete |
| Resolved, bounded | Source fixed with an explicit, documented product boundary |
| Resolved, deployed | Source, regression, signing, live process, and capture-smoke evidence complete |

## Resolution matrix for all 28 findings

| ID | Original audit condition and evidence | Resolution and current evidence | Status |
|---|---|---|---|
| P1-01 | Secure-app and secure-field detection could be stale, queued, or unknown when a key was admitted. Original areas: key callback, focus refresh, AX queue. | Unknown now fails closed. Key admission performs synchronous app and focus checks; focus refresh is serialized; pause and async work use generations. See [`interleaved_logger.py:302`](../interleaved_logger.py#L302), [`interleaved_logger.py:455`](../interleaved_logger.py#L455), [`interleaved_logger.py:1162`](../interleaved_logger.py#L1162), and [`interleaved_logger.py:1214`](../interleaved_logger.py#L1214). Tests: [`tests/test_runtime_privacy.py:19`](../tests/test_runtime_privacy.py#L19), [`tests/test_runtime_privacy.py:30`](../tests/test_runtime_privacy.py#L30), [`tests/test_runtime_privacy.py:56`](../tests/test_runtime_privacy.py#L56), [`tests/test_runtime_privacy.py:93`](../tests/test_runtime_privacy.py#L93). | Resolved |
| P1-02 | Mixed-case secure-app tokens did not match and blank entries matched everything. Original areas: config merge and secure matcher. | Tokens are stripped and casefolded, blank entries are rejected, and an explicit empty list remains valid. See [`config.py:376`](../config.py#L376) and [`interleaved_logger.py:346`](../interleaved_logger.py#L346). Test: [`tests/test_config.py:190`](../tests/test_config.py#L190). | Resolved |
| P1-03 | Exceptions after section detachment could lose data and kill persistence; repeated failure could grow memory. Original areas: flush transaction and writer loop. | Flush is serialized, exception-safe, grouped by capture date, and restores only bounded uncommitted data. Writer failure remains supervised and retries with capped backoff. See [`interleaved_logger.py:1814`](../interleaved_logger.py#L1814), [`interleaved_logger.py:1866`](../interleaved_logger.py#L1866), and [`interleaved_logger.py:1934`](../interleaved_logger.py#L1934). Tests: [`tests/test_persistence_lifecycle.py:27`](../tests/test_persistence_lifecycle.py#L27), [`tests/test_persistence_lifecycle.py:36`](../tests/test_persistence_lifecycle.py#L36), [`tests/test_persistence_lifecycle.py:102`](../tests/test_persistence_lifecycle.py#L102), [`tests/test_persistence_lifecycle.py:118`](../tests/test_persistence_lifecycle.py#L118). | Resolved |
| P1-04 | SIGTERM, listener exit, worker failure, and exceptions did not share an orderly nonzero shutdown with final persistence. | SIGTERM and SIGINT set one stop event, all waiters wake, workers and listeners are supervised and joined, final flush runs in `finally`, and fatal paths return nonzero. See [`interleaved_logger.py:1995`](../interleaved_logger.py#L1995) and [`interleaved_logger.py:2065`](../interleaved_logger.py#L2065). Tests include [`tests/test_runtime_privacy.py:653`](../tests/test_runtime_privacy.py#L653) and persistence lifecycle coverage. | Resolved |
| P1-05 | The shipped app and fallback build path used an obsolete, non-reproducible interpreter and advisory-bearing dependency set. | `.python-version` pins 3.11.9, rebuild requires `.venv`, install uses hashes, Requests is 2.33.0, pytest is 9.0.3, and lint and strict audit are canonical. The exact-runtime staged build and live launch succeeded. See [`.python-version`](../.python-version), [`scripts/rebuild_and_restart.sh:117`](../scripts/rebuild_and_restart.sh#L117), [`requirements.txt`](../requirements.txt), and [`tests/test_ops_smokes.py:105`](../tests/test_ops_smokes.py#L105). | Resolved, deployed |
| P1-06 | A decryptable legacy PKCS#12 and broad keychain ACL behavior exposed the TCC signing identity. | Setup imported the identity nonextractably into the dedicated keychain through native prompts, pinned exactly one matching leaf, and preserved deployed identity continuity. See [`scripts/setup_signing_identity.sh:105`](../scripts/setup_signing_identity.sh#L105), [`scripts/setup_signing_identity.sh:191`](../scripts/setup_signing_identity.sh#L191), and [`tests/test_ops_smokes.py:766`](../tests/test_ops_smokes.py#L766). The legacy PKCS#12 and any redundant login-keychain identity remain mode `600` because irreversible disposition requires explicit approval; neither blocks runtime. | Resolved, deployed |
| P1-07 | The signature gate checked metadata text rather than bundle integrity, exact identity, and identifier; build promotion lacked safe rollback. | Verification enforces nested and outer signatures, exact leaf and designated requirement, bundle ID, one-key entitlement allowlist, symlink containment, and Mach-O load-path containment. Build stages and verifies before promotion, prevalidates rollback, boots out and quiesces launchd, atomically promotes, bootstraps, and proves a fresh stable exact-path native PID. Failure restores the unchanged previous app and proves its fresh PID. The deployed verifier passed and a tampered copy failed safely. See [`scripts/lib/require_certificate_leaf.sh:224`](../scripts/lib/require_certificate_leaf.sh#L224), [`scripts/lib/require_certificate_leaf.sh:383`](../scripts/lib/require_certificate_leaf.sh#L383), [`scripts/rebuild_and_restart.sh:128`](../scripts/rebuild_and_restart.sh#L128), and [`scripts/lib/exact_process_lifecycle.sh:135`](../scripts/lib/exact_process_lifecycle.sh#L135). | Resolved, deployed |
| P1-08 | Accessibility tree limits were per node, with no global node, character, or elapsed-time budget, allowing worker starvation. | Runtime scans now have global node, character, child, depth, and 0.25 second bounds. Browser Accessibility lookup has its own node and time budgets. See [`interleaved_logger.py:1275`](../interleaved_logger.py#L1275) and [`browser_url.py:289`](../browser_url.py#L289). Tests: [`tests/test_runtime_privacy.py:521`](../tests/test_runtime_privacy.py#L521), [`tests/test_browser_url.py:293`](../tests/test_browser_url.py#L293), [`tests/test_browser_url.py:309`](../tests/test_browser_url.py#L309). | Resolved |
| P2-01 | A numeric sentinel suppressed the first Accessibility scan on an interpreter whose monotonic clock began near zero. | `None` represents never scanned, so the first scan is admitted. See state initialization in [`interleaved_logger.py:148`](../interleaved_logger.py#L148). Test: [`tests/test_runtime_privacy.py:514`](../tests/test_runtime_privacy.py#L514). | Resolved |
| P2-02 | Multiple callers could detach separately and race through header creation, append, and restore. | A dedicated flush lock serializes detach through commit or restoration. See [`interleaved_logger.py:1866`](../interleaved_logger.py#L1866). Test: [`tests/test_persistence_lifecycle.py:70`](../tests/test_persistence_lifecycle.py#L70). | Resolved |
| P2-03 | Non-finite numbers, conversion errors, unsafe config ownership, links, and writable modes could bypass intended trust. | Known numeric values require finite bounded values. Config opens with no-follow where available, verifies regular file and owner, and rejects unsafe write bits. See [`config.py:274`](../config.py#L274), [`config.py:469`](../config.py#L469), and [`config.py:569`](../config.py#L569). Tests: [`tests/test_config.py:357`](../tests/test_config.py#L357), [`tests/test_config.py:376`](../tests/test_config.py#L376), [`tests/test_config.py:395`](../tests/test_config.py#L395). | Resolved |
| P2-04 | Captured headings and fenced text could alter Markdown structure and inject instructions into later model analysis. | Inline metadata is sanitized, captured multiline text uses a dynamic safe fence, the parser requires an immediate generated timestamp and tracks fences, transforms do not cross fences, and the analysis prompt labels logs untrusted and requires human review. See [`markdown_format.py:56`](../markdown_format.py#L56), [`clean_markdown_log.py:684`](../clean_markdown_log.py#L684), and [`tests/test_markdown_compactor.py:18`](../tests/test_markdown_compactor.py#L18). Captured content can still contain hostile prose, so external use remains a manual trust decision. | Resolved, bounded |
| P2-05 | Deferred click enrichment could reverse chronology or describe a later UI context. | The callback reserves sequence, timestamp, heading, privacy generation, and context before queueing. Persistence stops at the first pending reservation. Mismatch, pause, failure, or expiry discards it. See [`interleaved_logger.py:1363`](../interleaved_logger.py#L1363), [`interleaved_logger.py:1392`](../interleaved_logger.py#L1392), and [`interleaved_logger.py:1425`](../interleaved_logger.py#L1425). Tests: [`tests/test_runtime_privacy.py:329`](../tests/test_runtime_privacy.py#L329), [`tests/test_persistence_lifecycle.py:136`](../tests/test_persistence_lifecycle.py#L136). | Resolved |
| P2-06 | Daily file selection used flush date instead of capture date. | Each section stores timezone-aware `captured_at`; flush groups sections by capture date. See [`interleaved_logger.py:703`](../interleaved_logger.py#L703), [`interleaved_logger.py:1839`](../interleaved_logger.py#L1839), and [`interleaved_logger.py:1866`](../interleaved_logger.py#L1866). Test: [`tests/test_persistence_lifecycle.py:53`](../tests/test_persistence_lifecycle.py#L53). | Resolved |
| P2-07 | Clipboard polling read unchanged text and retained the complete prior plaintext, including paused data. | Change count is checked first, only a SHA-256 digest is retained, paused transitions are absorbed by generation, and initialization retries with bounded backoff. See [`interleaved_logger.py:1605`](../interleaved_logger.py#L1605) and [`interleaved_logger.py:1638`](../interleaved_logger.py#L1638). Tests: [`tests/test_runtime_privacy.py:329`](../tests/test_runtime_privacy.py#L329), [`tests/test_runtime_privacy.py:434`](../tests/test_runtime_privacy.py#L434), [`tests/test_runtime_privacy.py:538`](../tests/test_runtime_privacy.py#L538). | Resolved |
| P2-08 | The cleaner retained whole files and transformed copies in memory and overwrote output directly. | Input and output stream through a mode `600` atomic replacement. Each section uses `SpooledTemporaryFile`. Full semantics apply through 1 MiB and 10,000 lines. Oversized sections pass through byte-for-byte after a warning, so content and fence structure are preserved with bounded memory. See [`clean_markdown_log.py:86`](../clean_markdown_log.py#L86), [`clean_markdown_log.py:665`](../clean_markdown_log.py#L665), and [`clean_markdown_log.py:811`](../clean_markdown_log.py#L811). The 20 MiB regression peaked at 21,004,288 bytes RSS and preserved the SHA-256 digest. Test: [`tests/test_markdown_compactor.py:135`](../tests/test_markdown_compactor.py#L135). | Resolved, bounded |
| P2-09 | Optional URL lookup could retry expensive Accessibility and Apple Events paths every window poll and retained secret-bearing query and fragment data. | Per-source and per-app backoff bounds retry cost. Safe normalization removes user information and fragments and neutralizes every query name and value. Unsafe full mode is explicit, warning-bearing, and still removes user information and fragment. See [`browser_url.py:45`](../browser_url.py#L45), [`browser_url.py:102`](../browser_url.py#L102), and [`config.py:557`](../config.py#L557). Tests: [`tests/test_browser_url.py:153`](../tests/test_browser_url.py#L153), [`tests/test_browser_url.py:180`](../tests/test_browser_url.py#L180), [`tests/test_browser_url.py:263`](../tests/test_browser_url.py#L263). | Resolved, bounded |
| P2-10 | Apple Events support lacked the required purpose metadata and the app lacked Hardened Runtime. | The deployed bundle declares `NSAppleEventsUsageDescription` and has exactly the Apple Events entitlement. Hardened Runtime was implemented and tested, then deliberately removed because macOS rejected the preserved local self-signed no-Team-ID leaf under that policy. Compensating controls enforce pinned nested and outer signatures, exact requirements, the sole entitlement, rejection of `disable-library-validation` and other dangerous entitlements, symlink containment, and Mach-O load-path containment. See [`ActivityLoggerNative.spec:56`](../ActivityLoggerNative.spec#L56), [`ActivityLoggerNative.entitlements`](../ActivityLoggerNative.entitlements), [`scripts/sign_app.sh:98`](../scripts/sign_app.sh#L98), and [`scripts/lib/require_certificate_leaf.sh:8`](../scripts/lib/require_certificate_leaf.sh#L8). Tests: [`tests/test_ops_smokes.py:105`](../tests/test_ops_smokes.py#L105) and [`tests/test_signing_hardening.py:21`](../tests/test_signing_hardening.py#L21). | Resolved, bounded and deployed |
| P2-11 | Sensitive files could be mode `644`, the cleaner name implied safety, and retention risk was undocumented. | Runtime uses umask `077`; generated logs, diagnostics, locks, and compacted outputs use `600`; and created private directories use `700`. Existing readable config warns and the documented operator mode is `600`. The preferred CLI is `compact_markdown_log.py`, and every run warns that output is sensitive plaintext and not redacted. Indefinite retention is an explicit product decision with FileVault and operator-managed archive/delete guidance. See [`interleaved_logger.py:1788`](../interleaved_logger.py#L1788), [`clean_markdown_log.py:811`](../clean_markdown_log.py#L811), and [`README.md`](../README.md). No automatic deletion was added. | Resolved, bounded |
| P2-12 | Typing and scroll idle workers woke at a constant rate while idle. | Stateful events wake workers only when a buffer opens, changes, stops, or reaches its exact deadline. See [`interleaved_logger.py:1003`](../interleaved_logger.py#L1003) and [`interleaved_logger.py:1714`](../interleaved_logger.py#L1714). Test: [`tests/test_runtime_privacy.py:548`](../tests/test_runtime_privacy.py#L548). | Resolved |
| P3-01 | Left and right physical modifiers shared one logical set entry, so one release cleared the other. | Physical keys and per-logical reference counts preserve the modifier until all matching physical keys release. See [`interleaved_logger.py:1187`](../interleaved_logger.py#L1187). Test: [`tests/test_runtime_privacy.py:310`](../tests/test_runtime_privacy.py#L310). | Resolved |
| P3-02 | Scroll-created sections bypassed the section cap. | Scroll seal checks buffer caps and requests persistence outside the state lock. See [`interleaved_logger.py:931`](../interleaved_logger.py#L931). Test: [`tests/test_runtime_privacy.py:642`](../tests/test_runtime_privacy.py#L642). | Resolved |
| P3-03 | One pasteboard initialization error ended clipboard capture for the process lifetime. | Initialization diagnoses and retries with exponential backoff capped at 60 seconds, interruptible by shutdown. See [`interleaved_logger.py:1638`](../interleaved_logger.py#L1638). | Resolved |
| P3-04 | Ordinary Python tracebacks with indented source lines were not compacted. | Traceback gathering accepts standard source and caret continuation lines while respecting structural boundaries. See [`clean_markdown_log.py:450`](../clean_markdown_log.py#L450). Test: [`tests/test_markdown_compactor.py:71`](../tests/test_markdown_compactor.py#L71). | Resolved |
| P3-05 | Repetition summaries overstated repeat count and generic transforms changed fenced content. | Repeat markers count omitted copies, parser and transforms track fences, and generic deduplication remains outside captured blocks. Tests: [`tests/test_markdown_compactor.py:46`](../tests/test_markdown_compactor.py#L46), [`tests/test_markdown_compactor.py:61`](../tests/test_markdown_compactor.py#L61). | Resolved |
| P3-06 | Launch Agent generation used fragile text substitution and wrote directly without validation. | `plistlib` renders XML safely to a temporary mode `600` file, validates it, and replaces atomically. See [`scripts/render_launch_agent.py:26`](../scripts/render_launch_agent.py#L26) and [`tests/test_ops_smokes.py:84`](../tests/test_ops_smokes.py#L84). | Resolved |
| P3-07 | ActivityWatch local-only behavior was a convention; redirects and environment proxies could contact remote hosts. | Config requires loopback by default, rejects user information, remote use requires an explicit warning-bearing opt-in, and the HTTP session disables proxy inheritance and redirects. See [`config.py:306`](../config.py#L306), [`interleaved_logger.py:519`](../interleaved_logger.py#L519), and [`tests/test_runtime_privacy.py:506`](../tests/test_runtime_privacy.py#L506). | Resolved, bounded |
| P3-08 | The instance lock lived under the configurable log directory, so two log paths allowed two global input listeners. | The lock now uses the stable per-user `~/Library/Application Support/ActivityLogger/activitylogger.lock`, validates ownership and type, and enforces private modes. See [`interleaved_logger.py:1962`](../interleaved_logger.py#L1962). Test: [`tests/test_persistence_lifecycle.py:233`](../tests/test_persistence_lifecycle.py#L233). | Resolved |

## QA and verification results

| Gate | Result |
|---|---|
| Final source test suite | 335 passed |
| Deployed signature verifier | Passed separately against the exact live bundle after the final rebuild |
| Dependency consistency | Passed |
| Ruff source check | Passed |
| Strict dependency audit | Passed |
| Shell syntax | Passed |
| Launch Agent plist validation | Passed |
| CI host | Pinned to `macos-15` |
| CI interpreter | Exact Python 3.11.9 |
| Dependency install | `--require-hashes` from `requirements.txt` |
| Cleaner large-section regression | 20 MiB exact pass-through, 21,004,288 bytes peak RSS, under 64 MiB gate |
| Live signature | Exact leaf, identifier, authority, Apple Events-only entitlement, no Hardened Runtime, no dangerous entitlement, and purpose string verified |
| Live process | Exact native PID `88019` started 12:57:05 CEST and remained stable; wrapper PID `85208` running |
| Live capture | Mode `600` daily log grew to 112,535 bytes by real typing at 12:57:44 CEST |
| Launch Agent | Mode `600`; `KeepAlive=true`, `RunAtLoad=true`, `Umask=63` |
| Negative signature case | Safely isolated tampered copy rejected |

The source suite and the deployed codesign rerun are reported separately to avoid double-counting. Live process and capture evidence supplement the signature result.

## Narrowed product decisions

### Privacy and URLs

Browser URL capture remains off by default. Safe mode intentionally neutralizes the entire query, including key names, instead of attempting a partial secret list. Unsafe mode is retained for operators who explicitly accept the risk, but user information and fragments are always removed.

ActivityWatch enrichment remains on by default because native results win and the endpoint is local-only by default. Remote enrichment exists only as an explicit warned opt-in.

### Markdown and external models

Captured data is untrusted. Structural escaping and fence-aware parsing reduce corruption and instruction confusion, but no parser can make arbitrary activity content trustworthy. The prompt now instructs the model not to follow log instructions and requires explicit human review before automation.

The compactor deliberately does not redact. Small sections keep the existing semantic transformations. A section exceeding 1 MiB or 10,000 lines is copied unchanged after a diagnostic. This bounded safe mode prioritizes content preservation, structural validity, and predictable memory over maximum compaction.

### Retention

No automatic deletion was introduced. ActivityLogger retains logs indefinitely because deletion policy is an operator decision. The repository now documents private modes, FileVault, careful backup handling, and operator-managed, verified archival or deletion. This is an accepted residual privacy exposure, not a sanitizer guarantee.

### Signing

Normal builds cannot create or rotate an identity. The one-time import uses native prompts and verifies deployed-leaf continuity. `--rotate-identity` remains available only for an intentional TCC-breaking rotation and prints that existing grants will not follow.

The new keychain, pin, canonical rebuild, deployed verification, exact-process replacement, and capture smoke succeeded. Hardened Runtime is intentionally disabled for the local self-signed no-Team-ID identity because macOS rejected that chain under Hardened Runtime. Strict nested and outer signing, entitlement allowlisting, dangerous-entitlement rejection, symlink containment, and load-path containment provide the accepted defense boundary. The legacy PKCS#12 and any redundant login-keychain identity remain mode `600` because irreversible disposition requires explicit operator approval.

## Test quality assessment

### Strengths

- Focused regressions reproduce the original privacy failures rather than checking source strings alone.
- Persistence tests cover exception restoration, partial date-group commit, concurrency, bounded retries, midnight routing, and pending-click barriers.
- Operations tests exercise staged rollback and restart recovery with isolated fake repositories.
- URL tests cover semantic normalization, privacy modes, node budgets, deadlines, backoff, and generation checks.
- Cleaner tests verify real subprocess peak RSS, byte-for-byte preservation, atomic failure behavior, modes, fences, and prompt trust instructions.
- CI builds and signs a staged app with an ephemeral CI identity and includes negative tamper cases.

### Remaining test boundaries

- Real macOS Accessibility, pasteboard, Automation consent, and TCC behavior cannot be fully simulated by unit tests.
- The deployed signed-app check can be deselected inside the restricted sandbox and passed separately after the final live rebuild.
- CI's ephemeral identity validates mechanics; the live external verifier separately established continuity with the operator's deployed leaf.
- Disk hardware failure, forced power loss, and OS-level TCC database corruption remain outside automated coverage.
- No coverage percentage threshold is imposed. The suite instead targets identified invariants and failure paths.

## Performance and resource assessment

The high-risk unbounded paths are now bounded:

- Runtime AX text scan: 1,000 global nodes, elapsed deadline, character cap, depth and per-node child cap.
- Browser AX URL scan: global node and elapsed budgets, followed by per-source/app backoff.
- AX work queue, keys, events, sections, diagnostics, and click expiry: configured or fixed caps.
- Typing, scroll, writer, shutdown, and pending-click timers: event-driven waits.
- Clipboard: change-count first and digest-only prior-value state.
- Compactor: section spool with a 256 KiB in-memory threshold and unchanged oversized-section mode.

The application remains an always-on Python process using macOS Accessibility and input listeners. Ongoing host energy and wakeup behavior can be observed operationally, but no source path found in the final QA loop requires another performance fix.

## Residual risks

1. Hardened Runtime is intentionally absent to preserve the local self-signed no-Team-ID identity. Strict signature, entitlement, symlink, and load-path checks narrow but do not equal an Apple-trusted Hardened Runtime chain.
2. The legacy PKCS#12 and any redundant login-keychain identity remain mode `600`. Their archive or irreversible deletion requires an explicit operator decision.
3. Activity logs are highly sensitive plaintext. Private modes and FileVault reduce exposure but do not protect against same-user compromise, authorized backup access, or deliberate external upload.
4. Unsafe full URL and remote ActivityWatch modes intentionally expand exposure when enabled.
5. A persistent storage failure can still force dropping the oldest bounded buffered sections. The logger diagnoses this instead of accepting unbounded memory growth.
6. Asynchronous click enrichment can be discarded under timeout or context churn. This preserves correctness and privacy at the cost of an omitted click.
7. Oversized compactor sections are not semantically reduced. The warning and exact pass-through are deliberate.
8. Self-signed local code identity remains an operator-managed trust asset. Host compromise with access to the unlocked signing context is outside the application threat model.

## Final deployment checklist

- [x] Confirmed exact Python 3.11.9, hashed dependencies, pip consistency, Ruff critical rules, and strict audit.
- [x] Passed all 335 source checks and the separate strict deployed codesign test after the final rebuild.
- [x] Confirmed the mode `600` legacy PKCS#12 and prior deployed app before migration.
- [x] Imported through native SecurityAgent prompts without password environment variables.
- [x] Confirmed one valid nonextractable identity in the dedicated keychain and private leaf pin.
- [x] Confirmed imported leaf `0a609d91ba3541a2b9589363974fa460be0f091c` matches the prior deployed app.
- [x] Completed the canonical staged rebuild and bootout/bootstrap handoff.
- [x] Verified nested and outer integrity, identifier, designated requirement, authority, pinned leaf, entitlement allowlist, symlink containment, and Mach-O load-path containment.
- [x] Recorded the intentional no-Hardened-Runtime policy for the local self-signed no-Team-ID leaf and verified that `disable-library-validation` is absent.
- [x] Verified minimal Apple Events entitlement and purpose metadata.
- [x] Reconciled the installed mode `600` plist to `KeepAlive=true`, `RunAtLoad=true`, and `Umask=63` through the canonical install and restart tools.
- [x] Confirmed final exact native PID `88019` started at 12:57:05 CEST and remained stable with wrapper PID `85208` running.
- [x] Confirmed a real typing smoke grew the mode `600` daily log to 112,535 bytes at 12:57:44 CEST.
- [x] Confirmed bounded security-log review found no kill, deny-mmap, or library-validation enforcement for the final process.
- [x] Verified secure-field behavior through deterministic QA without typing a live secret.
- [x] Confirmed safe URL behavior, private log and installed-plist modes, and tampered-copy rejection.
- [x] Recorded signing date, leaf, tests, and bundle verification in this report.
- [ ] Archive or delete the legacy PKCS#12 and any redundant login-keychain identity only after explicit operator approval. They remain mode `600` and do not block runtime.

## Final verdict

Source hardening, signed deployment, process replacement, and real capture are verified. All original 28 findings are resolved, live-deployed where applicable, or explicitly bounded. The only open operator item is disposition of the protected legacy PKCS#12 and any redundant login-keychain identity; it is not a runtime blocker.
