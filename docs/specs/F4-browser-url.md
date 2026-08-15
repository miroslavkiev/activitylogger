# F4 — Optional browser URL capture (P0)

**Status:** Implemented (opt-in; default OFF).  
**Scope contract:** [`00-SCOPE.md`](00-SCOPE.md)  
**Constraints:** [`F0-constraints-and-non-goals.md`](F0-constraints-and-non-goals.md), [`docs/MACOS_TCC.md`](../MACOS_TCC.md)  
**Related:** F1 (native window titles), F2 (`features.browser_url_capture`), F5 (`url_change` trigger)

## 1. Problem

Daily Markdown often shows browser work as `## Safari — …` or `## Google Chrome — …` with page titles only. Titles are weak for automation analysis (duplicate titles, truncated titles, no host path). Gemini needs stable URL lines when the user opts in.

Screen Recording, JPEG, and OCR for the address bar are out of scope (F0 / Ignored OCR).

## 2. Product decision

| Decision | Choice | Justification |
|----------|--------|---------------|
| Platform | macOS only | Product is macOS TCC + signed `.app` |
| Default | **OFF** (`features.browser_url_capture = false`) | Keep base TCC set at Accessibility + Input Monitoring only |
| Capture method | Accessibility first; Apple Events fallback | No Screen Recording; no pixels; no OCR |
| Storage | Event lines in daily Markdown | Markdown-only artifact (KEEP) |
| Query redaction | **None at capture** | Cleaner secret redaction is Ignored; opt-in flag is the privacy gate |
| Section headings | Unchanged (`## {app} — {title}`) | F1 owns titles; URL is a separate event |
| Section seal on URL | **Only when F5 flag ON** | F4 path seals after URL event; trigger `url_change`; F5 owns Markdown syntax |

### Why default OFF (locked)

Today production needs **Accessibility** + **Input Monitoring** only ([`MACOS_TCC.md`](../MACOS_TCC.md)).

URL capture that uses Apple Events needs **Automation** consent per browser. Default ON would:

1. Prompt new System Settings dialogs after rebuild or first browser focus.
2. Expand the trust surface without an explicit user choice.
3. Risk logging full URLs (including query strings) without consent.

Opt-in keeps the base path stable. The flag is the privacy gate. Partial query redaction is out of scope.

## 3. Goals

1. When the flag is ON and a supported browser is frontmost, log the active tab URL on change.
2. Never log a URL while secure pause is active.
3. Never require Screen Recording, mic, JPEG, or OCR.
4. Keep a stable Markdown line format for Gemini.
5. Fail soft: missing Automation grant or unsupported browser must not stop keystroke capture.

## 4. Non-goals

- Screenshot / Screen Recording / JPEG address-bar OCR
- Cleaner-side URL or query-token redaction (Ignored in scope)
- JSONL / SQLite URL sidecars
- Non-macOS browsers
- Logging every iframe or history entry (active tab / front window only)
- Changing `##` heading shape to embed the URL
- Broader app ignore-lists (Ignored)
- Sealing on URL change when `capture_triggers_enabled` is false (F5 OFF = event line only)
- Helper daemons, Screenpipe-style pipes, or a second process for URL read

## 5. Actors and surfaces

| Actor | Role |
|-------|------|
| User | Sets `features.browser_url_capture = true` (F2); grants Automation for chosen browsers once when Apple Events path is used |
| Launch Agent / signed `.app` | Same TCC identity as today (`ActivityLoggerNative.app` via `open -W`) |
| Gemini prompt | Reads `> [URL]: …` lines as stable browser context |
| F1 | Supplies frontmost app + window title; secure-app matching |
| F5 | Supplies closed-set name `url_change` and italic trigger syntax; F4 seals when both flags are ON |

## 6. Functional requirements

### FR-F4-001 — Feature flag

The logger SHALL read boolean `features.browser_url_capture` (F2 canonical name).  
Until F2 lands, a temporary constant MAY mirror that name; default MUST remain `false`.  
Do **not** use alternate names (`browser_url_enabled`, `url_capture`, etc.).

When `false` or unset:

- SHALL NOT poll browsers for URLs
- SHALL NOT call the URL provider
- SHALL NOT send Apple Events for URL read
- SHALL NOT cause Automation prompts attributable to URL capture

### FR-F4-002 — macOS-only enablement

On non-macOS builds or when AX/AppKit APIs are unavailable, enabling the flag SHALL be a no-op (no crash, no URL events).

### FR-F4-003 — Capture sources (ordered preference)

When the flag is ON and the frontmost app is a supported browser, the logger SHALL obtain the active tab URL using, in order:

1. **Accessibility attributes** on the frontmost browser window (for example document URL / address field value), when available without Screen Recording.
2. Else **Apple Events** to the frontmost browser (Scripting Bridge / in-process equivalent), reading the active tab URL.

The logger SHALL NOT use Screen Recording, window bitmaps, CGDisplayStream, `screencapture`, JPEG, or OCR.

### FR-F4-004 — Supported browsers (initial)

Initial target set (bundle / display name matching left to implementation; tests must cover these labels):

| Browser | Preferred path |
|---------|----------------|
| Safari | AX first, Apple Events fallback |
| Google Chrome | Apple Events (AX URL often weak) |
| Chromium / Brave / Microsoft Edge / Arc | Same family as Chrome when scriptable |
| Firefox | Best-effort AX or Apple Events; may remain unsupported |

Unsupported or unreadable browser: skip URL event; continue normal logging.

### FR-F4-005 — Emit on change only

The logger SHALL emit a URL event only when all are true:

- flag ON
- `is_paused()` is false
- frontmost app is a supported browser
- URL string is non-empty after normalize
- URL differs from `last_emitted` (see FR-F4-006)

### FR-F4-006 — Dedup scope

Dedup key SHALL be the full URL string last **emitted** while not paused (`last_emitted`).

Switching away from a browser and back to the **same** URL SHALL NOT emit again until a different URL was emitted in between, or the process restarted.

(Rationale: avoid spam on app-switch loops; F1 heading already records return to the browser.)

### FR-F4-007 — Secure pause (locked — clipboard parallel)

While `_pause_secure_app` or `_pause_secure_field` makes `is_paused()` true:

1. SHALL NOT append URL events (`add_event` remains a no-op while paused).
2. If a poll runs, SHALL update an internal **observation** marker for the candidate URL **without** writing to the log (same idea as clipboard marker advance).
3. SHALL NOT use “freeze polling only” as the sole privacy control: after resume, a URL observed **only** while paused MUST NOT appear as a new emit of that same string.

**Required behavior:**

- URL seen only while paused → never written later as if it were a fresh post-resume capture of that same URL.
- After resume, emit only when the candidate differs from `last_emitted` **and** was not solely absorbed as a paused observation of that same string (tests lock this via `apply_url_observation`).
- Prefer one helper (`apply_url_observation`) so pause rules stay in one place.

### FR-F4-008 — Markdown event format (stable)

URL events SHALL use exactly this single-line form (no code fence):

```text
> [URL]: {absolute_url}
```

Rules:

- `{absolute_url}` is the URL string from the browser after normalize (scheme + host + path + query + fragment as returned).
- No capture-time query stripping (see §8).
- Leading `> [URL]: ` prefix is fixed ASCII for Gemini / cleaner stability.
- Trailing newline handling matches other events (`add_event` / flush already adds spacing).
- F5 may later change the italic timestamp line to include ` · trigger:…`. URL **event** lines MUST stay unchanged so F4 fixtures remain valid.

Example inside a section:

```markdown
## Google Chrome — Example Domain
*14:02:11*

> [URL]: https://example.com/path?q=1

typed text here

---
```

### FR-F4-009 — Coordination with F1 headings

- F1 remains the source of `## {app} — {title}` and of `(app, title)` for `_is_secure_app_name`.
- URL MUST NOT be concatenated into the heading.
- URL capture MUST NOT change secure-app / secure-field pause matching.
- Window-title changes may open a new section; URL events belong to the section active when the URL is emitted.
- If title update and URL update arrive in the same poll cycle, order SHALL be: apply heading/section rules first, then append URL event to the current section (so the URL sits under the new heading when both change together).

### FR-F4-010 — Coordination with F5 triggers

Reserve trigger name **`url_change`** for F5 (closed set in F5).

| Mode | Behavior |
|------|----------|
| F4 ON, F5 OFF / not shipped | Append `> [URL]: …` only. Do **not** seal a section solely because the URL changed. Do **not** write `trigger:` metadata. |
| F4 ON, F5 ON (`capture_triggers_enabled`) | After a successful URL emit, F4 MUST seal the open buffer (same order as click: flush keys → append URL event → seal) with trigger `url_change`. F5 owns italic-line syntax; F4 owns the seal call on this path. |

F4 tests that assert only event text / heading shape MUST remain valid if F5 adds ` · trigger:url_change` on the timestamp line.

### FR-F4-011 — Gemini prompt note

When F4 is implemented, `prompts/gemini-automation-analysis.md` SHALL mention URL lines of the form `> [URL]: …` under Data format. Spec change can land with the implementation PR; this FR tracks that doc update.

### FR-F4-012 — Diagnostics

On repeated URL read failure (for example Automation denied), the logger SHALL rate-limit a diagnostics line (same pattern as clipboard/AX errors). It SHALL NOT crash listeners.

### FR-F4-013 — Single process

URL capture SHALL run inside the existing Python process (thread or existing window-check loop). No helper daemon, no Screenpipe-style pipes.

### FR-F4-014 — Max URL length

Normalize SHALL truncate candidates longer than **2000** characters (clipboard-class bound) before emit/dedup. Truncation MUST be stable so dedup still works.

## 7. Architecture

```text
window_checker_loop / url_poll (flag ON)
        │
        ▼
 frontmost app name (NSWorkspace / F1)
        │
        ├─ not browser → skip
        ├─ paused → observe marker only (FR-F4-007); no add_event
        └─ browser → get_browser_url(app)
                    │
                    ├─ AX document/address URL
                    └─ else Apple Events active-tab URL
                            │
                            ▼
                   apply_url_observation(...)
                            │
                            └─ event → add_event("> [URL]: " + candidate)
```

### Suggested pure helpers (TDD seams)

| Function | Responsibility |
|----------|----------------|
| `is_browser_app(app_name: str) -> bool` | Supported-browser match |
| `normalize_url_candidate(raw: str \| None) -> str \| None` | Strip whitespace; reject empty; apply 2000-char cap |
| `should_emit_url(*, enabled, paused, candidate, last_emitted) -> bool` | Gate + dedup (may be inlined into apply) |
| `format_url_event(url: str) -> str` | Returns `> [URL]: {url}` |
| `apply_url_observation(...)` | Pause-safe observe + optional emit (clipboard parallel) |

Browser I/O stays behind a narrow port (`BrowserUrlProvider`) so unit tests never need live Safari/Chrome.

### Poll cadence

Reuse `WINDOW_CHECK_SEC` / F2 `timing.window_check_sec`. No sub-second URL spam. Optional: also check URL after click when frontmost is browser (nice-to-have; not required for P0).

### TCC identity

All Apple Events and AX calls MUST execute as `ActivityLoggerNative.app` via the existing `open -W` Launch Agent path. Do not point Automation grants at bare Python / Terminal.

### Forbidden implementation paths

| Forbidden | Why |
|-----------|-----|
| Screen Recording / CGWindowListCreateImage / CGDisplayStream | F0 / scope |
| `screencapture`, JPEG encode, OCR libraries | F0 / Ignored OCR |
| Second process or named pipe for URL | Single-process KEEP |
| Embedding URL in `##` heading | Breaks F1 / Gemini parse |

## 8. Privacy

| Rule | Detail |
|------|--------|
| Secure pause | FR-F4-007; same bar as clipboard |
| Opt-in | Default OFF; user enables knowing URLs (including query strings) may be logged |
| Query tokens | **No** capture-time redaction; **no** cleaner URL redaction (Ignored) |
| Log dir mode | Existing `0700` on log directory remains |
| Secure apps | Password managers already pause; no URL write while paused |
| Length | Cap at 2000 chars (FR-F4-014) |

**Product note:** Full URLs improve Gemini automation ideas (hosts, paths, deep links). The privacy control is the feature flag, not a partial redaction that scope forbids expanding in the cleaner.

## 9. TCC checklist (exact)

Align with [`docs/MACOS_TCC.md`](../MACOS_TCC.md). Production identity is always the certificate-signed `.app`.

### Always required (unchanged)

| Permission | Target | Notes |
|------------|--------|-------|
| Accessibility | `ActivityLoggerNative.app` | Existing; AX URL path + secure field |
| Input Monitoring | `ActivityLoggerNative.app` | Existing; pynput |

### Required only when flag ON **and** Apple Events fallback is used

| Permission | Target | Notes |
|------------|--------|-------|
| **Automation** (Apple Events) | Control **Safari** / **Google Chrome** / other scriptable browsers as prompted | System Settings → Privacy & Security → Automation → ActivityLoggerNative → allow each browser |

Notes:

- AX-only success for a browser MAY avoid an Automation prompt for that browser.
- Chrome-family capture often needs Automation because AX URL is weak.
- macOS may prompt: “ActivityLoggerNative wants to control Safari” (wording varies by OS version).
- Flag OFF MUST NOT trigger Automation prompts for URL read.

### Explicitly NOT required for F4

| Permission | Why not |
|------------|---------|
| Screen Recording | Forbidden by F0; not used |
| Microphone | Out of scope |
| Full Disk Access | Not required for URL Apple Events / AX |

### First-time enable procedure (user-facing)

1. Set `features.browser_url_capture = true` in config (F2).
2. Rebuild/restart with `./scripts/rebuild_and_restart.sh` if binary changed; else kickstart if config-only hot reload is unsupported (F2 decides reload rules).
3. Bring Safari/Chrome to front; approve Automation prompts when shown (AE path).
4. Navigate to a new URL; within ~ one window-check interval, daily log gains a `> [URL]:` line.
5. Certificate-signed rebuild with the same signing identity SHOULD NOT require re-grant of Accessibility / Input Monitoring; Automation entries usually remain for the same app identity.

Update [`docs/MACOS_TCC.md`](../MACOS_TCC.md) in the implementation PR with an Automation subsection for optional URL capture.

## F0 impact

| F0 item | F4 effect |
|---------|-----------|
| K1 Launch + signing | Untouched identity; Automation is optional when flag ON + Apple Events path. |
| K2 Keystrokes | Untouched. |
| K3 Secure pause | URL path must match clipboard-parallel pause rules (FR-F4-007). |
| K4 Markdown-only | URL is an event line only; no sidecar. |
| K5 Cleaner + prompt | Prompt may document `> [URL]:`; no new redaction. |
| K6 Single-process | Untouched. |
| B1–B3 Media / Screen Recording / OCR | Stay banned (forbidden table in §7). |
| B4 Other ignores | Stay banned. |

## 10. Acceptance criteria

1. **AC-F4-01** Default config / unset flag → zero URL events; provider call count is 0 (no Apple Events URL reads in unit tests).
2. **AC-F4-02** Flag ON + mock provider returns URL A then URL B → log contains two lines `> [URL]: A` and `> [URL]: B` in order.
3. **AC-F4-03** Flag ON + same URL twice → only one event.
4. **AC-F4-04** Flag ON + paused → no event; after resume, same URL still does not emit; a different URL emits.
5. **AC-F4-05** `format_url_event` always matches `^> \[URL\]: \S` for non-empty absolute URLs used in fixtures.
6. **AC-F4-06** Secure-app pause regression tests remain green; URL path cannot bypass `add_event` pause guard.
7. **AC-F4-07** No code path in F4 implementation imports or calls Screen Recording / CGWindow image / screenshot / OCR APIs (enforce via grep test).
8. **AC-F4-08** Heading format remains `## {app} — {title}` with URL only as event body.
9. **AC-F4-09** Provider failure returns `None`; logger continues; diagnostics rate-limited.
10. **AC-F4-10** Gemini prompt lists URL line format after implementation.
11. **AC-F4-11** Config key is `features.browser_url_capture` (F2); alternate names are rejected or unused.
12. **AC-F4-12** With F5 off, URL change alone does not invent `trigger:` metadata or require a section seal.
13. **AC-F4-13** Candidates longer than 2000 chars are truncated before emit.
14. **AC-F4-14** With F4 ON and F5 ON, a URL change emit seals the open section with trigger `url_change`.

## 11. TDD — failing tests first

Add `tests/test_browser_url.py` (names locked for implementers).

### Unit — pure logic

| Test name | Given / When / Then |
|-----------|---------------------|
| `test_flag_off_never_emits` | Given enabled=False, candidate URL set; When `should_emit_url` / `apply_url_observation`; Then event is `None` and last_emitted unchanged. |
| `test_format_url_event_stable_prefix` | Given `https://example.com/x`; When format; Then exactly `> [URL]: https://example.com/x`. |
| `test_emit_on_first_url` | Given enabled, not paused, last_emitted empty; When candidate `https://a.test`; Then event formatted and last_emitted updated. |
| `test_dedup_same_url` | Given last_emitted equals candidate; When observe; Then no event. |
| `test_emit_on_url_change` | Given last_emitted `https://a.test`; When `https://b.test`; Then one event for B. |
| `test_paused_does_not_emit` | Given paused=True and new candidate; When observe; Then no event. |
| `test_paused_url_not_flushed_after_resume` | Given URL seen only while paused; When pause clears and same URL observed; Then still no event; When different URL; Then emit different URL only. |
| `test_empty_or_whitespace_url_rejected` | Given `""` / `"  "`; When normalize / observe; Then no event. |
| `test_url_longer_than_2000_truncated` | Given candidate length > 2000; When normalize; Then length == 2000 and emit uses truncated form. |
| `test_is_browser_app_positive_negative` | Given Safari/Chrome/Edge/Brave/Arc vs Terminal/Code; When `is_browser_app`; Then True/False as table. |
| `test_add_event_still_blocks_url_when_paused` | Given pause on; When `add_event(format_url_event(...))`; Then `_current_events` empty (regression). |

### Unit — provider port

| Test name | Given / When / Then |
|-----------|---------------------|
| `test_provider_ax_preferred_when_present` | Given fake provider AX returns URL, AE would return other; When resolve; Then AX URL used. |
| `test_provider_falls_back_to_apple_events` | Given AX empty, AE returns URL; When resolve; Then AE URL. |
| `test_provider_failure_returns_none` | Given both paths raise/deny; When resolve; Then `None`, no exception leak. |

### Integration-style (mocked I/O, real section flush)

| Test name | Given / When / Then |
|-----------|---------------------|
| `test_url_event_lands_under_current_heading` | Given heading `Google Chrome — Title`; When emit URL and flush; Then Markdown has `## Google Chrome — Title` then `> [URL]: …` before `---`. |
| `test_title_and_url_same_cycle_url_under_new_heading` | Given heading changes to new title and URL changes in one apply step; When flush; Then URL appears under the new heading section. |
| `test_flag_off_window_loop_skips_provider` | Given flag off; When one window-check iteration with browser frontmost; Then provider call count is 0. |
| `test_f4_alone_does_not_write_trigger_metadata` | Given F5 off; When URL emits and flush; Then no `trigger:` substring in section timestamp line. |
| `test_f4_with_f5_seals_url_change` | Given F4 ON and F5 ON; When URL emits; Then section seals with `trigger == "url_change"` and body includes `> [URL]: …`. |
| `test_secure_app_match_unchanged_with_url_helper` | Given secure app name from F1; When URL observation runs; Then pause matching still uses app/title only. |

### Constraint / grep guards

| Test name | Given / When / Then |
|-----------|---------------------|
| `test_no_screen_capture_imports_in_url_module` | Given F4 module sources; When scanned; Then no `CGWindowList`, `CGDisplayStream`, `screencapture`, OCR libs. |
| `test_config_key_is_browser_url_capture` | Given F2 defaults / loader (or F4 constant bridge); When read; Then key path is `features.browser_url_capture` and default is False. |

### Manual / TCC (not CI)

| Check | Steps | Pass |
|-------|-------|------|
| Automation grant | Enable flag; focus Chrome; approve prompt | URL lines appear |
| Deny Automation | Deny Chrome control; AX empty | No URL lines; keystrokes still log |
| Flag off | Flag false; focus Chrome | No Automation prompt for URL; no `> [URL]:` |
| Pause | Open 1Password; no URL lines while paused | Pass |
| Signing | Certificate leaf DR after rebuild | No TCC Accessibility re-prompt |

## 12. Markdown / Gemini contract

**Stable token:** `> [URL]:`

Gemini data-format bullet (target text for FR-F4-011):

> Optional browser lines: `> [URL]: https://…` when URL capture is enabled.

Cleaner (`clean_markdown_log.py`): no new URL redaction rules (Ignored). Cleaner MUST leave `> [URL]:` lines intact unless an existing generic rule already strips them (verify with a fixture test if cleaner grows).

## 13. Dependencies and sequencing

| Spec | Relation |
|------|----------|
| F0 | No Screen Recording / OCR / JPEG; single-process; Markdown-only |
| F2 | Owns `features.browser_url_capture` default `false`; F4 may hard-code a constant until F2 lands |
| F1 | Frontmost app + title; URL must not break secure-app name matching or heading shape |
| F5 | Owns `url_change` name + italic trigger syntax; F4 seals when both flags ON |

**Suggested implement order:** pure helpers + tests → provider port → wire into window loop behind flag → TCC doc + Gemini prompt.

## 14. Implementation notes (after tests fail)

- Prefer extending `window_checker_loop` over a new high-frequency thread.
- Mirror `apply_clipboard_change` for pause-safe observation.
- Use existing `add_event` so pause remains one gate.
- Keep Ukrainian labels on click/screen events as-is; URL tag is English ASCII by design for Gemini stability.
- Production verify: grow `logs/daily_log_*.md` with `> [URL]:` after flag ON — not only “listeners started”.
- After logger binary changes: `./scripts/rebuild_and_restart.sh`; confirm `certificate leaf` in designated requirement.

## 15. Open points (do not block P0)

| ID | Topic | Default until decided |
|----|-------|------------------------|
| OP-F4-1 | Firefox support quality | Best-effort; failures OK |
| OP-F4-2 | Click-triggered URL refresh | Not required for P0 |
| OP-F4-3 | Per-browser AX vs AE matrix hardening | Follow FR-F4-004; refine after manual TCC runs |

## 16. Traceability

| ID | Maps to |
|----|---------|
| FR-F4-001 … 014 | §6 |
| AC-F4-01 … 14 | §10 |
| Tests | §11 |
| TCC | §9 |
| Non-goals | §4 / `00-SCOPE.md` Ignored + F0 |
| F1 / F5 | FR-F4-009, FR-F4-010, §13 |

## Critic revision log

**Verdict: ACCEPT**

| Checklist item | Finding | Edit |
|----------------|---------|------|
| 1. Default OFF justified | Was present but under-specified vs base TCC set | Expanded “Why default OFF”; tied to Accessibility + Input Monitoring only and Automation surprise |
| 2. No Screen Recording / JPEG / OCR creep | Present but easy to reintroduce via “address bar image” ideas | Added forbidden table; F0 link; grep AC kept; non-goals list hardened |
| 3. TCC / Automation documented | Good base; ambiguous “Automation always” | Clarified AX may avoid Automation; AE needs it; flag OFF must not prompt; identity = signed `.app` / `open -W` |
| 4. Pause / privacy | FR-F4-007 allowed “freeze polling **or** observe” — freeze-only breaks post-resume secrecy | Locked clipboard-parallel observation markers; removed freeze-only option |
| 5. Markdown format stable | Solid; F5 timestamp risk | Stated event line immutable when F5 adds ` · trigger:…` |
| 6. TDD adequacy | Gaps: config key, length cap, F5-off metadata, secure-app unchanged | Added FR-F4-014, AC-F4-11…13, and matching tests |
| 7. F1 / F5 coordination | Key name vs F2; seal ownership vs F5 | **Aggregate:** key is `features.browser_url_capture`. F4 alone = event only; F4+F5 ON = F4 seals with `url_change` |

No code changes. Implementation remains out of scope for this revision.

**Aggregate critic (2026-08-15):** Renamed config key to F2 canonical `features.browser_url_capture` (default false).

**Independent aggregate verifier (2026-08-15):** Locked F4+F5 ON → F4 seals with `url_change` (was contradictory: F4 said “F5 owns seal”, F5 said “optional per F4”, MASTER said both).
