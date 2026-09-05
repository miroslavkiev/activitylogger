# ActivityLogger audit remediation

The operator approved all 16 audit fixes and selected Option C: a native Daily status tab and a Weekly review tab. The weekly tab keeps the existing three-step flow. This document tracks implementation and verification; it does not change the authority of older logs or dated audit evidence.

## Implementation plan

1. Fix fresh capture admission, context attribution, the disk deadline, retained data during storage failure and missed-day readiness. Preserve accepted data and transaction ownership.
2. Share private file reads and one payload-free day inspection per status request. Keep fresh checks at export. Repair runtime status, temporary-file cleanup, CLI defaults and safe errors.
3. Add the two native tabs, exact review-window identity, safe drafts, quality warnings, saved-result access and local recovery help. Reuse AppKit controls and the current worker.
4. Add focused regressions, run the canonical gates, conduct separate code and UX reviews, then build and verify the signed local app. Check runtime state before restarting. Update this document with actual results.

The shared reader uses nonblocking, no-follow file opens and checks ownership, private permissions, link count, size and stable identity. Existing publication rules stay separate. No new dependency or capture service is required.

The shared day result contains counts, dates and safe status codes, never captured payload. A status request may cache that result only for its own log directory and date cutoff. Export validates its sources again before publication. Missing, invalid and unsupported dates remain distinct.

Storage failure must stop admission of new events while retaining already accepted events in memory. It must not use the privacy-pause buffer discard, silently trim data, exit or restart the app to recover. Retry timing must apply to direct cap-triggered flushes as well as the writer thread.

## Finding checklist

| ID | Required change | Status |
|---|---|---|
| F01 | Fresh secure-app/context admission for queued text scans | Implemented; release validation below |
| F02 | Absolute monotonic flush deadline across wakeups | Implemented; release validation below |
| F03 | Bounded new admission and retries after storage failure, retained accepted data | Implemented; release validation below |
| F04 | Attribute input to its freshly verified context | Implemented; release validation below |
| F05 | Reconcile existing completed days after a multi-day absence | Implemented; release validation below |
| F06 | Validate runtime identity and preserve unknown privacy status | Implemented; release validation below |
| F07 | Shared readiness rejects invalid markers | Implemented; release validation below |
| F08 | Clean failed state writes and bound retry timing | Implemented; release validation below |
| F09 | Parse CLI arguments before loading only required config | Implemented; release validation below |
| F10 | Reuse one day inspection per status request | Implemented; release validation below |
| F11 | Report malformed dates without breaking status | Implemented; release validation below |
| F12 | Reject non-regular private files without blocking | Implemented; release validation below |
| F13 | Consistent context time bounds after clock changes | Implemented; release validation below |
| F14 | Save exact review-window identity | Implemented; release validation below |
| F15 | Keep drafts bound to their selected window | Implemented; release validation below |
| F16 | Safe recovery messages and visible field limits | Implemented; release validation below |

## Product and reuse work

- Daily status: verified state, safe pause reason, check time, storage, affected days, manual pause, refresh and local recovery help.
- Weekly review: existing three steps, quality and gap warnings, exact period, 4,000-character field limits, safe draft handling and Show saved results.
- Keep privacy pause active across both visible tabs. Tab selection must not change capture state.
- Separate source integrity from useful work context. Warn about system, unknown and paused context labels without inventing corrected old headings.
- Keep the original journal, intent, ready proof and recovery evidence together. Do not alter historical logs to make them look more complete.
- Prefer removing or batching repeated work, or using an existing template, before proposing an automation.

## Regression checks

- `tests/test_core_capture_recovery.py`: fresh admission on all capture channels, same-title PID changes, bound ActivityWatch enrichment, fixed flush deadlines, storage retention and exact recovery, missed-day proofs and runtime retry timing.
- `tests/test_analysis_inspection.py`: invalid and malformed proof handling, one parse per day in a request, date inventory and payload-free quality warnings.
- `tests/test_operator_controls.py`: current-process status, malformed and deeply nested state, private publication cleanup, exact outcome windows and nonblocking file rejection.
- `tests/test_review_center.py`: both native tabs, keyboard focus, whole-window privacy, safe draft and clock behavior, late worker replies, field limits, Finder and local help.
- `tests/test_cli_recovery.py`, `tests/test_check_analysis_day.py` and `tests/test_private_files.py`: config-independent help and controls, explicit paths, safe errors, pending transaction rejection and stable private reads.
- Existing parser, export, lifecycle, build and signing checks remain part of the full suite.

## Independent review corrections

Separate code and UX reviews checked the combined changes. A final real-writer fault test found that a failed directory sync after state replacement could falsely acknowledge Resume. One fixed private pending-state guard now keeps that candidate unverified until publication succeeds; actual capture remains paused on failure. They added guards for deeply nested JSON, preserved accepted click work during blocked storage, kept safe same-context title enrichment, rejected a stale PID with the same title, and rejected late UI results for a different selected window.

Validation also exposed a startup ownership bug: an early exit could write stopped status without owning the app lock. The cleanup path now requires ownership before any final flush, recovery, marker, status write or lock close. Tests use private temporary runtime homes. The running app republished its own status after the earlier test status write. Completed source logs are checked against their original hashes before release.

## Release evidence

Source implementation and independent reviews are complete. The final full suite passed **606 tests in 28.98 seconds**. Ruff E4/E7/E9/F, dependency consistency and strict dependency audit passed, with no known vulnerabilities. New code adds no dependency. Independent code, UX and final integration reviews found no unresolved material issue in their reviewed scope. Their private reports contain reproductions and final source hashes.

All **194 completed canonical logs** match the before-change SHA-256 checks after deployment, with zero changed or missing files. No source history was rewritten. The installed app is now signed version 4.6.0 with fresh native PID 38841 and matching runtime identity. The final active-day check passes strict parsing, matches its intent journal and has no invalid marker.

Two early build attempts stopped at signing while the Mac/keychain was locked, preserving 4.5.1. After unlocking, the canonical build signed, verified and promoted 4.6.0 successfully. The pinned signing leaf is unchanged and no TCC re-grant was needed. Source commit `4dbee1d` was pushed to `origin/main`.

Live checks confirmed that Daily status opens by default, both tabs display correctly and switching tabs keeps the window privacy pause active. Closing or minimizing removes that pause. Final state shows capture active, manual pause off and storage clear. Actual foreground typed events were saved within 14 seconds. The synthetic TextEdit marker test remained unverified because TextEdit was inactive while Screen Sharing was the native foreground app; the operator deleted the temporary test document. No captured text was printed to validate foreground capture.

Storage checks report zero unsafe log or review items and zero missing readiness proofs. The bundled local recovery guide is present. See [`specs/IMPL-STATUS.md`](specs/IMPL-STATUS.md) for the deployment evidence and validation limits.

The prior 8b3fa3d baseline passed 515 tests. Passing tests do not prove live consent, every native app's Accessibility behavior, VoiceOver use, continuous capture or survival of RAM-only records after a forced exit or power loss.
