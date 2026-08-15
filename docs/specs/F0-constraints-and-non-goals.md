# F0 — Cross-cutting constraints and non-goals

**Status:** locked constraints (F0_ACCEPT; FINAL_ACCEPT). F0 guard tests in §7.2 stay required for regressions.  
**Date:** 2026-08-15  
**Parent:** [`00-SCOPE.md`](00-SCOPE.md)  
**Audience:** feature authors, implementers, reviewers

This file is the shared constraint layer for F1–F6.  
It is not a product feature.

F0 locks:

- KEEP rules from `00-SCOPE.md`
- AVOID / out-of-scope bans from `00-SCOPE.md`
- Privacy and TCC regression gates

A feature that breaks any requirement here is out of contract.  
Do not add product work here. Put product work in F1–F6 only.

---

## 1. Purpose

Use this file to:

- keep production TCC identity stable
- keep privacy pause and keystroke semantics
- keep Markdown-only user logs
- keep the cleaner and Gemini prompt path
- ban Screen Recording / media / OCR pipelines

Every later spec must include an **F0 impact** section.  
Every later implementation must keep the F0 regression suite green (see §7).

---

## 2. Product job (unchanged)

Personal macOS input transcript → daily Markdown → cleaner → Gemini automation analysis.

Do not redefine this job in feature specs.

---

## 3. KEEP — enforceable requirements

These items expand the KEEP list in `00-SCOPE.md`.  
They freeze current production behavior. They do not add new product scope.

### K1. Certificate-signed `.app` + `open -W` launch chain

| Rule | Requirement |
|------|-------------|
| Runtime | Production capture uses `dist/ActivityLoggerNative.app` only. |
| Launch | Launch Agent label `com.mk.activitylogger` runs `start_logger.sh` → `/usr/bin/open -W` on that `.app`. |
| Rebuild | After logger binary changes, run `./scripts/rebuild_and_restart.sh`. |
| Signing | Designated requirement (DR) must include `certificate leaf` (not cdhash-only). |
| Identity | Signing path uses the `ActivityLogger Code Signing` identity (same identity keeps TCC). |
| TCC | First-time grant targets the certificate-signed `.app` for Accessibility and Input Monitoring. |

**Forbidden:**

- launchd → `/usr/bin/python3` / `interleaved_logger.py` for production capture
- `exec` of `Contents/MacOS/ActivityLoggerNative` from launchd (bypass `open -W`)
- shipping an ad-hoc-signed `.app` after rebuild
- removing or weakening the rebuild script’s hard fail when DR lacks `certificate leaf`
- telling the user to re-grant TCC after a successful certificate-signed rebuild with the same `ActivityLogger Code Signing` identity

**References:** [`AGENTS.md`](../../AGENTS.md), [`docs/MACOS_TCC.md`](../MACOS_TCC.md)

### K2. Char-level keystrokes + hotkey encoding

| Rule | Requirement |
|------|-------------|
| Character keys | While not paused, printable characters append as themselves (char level, not word aggregates). |
| Enter | Append `\n[ENTER]\n`. |
| Tab | Append `[TAB]`. |
| Esc | Append `[ESC]`. |
| Space | Append a single space character. |
| Backspace | Remove the last buffered keystroke unit; do not append a marker. |
| Other `Key.*` | Ignore (do not append) unless listed above or handled as a modifier. |
| Modifiers | Track `CMD`, `CTRL`, `OPT`, `SHIFT` from left/right variants. |
| Hotkeys | If any modifier other than `SHIFT` alone is held, append `[{mods}+{CHAR}]` where `{mods}` is the held set joined by `+` in sorted order, and `{CHAR}` is upper-case. Example: Cmd+C → `[CMD+C]`. |
| Shift alone | Shift + printable char does **not** use bracket encoding; append the character as typed. |
| Pause | While privacy-paused, do not append keystrokes. |
| Pause edge | Entering pause clears the keystroke buffer **and** the held-modifier set. |

Do not replace char-level capture with OCR, screenshot, or audio transcription.

### K3. Secure pause + tests

| Rule | Requirement |
|------|-------------|
| Secure apps | Pause when app name or window title contains any substring in the locked set `SECURE_APPS`: `1password`, `bitwarden`, `keychain`, `keepass`, `lastpass`, `passwords` (case-insensitive). |
| Secure fields | AX secure fields trigger pause. |
| Events | `add_event` is a no-op while paused. |
| Clipboard | Clipboard changes during pause advance change markers but do not log clipboard content. |
| After unpause | Clipboard text that appeared only while paused must not log later. |
| Cache safety | A stale secure-field cache `False` must not clear an active field pause without a forced refresh. |

Do not shrink `SECURE_APPS` under F1–F6.  
Adding a name requires an explicit change to this file (and a new positive test).

Existing privacy tests in `tests/test_privacy_and_cleaner.py` are part of the F0 gate.  
They must stay green. New pause behavior needs new failing-first tests.

### K4. Markdown-only artifact

| Rule | Requirement |
|------|-------------|
| Primary log | User-facing capture writes `logs/daily_log_YYYY-MM-DD.md` only. |
| Directory | Log directory mode remains `0o700` when the logger creates or enforces it. |
| Flush | Durable file flush remains the persistence path for sections. |
| Failed write | If a body write fails, in-memory sections stay restored (no silent data drop). |

**Forbidden as user-facing storage:**

- JSONL files beside the daily log
- SQLite databases for daily transcripts
- binary media files as the log of record

### K5. Cleaner + Gemini prompt retained

| Rule | Requirement |
|------|-------------|
| Cleaner | Keep `clean_markdown_log.py` as the pre-LLM compress/clean step. |
| Prompt | Keep `prompts/gemini-automation-analysis.md` as the analysis prompt. |
| Redaction | Do not add a mandatory cleaner secret-redaction pass under F0–F6. |

Cleaner compression may change only when:

1. existing cleaner tests stay green, and  
2. the change does not add secret redaction.

### K6. Single-process Python capture core

| Rule | Requirement |
|------|-------------|
| Process model | Capture core remains one Python process inside the signed `.app`. |
| Threads/queues | In-process threads and queues are allowed. |
| Multi-process | Do not require a second long-running capture process, GUI app, or media daemon for core logging. |

Helper scripts (rebuild, cleaner, Launch Agent wrapper) stay outside the capture process.  
They are not a second capture pipeline.

---

## 4. AVOID — explicit bans (from `00-SCOPE.md`)

These items are out of product scope.  
Feature specs must not reintroduce them without a prior change to `00-SCOPE.md`.

### B1. No JPEG / audio / pipes platform

Do not build:

- continuous JPEG / screenshot capture
- microphone / audio capture
- named-pipe or multi-process media fan-out as a product surface

Another app covers that class of work. ActivityLogger does not.

### B2. No Screen Recording pipeline

Do not add Screen Recording TCC usage or a Screen Recording-based capture path.  
Accessibility + Input Monitoring for the signed `.app` remain the permission model.

### B3. No OCR fallback

Do not add OCR to recover text from pixels.  
AX / input-event paths remain the text sources.

### B4. Other locked non-goals

Do not add under F0–F6:

- JSONL / SQLite storage for daily user logs
- cleaner secret redaction pass
- locale / Ukrainian label changes
- broader ignore-lists for apps/windows as a platform feature
- local query API / MCP
- retention policy automation

---

## 5. Shared rules (summary)

1. No Screen Recording / mic / JPEG capture pipeline in ActivityLogger.  
2. Markdown-only storage for user-facing logs.  
3. Privacy pause for password managers and AX secure fields must not weaken.  
4. Production rebuild remains `./scripts/rebuild_and_restart.sh` with certificate leaf DR.  
5. Specs stay test-driven: acceptance criteria + failing-test list before implementation notes.

---

## 6. Acceptance criteria

A change set is F0-compliant only if all boxes pass.  
Each box maps to a test in §7 or a named manual check.

### AC-K1 Launch and signing

- [ ] `start_logger.sh` ends with `/usr/bin/open -W` on `ActivityLoggerNative.app` (`test_start_logger_uses_open_dash_w_on_app_bundle`).
- [ ] `start_logger.sh` does not `exec` `Contents/MacOS/ActivityLoggerNative` (`test_start_logger_does_not_exec_inner_macos_binary`).
- [ ] Launch Agent plist invokes `start_logger.sh` via bash; ProgramArguments has no `python3` / `interleaved_logger.py` (`test_launch_agent_plist_invokes_start_logger_not_python`).
- [ ] `scripts/rebuild_and_restart.sh` calls `scripts/sign_app.sh` and aborts when DR lacks `certificate leaf` (`test_rebuild_script_invokes_sign_app`, `test_rebuild_script_fails_without_certificate_leaf`).
- [ ] `AGENTS.md` and `docs/MACOS_TCC.md` still state: certificate-signed `.app` + `open -W`; do not re-grant TCC after same-identity cert rebuild (`test_tcc_docs_forbid_adhoc_and_python_launchd`).

### AC-K2 Keystrokes

- [ ] Printable chars append as characters while not paused (`test_on_press_appends_printable_char`).
- [ ] Enter / Tab / Esc use the markers in K2 (`test_on_press_encodes_enter_tab_esc_markers`).
- [ ] Non-Shift modifiers encode as sorted `[MOD+…+CHAR]` (`test_on_press_encodes_modifier_hotkey`).
- [ ] Paused state does not append keystrokes (`test_on_press_noop_when_paused`).
- [ ] Pause entry clears keystroke buffer and modifier set (`test_recompute_clears_keystrokes_on_pause_edge`, `test_recompute_clears_modifiers_on_pause_edge`).

### AC-K3 Secure pause

- [ ] `SECURE_APPS` still contains the locked six names (`test_secure_apps_set_locked_baseline`).
- [ ] Secure app name detection matches those substrings in app or title (`test_is_secure_app_name_positive_and_negative`).
- [ ] Secure-field pause still blocks events and keystrokes (`test_add_event_noop_when_paused`, `test_on_press_noop_when_paused`).
- [ ] Clipboard-during-pause does not leak after unpause (`test_clipboard_secret_not_logged_after_unpause`).
- [ ] Stale secure-field cache cannot clear pause without force refresh (`test_stale_cache_false_does_not_clear_pause_after_secure_mark`).
- [ ] Existing privacy tests in `tests/test_privacy_and_cleaner.py` pass.

### AC-K4 Markdown artifact

- [ ] Flush writes Markdown sections to `daily_log_*.md` (`test_get_filepath_is_daily_markdown_only`, `test_flush_success_clears_sections`).
- [ ] Log directory mode `0o700` remains enforced (`test_log_dir_mode_is_0o700`).
- [ ] Failed body write restores in-memory sections (`test_flush_restore_on_body_write_failure`).
- [ ] No new user-facing JSONL/SQLite/media log path (`test_no_jsonl_or_sqlite_writer_symbols_in_capture_module`).

### AC-K5 Cleaner and prompt

- [ ] `clean_markdown_log` remains importable with compress helpers (`test_cleaner_module_entrypoint_remains`).
- [ ] `prompts/gemini-automation-analysis.md` exists and is non-empty (`test_gemini_prompt_file_exists`).
- [ ] Cleaner public API has no mandatory secret-redaction stage (`test_cleaner_has_no_secret_redaction_pass`).

### AC-K6 Process model

- [ ] App / PyInstaller entry remains the single `interleaved_logger` capture core (`test_capture_core_is_single_module_process_entry`).
- [ ] No second Launch Agent capture binary; docs do not require a second always-on capture process (`test_no_second_capture_daemon_script_required`).

### AC-B Bans

- [ ] Capture module does not import Screen Recording / screenshot capture APIs as a logging path (`test_no_screen_recording_api_imports_in_capture_module`).
- [ ] Capture module does not open mic/audio recording for logging (`test_no_audio_capture_pipeline_in_capture_module`).
- [ ] Capture path does not require an OCR library (`test_no_ocr_pipeline_dependency_required_for_capture`).
- [ ] Feature specs for F1–F6 do not re-open banned items unless `00-SCOPE.md` changed first (reviewer check).

---

## 7. TDD regression suite outline

These tests guard F0.  
Names below are the contract.

**Order:** add any missing §7.2 test as a failing test first.  
Make it green before merging F1–F6 implementation that can break the rule.

### 7.1 Existing tests that must stay green

File: `tests/test_privacy_and_cleaner.py`

| Test name | Constraint |
|-----------|------------|
| `test_stale_cache_false_does_not_clear_pause_after_secure_mark` | K3 |
| `test_force_refresh_false_clears_field_pause` | K3 |
| `test_force_refresh_true_sets_field_pause` | K3 |
| `test_add_event_noop_when_paused` | K3 |
| `test_recompute_clears_keystrokes_on_pause_edge` | K2, K3 |
| `test_clipboard_while_paused_advances_markers_no_event` | K3 |
| `test_clipboard_secret_not_logged_after_unpause` | K3 |
| `test_clipboard_new_text_after_unpause_is_logged` | K3 |
| `test_is_secure_app_name_positive_and_negative` | K3 |
| `test_flush_restore_on_body_write_failure` | K4 |
| `test_flush_success_clears_sections` | K4 |
| `test_enqueue_ax_drops_on_full_without_raising` | K6 (in-process queue safety) |
| `test_enqueue_ax_coalesces_scans` | K6 |
| `test_intra_block_repeat_marker_always_ends_with_newline` | K5 |
| `test_traceback_stops_at_section_boundary` | K5 |
| `test_traceback_does_not_swallow_following_prose` | K5 |

Gate command for existing suite:

```bash
pytest -q tests/test_privacy_and_cleaner.py
```

### 7.2 Required new / explicit F0 guard tests

Add under `tests/` (preferred file: `tests/test_f0_constraints.py`).  
Static checks may read scripts and docs; they must not need a live TCC prompt.

#### Launch + signing + TCC docs (K1)

| Test name | Asserts |
|-----------|---------|
| `test_start_logger_uses_open_dash_w_on_app_bundle` | `start_logger.sh` contains `/usr/bin/open -W` and targets `ActivityLoggerNative.app`. |
| `test_start_logger_does_not_exec_inner_macos_binary` | Script does not `exec` `Contents/MacOS/ActivityLoggerNative`. |
| `test_launch_agent_plist_invokes_start_logger_not_python` | Plist ProgramArguments point at `start_logger.sh`; no `python3` / `interleaved_logger.py`. |
| `test_rebuild_script_fails_without_certificate_leaf` | `rebuild_and_restart.sh` contains a hard fail when DR lacks `certificate leaf`. |
| `test_rebuild_script_invokes_sign_app` | Rebuild path calls `scripts/sign_app.sh` after PyInstaller. |
| `test_tcc_docs_forbid_adhoc_and_python_launchd` | `AGENTS.md` and `docs/MACOS_TCC.md` still forbid ad-hoc production signing and launchd→Python capture; they still say same-identity cert rebuild does not need TCC re-grant. |

#### Keystrokes + hotkeys (K2)

| Test name | Asserts |
|-----------|---------|
| `test_on_press_appends_printable_char` | Char key appends the character while not paused. |
| `test_on_press_encodes_modifier_hotkey` | Non-Shift modifier + char becomes sorted `[MOD+CHAR]` (example: Cmd+C → `[CMD+C]`). |
| `test_on_press_encodes_enter_tab_esc_markers` | Enter / Tab / Esc match K2 markers. |
| `test_on_press_noop_when_paused` | No keystroke buffer growth while paused. |
| `test_recompute_clears_modifiers_on_pause_edge` | Entering pause clears the held-modifier set (not only keystrokes). |

#### Artifact + bans (K4, B1–B3)

| Test name | Asserts |
|-----------|---------|
| `test_get_filepath_is_daily_markdown_only` | Log path pattern is `daily_log_*.md`. |
| `test_log_dir_mode_is_0o700` | Logger sets or keeps log directory mode `0o700`. |
| `test_no_jsonl_or_sqlite_writer_symbols_in_capture_module` | `interleaved_logger.py` has no production JSONL/SQLite writer for daily logs. |
| `test_no_screen_recording_api_imports_in_capture_module` | Capture module does not import ScreenCaptureKit, `CGWindowListCreateImage`, or equivalent screenshot capture APIs as a logging path. |
| `test_no_audio_capture_pipeline_in_capture_module` | Capture module does not open mic/audio recording for logging. |
| `test_no_ocr_pipeline_dependency_required_for_capture` | Capture path does not import or require an OCR library (for example `pytesseract`, Vision OCR wrappers used for log text). |

#### Cleaner + prompt (K5)

| Test name | Asserts |
|-----------|---------|
| `test_gemini_prompt_file_exists` | `prompts/gemini-automation-analysis.md` exists and is non-empty. |
| `test_cleaner_module_entrypoint_remains` | `clean_markdown_log` remains importable with compress helpers. |
| `test_cleaner_has_no_secret_redaction_pass` | Cleaner public API does not add a mandatory secret-redaction stage. |

#### Secure-app set + process model (K3, K6)

| Test name | Asserts |
|-----------|---------|
| `test_secure_apps_set_locked_baseline` | `SECURE_APPS` contains at least the six locked names in K3. |
| `test_capture_core_is_single_module_process_entry` | `ActivityLoggerNative.spec` (or equivalent) still sets the app entry to `interleaved_logger` as the only capture script. |
| `test_no_second_capture_daemon_script_required` | No Launch Agent / plist besides `com.mk.activitylogger` starts a second capture binary; README/AGENTS do not require a second always-on capture process. |

Full F0 gate (after §7.2 exists):

```bash
pytest -q tests/test_privacy_and_cleaner.py tests/test_f0_constraints.py
```

### 7.3 Manual smoke (not pytest; required after rebuild)

| Check | Pass condition |
|-------|----------------|
| Certificate DR | `codesign -d -r- dist/ActivityLoggerNative.app` shows `certificate leaf`. |
| Capture | Typing grows `logs/daily_log_*.md` within ~30s. |
| TCC | After a same-identity certificate-signed rebuild, Accessibility / Input Monitoring still work without a new grant prompt. |

---

## 8. Rules for other feature specs

1. Every F1–F6 spec must include a section **F0 impact**.  
2. That section must state which KEEP items are touched and which AVOID items stay banned.  
3. Implementation notes come after acceptance criteria and the failing-test list.  
4. If a feature needs a banned item, update `00-SCOPE.md` first. Do not expand F0 quietly.  
5. Do not merge F1–F6 implementation until the F0 tests that cover touched KEEP/AVOID items are present and green.

---

## 9. Done definition for F0 itself

F0 is complete when:

- this document is the cited constraint contract for F1–F6
- `pytest -q tests/test_privacy_and_cleaner.py` stays green
- all §7.2 guard tests exist and pass
- no feature spec contradicts KEEP/AVOID without an explicit `00-SCOPE.md` change

---

## Critic revision log

**Verdict: ACCEPT**

**2026-08-15**

- Clarified F0 as constraint layer only; blocked product-scope creep into this file.
- Pinned K2 markers, hotkey format (`sorted` mods, Shift-alone rule), and pause-edge modifier clear.
- Pinned K3 `SECURE_APPS` baseline; forbid shrink under F1–F6.
- Made acceptance criteria map to named tests; replaced soft “docs still forbid…” with `test_tcc_docs_forbid_adhoc_and_python_launchd`.
- Narrowed pytest gates; required §7.2 before F1–F6 merges that can break F0.
- Added missing TDD guards: modifier clear, log dir `0o700`, locked `SECURE_APPS`, TCC doc contract, concrete Screen Recording / OCR import bans.
- Added manual TCC smoke: same-identity cert rebuild must not demand a new grant.
- Tightened K6 tests to PyInstaller entry + single Launch Agent / docs contract.
- Applied STE edits: shorter sentences, active voice, one rule per row where practical.
