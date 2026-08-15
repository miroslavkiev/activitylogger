# F1 — Native-first window titles (ActivityWatch optional)

**Status:** draft spec (TDD), critic-revised  
**Priority:** P0  
**Scope contract:** [`00-SCOPE.md`](00-SCOPE.md)  
**Constraint contract:** [`F0-constraints-and-non-goals.md`](F0-constraints-and-non-goals.md)  
**Depends on:** none for behavior. F2 owns `config.toml` load and schema. F1 uses only the `[window_titles]` keys reserved in F2.  
**Related code today:** `get_active_window()`, `get_frontmost_app_name()`, `window_checker_loop()`, `_is_secure_app_name()` in `interleaved_logger.py`  
**Gemini contract:** `prompts/gemini-automation-analysis.md` expects `## App — Window title`

---

## 1. Summary

ActivityLogger resolves frontmost **app name** and **window title** from macOS first (`NSWorkspace` + Accessibility). ActivityWatch is an optional enricher. It fills empty fields only. It never replaces a non-empty native value.

Section headings stay `## {app} — {title}` (em dash `U+2014`). Secure-app pause uses the same resolved `(app, title)` pair in the same check cycle. Capture stays useful when ActivityWatch is off or missing.

---

## 2. Problem / current behavior

Today the logger treats ActivityWatch as the primary title source.

| Fact | Location |
|------|----------|
| `get_active_window()` only calls ActivityWatch HTTP (`AW_BASE_URL`, default `http://localhost:5600`) | `interleaved_logger.py` ~233–254 |
| On AW failure it returns `("", "")` | same |
| `get_frontmost_app_name()` already uses `NSWorkspace` `localizedName` | ~176–186 |
| `window_checker_loop()` calls AW first; if `app` is empty it falls back to frontmost name only | ~502–508 |
| If `title` is empty it substitutes `AW_HINT` = `"(ActivityWatch not running; start ActivityWatch for window titles)"` | ~54–55, ~508 |
| Headings are `{app} — {title}`; flush writes `## {heading}` | ~513–515, ~625 |
| Secure-app pause uses `_is_secure_app_name(app, title)` against `SECURE_APPS` substrings in app **or** title | ~52, ~155–158, ~510 |
| Startup diag messages say “ActivityWatch OK / unavailable” | ~676–688 |
| README lists AW as the window-title path and tells users to put AW in Login Items for titles | `README.md` |
| No unit tests cover native title resolution or resolve order | `tests/` |

Result: without ActivityWatch, titles become a hint string, not a real window title. App name alone is not enough for useful Markdown sections or for title-based secure matches (example: Safari with “Bitwarden — Login”).

There is no Screen Recording / OCR path in scope ([`00-SCOPE.md`](00-SCOPE.md) ignored list). Native titles use Accessibility already required for capture.

---

## 3. Goals / Non-goals

### Goals

- Resolve `(app, title)` with native macOS APIs as the **default and primary** path.
- Keep ActivityWatch as an **optional enricher** that fills empty `app` and/or empty `title` only.
- Keep Markdown section shape `## {app} — {title}` stable for Gemini.
- Keep `_is_secure_app_name(app, title)` correct for native-sourced strings.
- Make capture useful when ActivityWatch is not installed or not running.
- Cover the new resolution path with failing-first pytest cases.

### Non-goals

- JPEG / audio / Screen Recording / OCR fallback (F0 / scope ignore).
- Browser URL capture (F4).
- Capture-trigger metadata on sections (F5).
- Broader ignore-lists for apps/windows (scope ignore).
- Ownership of global `config.toml` load/schema (F2). F1 only names the reserved `[window_titles]` keys.
- Changing daily Markdown as the only log artifact.
- Changing Launch Agent / signing / TCC chain.
- Locale / Ukrainian label changes (scope ignore).
- AW override of a non-empty native title (deferred; not in F1).

---

## 4. Product decisions (locked for F1)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary source | Native `NSWorkspace` + AX window title | Removes hard AW dependency; uses existing Accessibility grant |
| Enricher | ActivityWatch HTTP when enabled | Fills gaps only; optional |
| Conflict policy | **Native wins** when both sides have a non-empty value for that field | Predictable; no “weaker title” heuristics |
| Empty title display | Fixed placeholder `Unknown window` | Keeps `{app} — {title}` form for Gemini |
| Separator | Em dash ` — ` (spaces + `U+2014`) | Matches today’s code and Gemini prompt |
| Config keys | F2 table: `window_titles.activitywatch_enricher`, `window_titles.activitywatch_base_url` | Avoid a second key namespace |
| Secure pause inputs | Same resolve result used for heading **and** `_is_secure_app_name` in one cycle | No dual-source race |

---

## 5. User stories

1. **As a user without ActivityWatch**, I get real app and window titles in daily Markdown so my log stays useful after reboot.
2. **As a user with ActivityWatch running**, I still get titles; AW may fill gaps when a native field is empty.
3. **As a user who opens a password manager**, secure-app pause still triggers from app name or title substrings, whether the strings came from native APIs or AW.
4. **As a maintainer**, I can unit-test title resolution without a live ActivityWatch server.
5. **As an agent rebuilding the app**, certificate-signed rebuild remains the only production path; F1 does not change TCC grants after a cert-signed rebuild.

---

## 6. Resolution algorithm (normative)

Define one resolver (name may change; behavior is normative). Call it from `window_checker_loop()` and from startup heading init. Do not call AW-only `get_active_window()` as the production path.

### 6.1 Steps

1. **Native read** (when AppKit / AX bindings are available):
   - `app_n` = frontmost `NSWorkspace` `localizedName` (same idea as today’s `get_frontmost_app_name()`).
   - `title_n` = Accessibility title of that app’s focused window; if missing, try main/front window once (`AXTitle` or equivalent window-level attribute only).
2. **Start result** with `(app, title) = (app_n, title_n)` (empty string if missing).
3. **Enricher gate:** if `window_titles.activitywatch_enricher` is `false` (or interim constant equivalent), skip HTTP. Go to step 5.
4. **Enricher fill** (best-effort; errors → no data):
   - If `app` is empty and AW returns a non-empty app, set `app` from AW.
   - If `title` is empty and AW returns a non-empty title, set `title` from AW.
   - If `app` is already non-empty, do **not** replace it with AW app.
   - If `title` is already non-empty, do **not** replace it with AW title.
5. **Return** `(app, title)`. The resolver does **not** insert placeholders. Placeholders apply only when building the heading string (§6.2).

### 6.2 Heading build (after resolve)

| Condition | Action |
|-----------|--------|
| `app` empty and `title` empty | Skip heading update (`continue`), same as today |
| `app` non-empty and `title` empty | Heading body = `{app} — Unknown window` |
| `app` empty and `title` non-empty | Heading body = `Unknown — {title}` (rare; keep em-dash form) |
| both non-empty | Heading body = `{app} — {title}` |

Flush prefixes `## ` in front of the heading body. Secure prefixes stay:

- `🔒 [SECURE APP PAUSED] {app} — {title_or_placeholder}`
- `🔒 [SECURE FIELD PAUSED] {app} — {title_or_placeholder}`

Exact placeholder string: **`Unknown window`**. Do not use `AW_HINT`. Do not tell the user to start ActivityWatch in headings.

### 6.3 AX unavailable

If native APIs are unavailable (`AX_AVAILABLE` false or equivalent):

- Treat native `(app, title)` as `("", "")`.
- Still allow enricher fill when enabled.
- If both remain empty, skip heading update.
- Do not crash the logger.

---

## 7. Functional requirements

**FR-F1-01** Provide one resolution API that returns `(app: str, title: str)` for the frontmost context per §6.1.

**FR-F1-02** Native path (when available) must obtain app from `NSWorkspace` and title from window-level AX only. Prefer focused window; else main/front once.

**FR-F1-03** If native `app` and native `title` are both non-empty, the result is those values. ActivityWatch is not required.

**FR-F1-04** ActivityWatch enricher:

- Runs only when `window_titles.activitywatch_enricher` is true (default true; see §9).
- Fills empty fields only (§6.1 step 4).
- Must not hard-fail the logger if AW is down; treat errors as “no enricher data”.
- HTTP failures must not escape into the window-check loop.

**FR-F1-05** `window_checker_loop()` and startup heading init must call the unified resolver. Production must not depend on AW-only `get_active_window()` semantics.

**FR-F1-06** When both fields are empty after resolve, skip heading update. Do not invent fake apps.

**FR-F1-07** Apply `Unknown window` only at heading build (§6.2). Remove `AW_HINT` from the default heading path.

**FR-F1-08** Heading body uses em dash form `{app} — {title}` before Markdown `##` prefix. Secure prefixes in §6.2 stay unchanged.

**FR-F1-09** In the same window-check cycle, pass the resolved `(app, title)` (pre-placeholder) into `_is_secure_app_name`. Matching rules stay: `SECURE_APPS` substrings in app or title, case-insensitive. Do not match against a different source than the heading for that cycle.

**FR-F1-10** Diagnostic messages must not claim ActivityWatch is required for titles. Prefer: native OK / native title missing / AW enricher used / AW unavailable (enricher skipped).

**FR-F1-11** Existing privacy tests for `_is_secure_app_name` and pause behavior must keep passing. Secure-field pause (AX) stays unchanged by F1.

**FR-F1-12** Production runtime remains `dist/ActivityLoggerNative.app` via `open -W`. After code change, rebuild with `./scripts/rebuild_and_restart.sh`.

**FR-F1-13** Do not read focused secure-field values as “window titles”. Window-level `AXTitle` only.

---

## 8. Markdown / Gemini format impact

### Locked shape (Gemini)

Gemini prompt documents:

```text
## App — Window title
```

F1 keeps that contract:

- One space, em dash `—` (`U+2014`), one space between app and title.
- Do not switch to hyphen-minus `-` or en dash `–`.
- Do not put URL, trigger, or other metadata inside the `##` line (F4/F5 own other lines).

### Unchanged example

```markdown
## Safari — Example Domain
*14:02:11*

typed text here

---
```

### Secure app (unchanged prefix pattern)

```markdown
## 🔒 [SECURE APP PAUSED] 1Password — Vault
*14:03:01*

---
```

### Without ActivityWatch (changed vs today)

**Today (bad):**

```markdown
## Safari — (ActivityWatch not running; start ActivityWatch for window titles)
```

**After F1 (required)** when native title exists:

```markdown
## Safari — Example Domain
```

**After F1** when app is known and title is still empty after native + optional AW:

```markdown
## Safari — Unknown window
```

### Fallback heading when nothing was ever set

Replace AW-centric `FALLBACK_HEADING`:

- Today: `Unknown — (ActivityWatch not running; start ActivityWatch for window titles)`
- After F1: `Unknown — Unknown window`

---

## 9. Config surface (F2-aligned)

F2 owns discovery, load, and validation of `config.toml`. F1 does **not** invent a parallel file or a `window_titles.*` table.

### Reserved keys (must match F2)

| TOML key | Type | Default | Meaning for F1 |
|----------|------|---------|----------------|
| `window_titles.activitywatch_enricher` | bool | `true` | When true, try AW to fill empty app/title after native |
| `window_titles.activitywatch_base_url` | string | `http://localhost:5600` | AW API base (today’s `AW_BASE_URL`) |

Until F2 lands, implementation may keep module-level constants with the **same semantics** (`activitywatch_enricher`, `activitywatch_base_url` / `AW_BASE_URL`). Do not create a second config file format.

### Conflict rules

- Do **not** ship `[activitywatch]`, `aw_enabled`, or `aw_base_url`. Those names are rejected aliases in F2.
- Do **not** expand `privacy.secure_apps` under F1 (broader ignore-lists stay out of scope; F2 may later load the existing list only).
- Do **not** add F1 root keys under `[features]`; that table is for F4–F6 flags in F2.

Out of F1: flush intervals, log paths, browser URL flag, capture triggers.

---

## 10. Privacy / security requirements

**PR-F1-01** Do not add Screen Recording, microphone, JPEG, or OCR to obtain titles.

**PR-F1-02** Secure-app pause must not regress:

- App name containing a `SECURE_APPS` token still pauses (example: `1Password`).
- Title containing a `SECURE_APPS` token still pauses (example: Safari title `Bitwarden — Login`).
- Pause must work when those strings come from native AX/NSWorkspace (not only AW).
- Pause decision and heading for that cycle use the same resolve pair (§6 / FR-F1-09).

**PR-F1-03** While paused, keystrokes and clipboard logging rules stay as today. F1 does not change pause semantics beyond correct app/title inputs.

**PR-F1-04** Native title reads use Accessibility already granted to the signed `.app`. Do not ask for new TCC categories for F1.

**PR-F1-05** Do not log password field values as window titles (FR-F1-13).

**PR-F1-06** Markdown remains the only user-facing log store (no JSONL/SQLite sidecar for titles).

---

## 11. F0 impact

| F0 item | F1 effect |
|---------|-----------|
| K1 Launch + signing | Untouched. Rebuild still `./scripts/rebuild_and_restart.sh`. |
| K2 Keystrokes + hotkeys | Untouched. Pause still blocks append. |
| K3 Secure pause + tests | **Touched inputs only.** Same matching rules; new source of `(app, title)`. Existing privacy tests must stay green. |
| K4 Markdown-only artifact | Untouched. Heading copy changes; shape stays `## …`. |
| K5 Cleaner + Gemini prompt | Heading form stays Gemini-compatible. Prompt file may note native titles; no new redaction. |
| K6 Single-process capture | Untouched. AW remains optional in-process HTTP enricher, not a second capture daemon. |
| B1–B3 Media / Screen Recording / OCR | Stay banned. |
| B4 Other ignores | Stay banned (no ignore-list platform, no JSONL, no locale work). |

F1 preserves F0 acceptance criteria AC-K1…AC-K6 and AC-B. New F1 tests do not replace the F0 regression suite.

---

## 12. Acceptance criteria

- [ ] With ActivityWatch **stopped**, focusing a normal app window writes `## {app} — {real title}` within one window-check period (native path).
- [ ] With ActivityWatch **running**, headings still work; AW does not replace a non-empty native title or non-empty native app.
- [ ] Empty native title + AW title present → heading uses AW title (enricher fill).
- [ ] Empty native title + AW down → heading uses `{app} — Unknown window` (no `AW_HINT` text).
- [ ] Both empty after resolve → no heading invent; skip update.
- [ ] `_is_secure_app_name` / secure-app pause still triggers for app-token and title-token cases.
- [ ] Secure pause works when app/title came from native mocks/APIs in tests; same cycle as heading (§6).
- [ ] Secure-field pause behavior unchanged; existing field-pause tests still pass.
- [ ] Daily log remains Markdown-only; section headings still use `## ` + `{app} — {title}` with em dash.
- [ ] Existing `tests/test_privacy_and_cleaner.py` cases still pass.
- [ ] New F1 unit tests fail on current `main` before implementation, then pass after.
- [ ] README / feature bullet no longer states ActivityWatch as the primary title source (doc update in same change set as code).
- [ ] Config keys used for AW match F2 names (`window_titles.activitywatch_enricher`, `window_titles.activitywatch_base_url`), or interim constants with the same semantics.
- [ ] After implementation: `./scripts/rebuild_and_restart.sh`; `codesign -d -r-` shows `certificate leaf`; typing grows `logs/daily_log_*.md`.

---

## 13. Test plan (TDD)

Mark **U** = unit (mock NSWorkspace / AX / HTTP). Mark **I** = integration (optional; may need Accessibility on the host).

**Before implementation:** new unit cases below must fail (native-first API missing, AW-first path, or `AW_HINT` still used). Existing privacy tests must already pass and must stay green.

### Unit — resolution order

| Suggested name | Given / When / Then | Type |
|----------------|---------------------|------|
| `test_resolve_window_prefers_native_over_aw` | Given native `("Safari", "Docs")` and AW `("Other", "AW Title")`. When resolve runs. Then `("Safari", "Docs")`. | U |
| `test_resolve_window_aw_fills_empty_native_title` | Given native `("Safari", "")` and AW `("Safari", "GitHub")`, enricher on. When resolve runs. Then title is `"GitHub"`. | U |
| `test_resolve_window_aw_fills_empty_native_app` | Given native `("", "Some Title")` and AW `("Mail", "Some Title")`, enricher on. When resolve runs. Then app is `"Mail"`. | U |
| `test_resolve_window_aw_does_not_override_native_app` | Given native `("Safari", "")` and AW `("Chrome", "GitHub")`, enricher on. When resolve runs. Then app stays `"Safari"` and title becomes `"GitHub"`. | U |
| `test_resolve_window_aw_down_uses_native_only` | Given native `("Terminal", "bash")` and AW raises / unreachable. When resolve runs. Then `("Terminal", "bash")`; no exception escapes. | U |
| `test_resolve_window_aw_disabled_skips_http` | Given `activitywatch_enricher` false and native `("Safari", "")`. When resolve runs. Then no HTTP call; resolve returns `("Safari", "")`. | U |
| `test_resolve_window_both_empty_returns_empty_pair` | Given native and AW empty. When resolve runs. Then `("", "")`. | U |
| `test_resolve_window_ax_unavailable_allows_aw_fill` | Given native unavailable and AW `("Mail", "Inbox")`, enricher on. When resolve runs. Then `("Mail", "Inbox")`. | U |

### Unit — heading / placeholder

| Suggested name | Given / When / Then | Type |
|----------------|---------------------|------|
| `test_heading_uses_unknown_window_not_aw_hint` | Given app `"Safari"` and empty title after resolve. When heading is built. Then string is `Safari — Unknown window` and does not contain `ActivityWatch`. | U |
| `test_heading_uses_em_dash_separator` | Given `("Safari", "Docs")`. When heading is built. Then body contains ` — ` (em dash), not ` - `. | U |
| `test_fallback_heading_has_no_aw_instruction` | Given no current heading on flush. When fallback is used. Then fallback is `Unknown — Unknown window` and does not contain `ActivityWatch not running`. | U |
| `test_markdown_section_line_format` | Given heading `Safari — Example`. When flush formats a section. Then line starts with `## Safari — Example`. | U |
| `test_both_empty_skips_heading_update` | Given resolve `("", "")`. When window checker runs one cycle. Then current heading is unchanged / update skipped. | U |

### Unit — secure pause inputs

| Suggested name | Given / When / Then | Type |
|----------------|---------------------|------|
| `test_secure_pause_from_native_app_name` | Given resolve returns `("1Password", "Vault")`. When pause rules run on that pair. Then secure-app pause is true. | U |
| `test_secure_pause_from_native_title_token` | Given resolve returns `("Safari", "Bitwarden — Login")`. When pause rules run. Then secure-app pause is true. | U |
| `test_non_secure_native_window_does_not_pause_by_name` | Given `("Safari", "Example")`. When pause rules run. Then secure-app pause is false (field pause out of scope for this case). | U |
| `test_secure_pause_uses_same_pair_as_heading` | Given one resolve result. When checker updates heading and pause. Then both consumers see the same `(app, title)` for that cycle. | U |

### Unit — legacy / regression

| Suggested name | Given / When / Then | Type |
|----------------|---------------------|------|
| `test_is_secure_app_name_positive_and_negative` | Existing case — keep. | U |
| `test_get_active_window_no_longer_sole_source` | Given AW and native both patched. When the production entry used by the checker is called. Then native path is consulted first (assert mock call order). | U |
| Existing K3 field-pause / clipboard-pause cases | Must stay green; F1 must not alter field-pause control flow. | U |

### Integration (optional, host-dependent)

| Suggested name | Given / When / Then | Type |
|----------------|---------------------|------|
| `test_live_frontmost_title_smoke` | Given Accessibility trusted and a known front app. When native resolve runs once. Then app is non-empty; title may be empty on some apps but must not raise. | I |

Skip live smoke in CI if `AXIsProcessTrusted()` is false.

### Must fail before implementation

On current code:

1. Any test that asserts native-first call order.
2. Any test that asserts absence of `AW_HINT` / “ActivityWatch not running” in headings.
3. Any test that expects a dedicated native title helper (does not exist yet).
4. `test_resolve_window_prefers_native_over_aw` (today AW is the only source inside `get_active_window`).
5. `test_heading_uses_unknown_window_not_aw_hint` (today `AW_HINT` is used).

Preferred new module: `tests/test_window_titles.py` (name may change). Keep privacy cases in `tests/test_privacy_and_cleaner.py`.

---

## 14. Risks & closed questions

### Risks

- Some apps expose empty `AXTitle`; enricher or `Unknown window` will show. Acceptable; OCR is out of scope.
- Electron / browser titles may differ from old AW-only logs under native-wins policy. Acceptable for F1.
- Extra AX reads each `WINDOW_CHECK_SEC` may add load; keep reads shallow (window title only, not full `extract_text` tree).
- Renaming `get_active_window` may break external importers; prefer a thin wrapper or keep the name with new semantics documented in tests.

### Closed for F1 (do not reopen in implementation)

1. AW override of non-empty native title: **no**.
2. Placeholder string: **`Unknown window`** (keeps em-dash form for Gemini).
3. Config keys: **`window_titles.activitywatch_enricher`** and **`window_titles.activitywatch_base_url`** per F2. Ship with constants first if F2 is not loaded yet.
4. “Weaker title” heuristics: **out**. Empty vs non-empty only.

Do not use open discussion to add ignore-lists, OCR, JSONL, or Screen Recording.

---

## 15. Implementation notes (high-level only)

1. Add a native helper that returns frontmost app name + focused/main window `AXTitle` using existing AppKit / ApplicationServices imports.
2. Refactor resolution so native runs first; call existing AW bucket/event fetch only as enricher for empty fields when `activitywatch_enricher`.
3. Point `window_checker_loop()` and startup init at the unified resolver; feed the same pair into secure-app pause.
4. Replace `AW_HINT` / `FALLBACK_HEADING` AW instructions with neutral unknown-window copy.
5. Update diag strings and README feature line to match native-first behavior.
6. Add pytest cases from §13; run them red, then implement, then green.
7. Do not change the pause state machine beyond feeding correct `(app, title)`.
8. After code lands: `./scripts/rebuild_and_restart.sh`; confirm certificate leaf DR; smoke-check log growth.

No production code belongs in this document.

---

## Critic revision log

**Verdict: ACCEPT**

Changes in this critic pass:

1. **Native-first vs AW-optional** — Added normative §6 algorithm. Removed vague “weaker” language. Locked native-wins per field (empty vs non-empty only).
2. **Secure-app pause** — Required same resolve pair for heading and `_is_secure_app_name` in one cycle (FR-F1-09, PR-F1-02, new unit test). Clarified field-pause unchanged.
3. **Heading / Gemini stability** — Locked em dash `U+2014`, `Unknown window`, fallback `Unknown — Unknown window`, and “no metadata in `##`” (F4/F5). Cited Gemini prompt contract.
4. **TDD** — Expanded failing-first cases: no override of native app, AX unavailable + AW fill, both-empty skip, em-dash assert, same-pair pause/heading. Clarified placeholder is heading-layer only.
5. **F0 / scope** — Added §11 F0 impact (required by F0). Restated bans; no ignore-lists / OCR / JSONL.
6. **F2 config** — Locked `[window_titles] activitywatch_enricher` / `activitywatch_base_url` (F2 authority). Rejected `[activitywatch]` / `aw_*` aliases.
7. **STE** — Shortened sentences; decision table; closed open questions that blocked implementers.

**Aggregate critic (2026-08-15):** Re-aligned AW keys to F2 after F2 won the namespace decision.

**Independent aggregate verifier (2026-08-15):** Placeholder cross-ref §8 → §6.2.
