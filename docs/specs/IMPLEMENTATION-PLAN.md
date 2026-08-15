# ActivityLogger F0–F6 Implementation Plan

**Status:** Implemented (FINAL_ACCEPT) — historical build order for F0→F2→F1→F3→F5→F4→F6. See [`IMPL-STATUS.md`](IMPL-STATUS.md).

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship F0–F6 capture improvements in the locked order (F0 → F2 → F1 → F3 → F5 → F4 → F6) while the capture core stays one Python process inside the certificate-signed `.app`.

**Architecture:** Keep `interleaved_logger.py` as the single-process entry. Extract small pure modules (`config.py`, optional `window_titles.py` helpers) and import them. Do not add a second capture daemon. Config authority is F2 only.

**Tech stack:** Python 3 (`tomllib` / `tomli`), pytest, pynput, AppKit/AX, PyInstaller `ActivityLoggerNative.app`, Launch Agent `start_logger.sh` → `open -W`.

**TDD rule:** For every task that adds or changes behavior, write the failing tests first. Run them and confirm FAIL for the right reason. Then implement the minimum code. Then re-run and confirm PASS. Do not merge feature code before its listed tests exist. Exception: Task F0.1 only re-runs the existing privacy suite (baseline; no new production code).

**Rebuild rule:** After any change that ships in the logger binary (`interleaved_logger.py`, new modules imported by it, `ActivityLoggerNative.spec`, or related bundle assets), finish with:

```bash
./scripts/rebuild_and_restart.sh
```

Confirm `codesign -d -r- dist/ActivityLoggerNative.app` shows `certificate leaf`. Smoke-check: typing grows `logs/daily_log_*.md` within ~30s (or configured `flush_interval_sec`). Do not leave an ad-hoc-signed `.app`. Do not ask for TCC re-grant after a same-identity certificate-signed rebuild. If you stop after a mid-phase task that already edited binary sources, run the rebuild before smoke or handoff (do not wait for the later phase-end rebuild step).

**Authority:** [`00-SCOPE.md`](00-SCOPE.md), [`00-MASTER.md`](00-MASTER.md), [`F2-config.md`](F2-config.md) for key names. Sibling specs F0–F6 for behavior.

---

## Canonical config keys (do not invent aliases)

Primary path: `~/.config/activitylogger/config.toml` (see F2 discovery order).

```toml
[paths]
log_dir = "~/scripts/activitylogger/logs"

[timing]
window_check_sec = 5
flush_interval_sec = 30
typing_pause_sec = 0.5
secure_field_cache_sec = 0.35
diag_min_interval_sec = 30.0

[privacy]
secure_apps = [
  "1password",
  "bitwarden",
  "keychain",
  "keepass",
  "lastpass",
  "passwords",
]

[ax]
ax_queue_maxsize = 16
ax_max_depth = 7
screen_compare_max_chars = 4000

[window_titles]
activitywatch_enricher = true
activitywatch_base_url = "http://localhost:5600"

[features]
browser_url_capture = false
capture_triggers_enabled = false
scroll_coalesce_enabled = false
scroll_coalesce_ms = 400
```

**Rejected aliases (do not ship):** `aw_enabled`, `aw_base_url`, `[activitywatch]`, `browser_url_enabled`, `typing_pause_ms`, `file_flush_sec`.

Env overrides (narrow): `ACTIVITYLOGGER_CONFIG` (path), `ACTIVITYLOGGER_LOG_DIR` → `paths.log_dir`.

---

## File map

| Path | Action | Role |
|------|--------|------|
| `config.py` | **Create** | Pure `AppConfig` + `load_config()`; no pynput |
| `window_titles.py` | **Create** (optional) | Native resolve + AW enricher helpers; import into logger |
| `browser_url.py` | **Create** (optional) | F4 URL helpers only; import into logger (no second process) |
| `interleaved_logger.py` | **Edit** | Wire config; F1–F6 behavior; stay single entry |
| `tests/test_f0_constraints.py` | **Create** | F0 §7.2 guards |
| `tests/test_config.py` | **Create** | TC-F2-* |
| `tests/test_window_titles.py` | **Create** | F1 resolve / heading / pause |
| `tests/test_flush_model.py` | **Create** | T-F3-* |
| `tests/test_capture_triggers.py` | **Create** | T-F5-* |
| `tests/test_browser_url.py` | **Create** | F4 URL emit / seal |
| `tests/test_scroll_coalesce.py` | **Create** | T-F6-* |
| `tests/test_privacy_and_cleaner.py` | **Edit** | Keep green; extend for F5 cleaner regex if needed |
| `start_logger.sh` | **Edit** | Resolve `REPO` from script dir; keep `open -W` |
| `com.mk.activitylogger.plist.template` | **Create** | Placeholders `@REPO@` |
| `com.mk.activitylogger.plist` | **Retire** | Stop shipping absolute machine paths; template + install only |
| `scripts/install_launch_agent.sh` | **Create** | Write machine-local plist |
| `config.example.toml` | **Create** (repo root) | Scaffold defaults |
| `docs/MACOS_TCC.md`, `AGENTS.md` | **Edit** | Config path + install notes; F0 doc contracts |
| `clean_markdown_log.py` | **Edit** (F5) | Accept trigger timestamp line |
| `prompts/gemini-automation-analysis.md` | **Edit** (F5) | Document trigger syntax (shipped; leave unchanged in docs-only passes) |
| `ActivityLoggerNative.spec` | **Edit** if needed | Bundle new modules; entry stays `interleaved_logger` |

**Do not create:** second Launch Agent, JSONL/SQLite writers, media capture modules, cleaner secret-redaction stage.

**Today (monolithic):** `interleaved_logger.py` (~716 lines) owns constants, pause, keys, AX, window loop, flush, main. Tests live mainly in `tests/test_privacy_and_cleaner.py`.

---

## Out of scope ([`00-SCOPE.md`](00-SCOPE.md))

- JSONL / SQLite sidecars
- Cleaner secret redaction pass
- Locale / Ukrainian label changes
- Broader ignore-lists for apps/windows
- Local query API / MCP
- Retention policy automation
- OCR fallback
- Screen Recording / mic / JPEG capture pipeline
- Second long-running capture process
- Hot reload of config (restart / kickstart only)

---

## Phase F0 — Constraint regression suite

### Task F0.1 — Existing privacy gate stays green

**Files:**
- Test: `tests/test_privacy_and_cleaner.py` (no new product code)

**TDD note:** Baseline only — re-run existing F0 §7.1 tests. Do not add feature code here.

**Step 1:** Run the existing suite (baseline).

```bash
pytest -q tests/test_privacy_and_cleaner.py
```

**Expected:** PASS (all cases listed in F0 §7.1).

**Step 2:** If any FAIL, fix only regressions; do not start F1–F6.

---

### Task F0.2 — Launch + signing + TCC doc guards

**Files:**
- Create: `tests/test_f0_constraints.py`
- Read-only: `start_logger.sh`, `scripts/rebuild_and_restart.sh`, `scripts/sign_app.sh`, Launch Agent plist / template, `AGENTS.md`, `docs/MACOS_TCC.md`, `ActivityLoggerNative.spec`

**Step 1 — Failing tests first** (names locked in F0 §7.2):

- `test_start_logger_uses_open_dash_w_on_app_bundle`
- `test_start_logger_does_not_exec_inner_macos_binary`
- `test_launch_agent_plist_invokes_start_logger_not_python`
- `test_rebuild_script_fails_without_certificate_leaf`
- `test_rebuild_script_invokes_sign_app`
- `test_tcc_docs_forbid_adhoc_and_python_launchd`

**Step 2 — Verify FAIL**

```bash
pytest -q tests/test_f0_constraints.py -k "start_logger or rebuild or tcc_docs or launch_agent"
```

**Expected:** FAIL until the new test file and assertions exist (import/collection failure or empty selection). After assertions exist against already-compliant scripts/docs, PASS is allowed. Still add every named guard before F1.

**Step 3 — Implement:** Only fix scripts/docs if a guard fails. Do not change TCC launch chain design.

**Step 4 — Verify**

```bash
pytest -q tests/test_f0_constraints.py -k "start_logger or rebuild or tcc_docs or launch_agent"
```

---

### Task F0.3 — Keystroke, artifact, ban, cleaner, process guards

**Files:**
- Modify: `tests/test_f0_constraints.py`
- Touch production only if a guard proves a real F0 break

**Step 1 — Failing tests first** (F0 §7.2 remaining names):

- K2: `test_on_press_appends_printable_char`, `test_on_press_encodes_modifier_hotkey`, `test_on_press_encodes_enter_tab_esc_markers`, `test_on_press_noop_when_paused`, `test_recompute_clears_modifiers_on_pause_edge`
- K4/B: `test_get_filepath_is_daily_markdown_only`, `test_log_dir_mode_is_0o700`, `test_no_jsonl_or_sqlite_writer_symbols_in_capture_module`, `test_no_screen_recording_api_imports_in_capture_module`, `test_no_audio_capture_pipeline_in_capture_module`, `test_no_ocr_pipeline_dependency_required_for_capture`
- K5: `test_gemini_prompt_file_exists`, `test_cleaner_module_entrypoint_remains`, `test_cleaner_has_no_secret_redaction_pass`
- K3/K6: `test_secure_apps_set_locked_baseline`, `test_capture_core_is_single_module_process_entry`, `test_no_second_capture_daemon_script_required`

**Step 2 — Verify FAIL then implement minimum fixes if needed.**

**Step 3 — Full F0 gate**

```bash
pytest -q tests/test_privacy_and_cleaner.py tests/test_f0_constraints.py
```

**Expected:** PASS. Do not start F2 until this gate is green.

**Rebuild:** Not required unless you changed logger binary sources.

---

## Phase F2 — Config load (canonical schema)

### Task F2.1 — `AppConfig` + defaults (TC-F2-01, 11, 18)

**Files:**
- Create: `config.py`
- Create: `tests/test_config.py`
- Create: `config.example.toml` at repo root (scaffold content = §6 defaults)

**Step 1 — Failing tests:** `TC-F2-01` defaults when file missing; `TC-F2-11` feature key round-trip; `TC-F2-18` no JSONL/SQLite fields on `AppConfig`.

**Step 2**

```bash
pytest -q tests/test_config.py -k "defaults or round_trip or no_jsonl"
```

**Expected:** FAIL (`load_config` / `AppConfig` missing).

**Step 3 — Implement:** dataclass + `load_config()` returning defaults when no file. Include all §6.2 keys with exact names. Reject alias names in schema (do not accept them as synonyms).

**Step 4**

```bash
pytest -q tests/test_config.py -k "defaults or round_trip or no_jsonl"
```

**Expected:** PASS.

---

### Task F2.2 — Discovery, env, failure matrix (TC-F2-02…07, 09, 12, 16, 17)

**Files:**
- Modify: `config.py`, `tests/test_config.py`

**Step 1 — Failing tests:** TC-F2-02 XDG `log_dir`; TC-F2-03 `ACTIVITYLOGGER_CONFIG` wins; TC-F2-04 tilde expand; TC-F2-05 invalid TOML fatal; TC-F2-06 validation ranges; TC-F2-07 unknown key warning; TC-F2-09 `ACTIVITYLOGGER_LOG_DIR`; TC-F2-12 missing `ACTIVITYLOGGER_CONFIG` fatal; TC-F2-16 frozen skips repo walk; TC-F2-17 unreadable discovered file fatal; TC-F2-19 `scroll_coalesce_ms` floor.

**Step 2 — Verify FAIL**

```bash
pytest -q tests/test_config.py -k "xdg or ACTIVITYLOGGER or tilde or invalid or validation or unknown or frozen or unreadable or scroll_coalesce"
```

**Expected:** FAIL (discovery/validation not implemented yet).

**Step 3 — Implement:** Discovery order F2 §7.1; value precedence §7.2; validation §6.4; fatal vs warn matrix §7.4.

**Step 4 — Verify PASS**

```bash
pytest -q tests/test_config.py -k "xdg or ACTIVITYLOGGER or tilde or invalid or validation or unknown or frozen or unreadable or scroll_coalesce"
```

**Expected:** PASS.

---

### Task F2.3 — `secure_apps` from config (TC-F2-08, 10)

**Files:**
- Modify: `config.py`, `tests/test_config.py`
- Later wire in F2.4: `interleaved_logger.py` uses loaded list

**Step 1 — Failing tests:** TC-F2-08 list override; TC-F2-10 explicit empty list.

```bash
pytest -q tests/test_config.py -k "secure_apps"
```

**Expected:** FAIL.

**Step 2 — Implement** list load + empty-explicit rule. AX secure-field pause stays on always.

**Step 3 — Verify PASS**

```bash
pytest -q tests/test_config.py -k "secure_apps"
```

**Expected:** PASS.

---

### Task F2.4 — Wire logger + launch install

**Files:**
- Modify: `interleaved_logger.py` — call `load_config()` once at startup; replace module constants with config values (`WINDOW_CHECK_SEC`, `FLUSH_INTERVAL_SEC`, `SECURE_APPS`, AX limits, `log_dir`, reserved feature keys)
- Modify: `start_logger.sh` — `REPO` from script directory / `ACTIVITYLOGGER_REPO`
- Create: `com.mk.activitylogger.plist.template`, `scripts/install_launch_agent.sh`
- Retire: checked-in `com.mk.activitylogger.plist` absolute paths (F2 §11); installs come from template only
- Modify: `docs/MACOS_TCC.md`, `AGENTS.md` (short config + install notes)
- Tests: TC-F2-14, TC-F2-15; optional TC-F2-13 permissions warning

**Step 1 — Failing tests** for shell/install first.

```bash
pytest -q tests/test_config.py -k "start_logger or install_template or permissions"
```

**Expected:** FAIL.

**Step 2 — Implement** wiring. Keep `open -W`. Launchd stdout/stderr under `$REPO/logs` only (not `paths.log_dir`). Retire hard-coded plist paths per F2 migration.

**Step 3 — Verify**

```bash
pytest -q tests/test_config.py tests/test_privacy_and_cleaner.py tests/test_f0_constraints.py
```

**Step 4 — Rebuild**

```bash
./scripts/rebuild_and_restart.sh
```

Confirm certificate leaf + log growth.

---

## Phase F1 — Native-first window titles

### Task F1.1 — Resolve API (native wins; AW fills empty)

**Files:**
- Create or extend: `window_titles.py` (preferred) **or** helpers inside `interleaved_logger.py`
- Create: `tests/test_window_titles.py`
- Modify: `interleaved_logger.py` — `window_checker_loop` / startup call resolver

**Step 1 — Failing tests:**

- `test_resolve_window_prefers_native_over_aw`
- `test_resolve_window_aw_fills_empty_native_title`
- `test_resolve_window_aw_fills_empty_native_app`
- `test_resolve_window_aw_does_not_override_native_app`
- `test_resolve_window_aw_down_uses_native_only`
- `test_resolve_window_aw_disabled_skips_http` (key: `window_titles.activitywatch_enricher`)
- `test_resolve_window_both_empty_returns_empty_pair`
- `test_resolve_window_ax_unavailable_allows_aw_fill`
- `test_get_active_window_no_longer_sole_source`

**Step 2**

```bash
pytest -q tests/test_window_titles.py -k "resolve_window or get_active_window_no_longer"
```

**Expected:** FAIL.

**Step 3 — Implement** F1 §6.1. Use config keys `activitywatch_enricher`, `activitywatch_base_url` only. Native wins on non-empty fields.

**Step 4**

```bash
pytest -q tests/test_window_titles.py -k "resolve_window or get_active_window_no_longer"
```

**Rebuild:** Required if stopping after this task (binary sources changed). Otherwise continue to F1.2 and rebuild there.

---

### Task F1.2 — Heading build + secure same-pair

**Files:**
- Modify: `window_titles.py` / `interleaved_logger.py`
- Modify: `tests/test_window_titles.py`

**Step 1 — Failing tests:**

- `test_heading_uses_unknown_window_not_aw_hint`
- `test_heading_uses_em_dash_separator`
- `test_fallback_heading_has_no_aw_instruction`
- `test_markdown_section_line_format`
- `test_both_empty_skips_heading_update`
- `test_secure_pause_from_native_app_name`
- `test_secure_pause_from_native_title_token`
- `test_non_secure_native_window_does_not_pause_by_name`
- `test_secure_pause_uses_same_pair_as_heading`

**Step 2**

```bash
pytest -q tests/test_window_titles.py -k "heading or secure_pause or markdown_section or both_empty"
```

**Step 3 — Implement** F1 §6.2 placeholders (`Unknown window`). Remove `AW_HINT` from default heading path. Same `(app, title)` for heading and `_is_secure_app_name` in one cycle.

**Step 4 — Verify + privacy regression**

```bash
pytest -q tests/test_window_titles.py tests/test_privacy_and_cleaner.py tests/test_f0_constraints.py
```

**Step 5 — Rebuild**

```bash
./scripts/rebuild_and_restart.sh
```

---

## Phase F3 — Typing-pause burst flush (no section seal)

### Task F3.1 — Idle flush keys → events only

**Files:**
- Modify: `interleaved_logger.py` (idle timer / monotonic check; use `timing.typing_pause_sec`)
- Create: `tests/test_flush_model.py`

**Step 1 — Failing tests:** T-F3-01…09 (happy path, continuous typing, backspace, hotkeys/ENTER).

```bash
pytest -q tests/test_flush_model.py -k "T_F3_0 or idle or backspace or hotkey or enter"
```

**Expected:** FAIL (no idle flush today).

**Step 2 — Implement:** After idle ≥ `typing_pause_sec` with no buffer-mutating key activity, run same join as `_flush_keys` into `_current_events`. **Do not** seal `_sections`. **Do not** write Markdown. **Do not** emit F5 trigger `typing_pause`.

**Step 3**

```bash
pytest -q tests/test_flush_model.py -k "T_F3_0"
```

**Rebuild:** Required if stopping after this task (binary sources changed). Otherwise continue to F3.2 and rebuild there.

---

### Task F3.2 — Pause discard + coordination

**Files:**
- Modify: `interleaved_logger.py`, `tests/test_flush_model.py`

**Step 1 — Failing tests:** T-F3-10…24 (pause discard, no resurrect, add_event order, window switch, file flush interval from config, key-flush cause `typing_pause` without section seal / without F5 section trigger `typing_pause`, concurrent lock cases).

```bash
pytest -q tests/test_flush_model.py
```

**Expected:** FAIL.

**Step 2 — Implement:** On pause edge, discard key buffer (existing behavior); cancel/ignore pending idle flush. Keep `flush_interval_sec` for durable file flush only. Internal key-flush cause may be `typing_pause` for tests (F3 FR-F3-015); never copy that name onto a sealed section as F5 trigger.

**Step 3 — Verify**

```bash
pytest -q tests/test_flush_model.py tests/test_privacy_and_cleaner.py tests/test_f0_constraints.py
```

**Step 4 — Rebuild**

```bash
./scripts/rebuild_and_restart.sh
```

---

## Phase F5 — Capture triggers (opt-in)

### Task F5.1 — Closed set + format helper (flag OFF first)

**Files:**
- Modify: `interleaved_logger.py` (section dict `trigger`; timestamp line helper)
- Create: `tests/test_capture_triggers.py`

**Step 1 — Failing tests:** T-F5-01 closed set; T-F5-02 reject unknown; T-F5-03 format helper; T-F5-14 reserved names include `typing_pause` unused; T-F5-16 flag OFF legacy `*{HH:MM:SS}*`; T-F5-17/18 flag OFF no click/clipboard seal.

Closed set only: `app_switch`, `click`, `clipboard`, `file_flush`, `url_change`, `scroll_coalesce`, `typing_pause` (reserved unused).

**Normative Markdown (flag ON):** `*{HH:MM:SS} · trigger:{name}*`

```bash
pytest -q tests/test_capture_triggers.py -k "closed or format or flag_off or reserved"
```

**Step 2 — Implement** helpers gated by `features.capture_triggers_enabled` (default false).

**Rebuild:** Required if stopping after this task (binary sources changed). Otherwise continue to F5.2 / F5.3 and rebuild at F5.3.

---

### Task F5.2 — Seal paths when flag ON

**Files:**
- Modify: `interleaved_logger.py` — seal on click/clipboard when ON; stamp `app_switch` / `file_flush`
- Modify: `tests/test_capture_triggers.py`

**Step 1 — Failing tests:** T-F5-04…09, T-F5-13.

```bash
pytest -q tests/test_capture_triggers.py -k "app_switch or file_flush or click or clipboard or round_trip or paused"
```

**Step 2 — Implement** seal causes. Initiating cause wins. Never emit `typing_pause` from F3 v1.

**Rebuild:** Required if stopping after this task (binary sources changed). Otherwise continue to F5.3 and rebuild there.

---

### Task F5.3 — Cleaner + Gemini + no rewrite

**Files:**
- Modify: `clean_markdown_log.py` (timestamp regex accepts legacy + trigger line)
- Modify: `prompts/gemini-automation-analysis.md` (done in feature ship; do not re-edit in docs-only work)
- Modify: `tests/test_capture_triggers.py`, possibly `tests/test_privacy_and_cleaner.py`

**Step 1 — Failing tests:** T-F5-10…12, T-F5-15, T-F5-19.

```bash
pytest -q tests/test_capture_triggers.py tests/test_privacy_and_cleaner.py
```

**Step 2 — Implement** parse accept both forms. Do not rewrite old log files.

**Step 3 — Full gate**

```bash
pytest -q tests/test_capture_triggers.py tests/test_flush_model.py tests/test_privacy_and_cleaner.py tests/test_f0_constraints.py
```

**Step 4 — Rebuild**

```bash
./scripts/rebuild_and_restart.sh
```

---

## Phase F4 — Browser URL capture (opt-in)

### Task F4.1 — Format, dedup, pause, flag OFF

**Files:**
- Create helpers in `interleaved_logger.py` or small `browser_url.py` imported by logger
- Create: `tests/test_browser_url.py`

**Step 1 — Failing tests:** `test_flag_off_never_emits`, `test_format_url_event_stable_prefix`, `test_emit_on_first_url`, `test_dedup_same_url`, `test_emit_on_url_change`, `test_paused_does_not_emit`, `test_paused_url_not_flushed_after_resume`, `test_empty_or_whitespace_url_rejected`, `test_url_longer_than_2000_truncated`, `test_is_browser_app_positive_negative`, `test_add_event_still_blocks_url_when_paused`, `test_config_key_is_browser_url_capture`, `test_no_screen_capture_imports_in_url_module`.

Event form: `> [URL]: {absolute_url}` — never inside `##` heading.

```bash
pytest -q tests/test_browser_url.py -k "flag_off or format or emit or dedup or paused or browser_app or config_key or no_screen"
```

**Step 2 — Implement** observation helpers. Gate on `features.browser_url_capture` only.

**Rebuild:** Required if stopping after this task (binary sources changed). Otherwise continue to F4.2 and rebuild there.

---

### Task F4.2 — Provider + window-loop wire + F5 seal

**Files:**
- Modify: URL provider (AX then Apple Events); `window_checker_loop`
- Modify: `tests/test_browser_url.py`

**Step 1 — Failing tests:** provider preference/fallback/failure; `test_url_event_lands_under_current_heading`; `test_title_and_url_same_cycle_url_under_new_heading`; `test_flag_off_window_loop_skips_provider`; `test_f4_alone_does_not_write_trigger_metadata`; `test_f4_with_f5_seals_url_change`; `test_secure_app_match_unchanged_with_url_helper`.

**Seal ownership (locked):** F5 OFF → URL event line only. F4 ON + F5 ON → F4 seals after URL emit with trigger `url_change`.

```bash
pytest -q tests/test_browser_url.py
```

**Step 2 — Implement.** Fail soft on Automation deny. No Screen Recording / OCR.

**Step 3 — Verify**

```bash
pytest -q tests/test_browser_url.py tests/test_capture_triggers.py tests/test_window_titles.py tests/test_f0_constraints.py
```

**Step 4 — Rebuild**

```bash
./scripts/rebuild_and_restart.sh
```

---

## Phase F6 — Scroll coalescing (opt-in)

### Task F6.1 — Coalesce burst + format

**Files:**
- Modify: `interleaved_logger.py` (optional `on_scroll` when enabled)
- Create: `tests/test_scroll_coalesce.py`

**Step 1 — Failing tests:** T-F6-01 default off; T-F6-02 one note; T-F6-03 quiet reset; T-F6-06 no `on_move`; T-F6-09 format contract (`🖱️ **Scroll:** {n} ticks, net {dir}`).

Keys: `features.scroll_coalesce_enabled` (default false), `features.scroll_coalesce_ms` (default 400).

```bash
pytest -q tests/test_scroll_coalesce.py -k "default_off or coalesce or quiet or move or format"
```

**Step 2 — Implement** burst state + quiet flush. Prefer not to attach `on_scroll` when disabled.

**Rebuild:** Required if stopping after this task (binary sources changed). Otherwise continue to F6.2 and rebuild there.

---

### Task F6.2 — Pause, app switch, F5 trigger, shutdown

**Files:**
- Modify: `interleaved_logger.py`, `tests/test_scroll_coalesce.py`

**Step 1 — Failing tests:** T-F6-04 pause discard; T-F6-05 app-switch flush prior section; T-F6-07 trigger `scroll_coalesce` when F5 ON; T-F6-08 pause gate; T-F6-10 delivery failure soft; T-F6-11 shutdown/file flush; T-F6-12 no screenshot/scan.

```bash
pytest -q tests/test_scroll_coalesce.py
```

**Step 2 — Implement** seal like click: flush keys → append scroll line → seal. Trigger name exact `scroll_coalesce` when F5 ON.

**Step 3 — Full suite**

```bash
pytest -q tests/
```

**Step 4 — Rebuild**

```bash
./scripts/rebuild_and_restart.sh
```

Confirm certificate leaf + smoke typing (and optional scroll with flag ON).

---

## Cross-cutting verify checklist (after each binary phase)

1. `pytest -q tests/test_privacy_and_cleaner.py tests/test_f0_constraints.py` stays green.
2. `./scripts/rebuild_and_restart.sh` completed; DR has `certificate leaf`.
3. Typing grows daily Markdown under configured `log_dir`.
4. No rejected config aliases shipped.
5. No out-of-scope media / JSONL / SQLite / second capture process.

---

## Suggested commit cadence (when user asks for commits)

1. `test(f0): add constraint regression suite`
2. `feat(f2): load XDG TOML config and install template`
3. `feat(f1): native-first window titles with AW enricher`
4. `feat(f3): typing-pause flush keys into events`
5. `feat(f5): opt-in capture trigger metadata`
6. `feat(f4): opt-in browser URL events and url_change seal`
7. `feat(f6): opt-in scroll coalescing`

Do not commit unless the operator asks.

---

## Document control

- Plan ID: IMPLEMENTATION-PLAN
- Path: `docs/specs/IMPLEMENTATION-PLAN.md`
- Spec order: F0 → F2 → F1 → F3 → F5 → F4 → F6 ([`00-MASTER.md`](00-MASTER.md) §7)
- Config authority: [`F2-config.md`](F2-config.md)
- Scope: [`00-SCOPE.md`](00-SCOPE.md)

---

## Checker revision log

**2026-08-15 — plan checker**

| Check | Result |
|-------|--------|
| Order F0→F2→F1→F3→F5→F4→F6 | Pass (phases + goal + commits already matched MASTER §7) |
| Canonical config keys / rejected aliases | Pass (snippet matched MASTER; no aliases as primary) |
| TDD failing-first per task | Fixed: F0.1 marked baseline exception; F0.2 FAIL wording tightened; F2.2/F2.3 split Verify FAIL → Implement → PASS |
| `rebuild_and_restart.sh` after binary changes | Fixed: mid-phase stop/handoff rebuild note; rebuild reminders on F1.1, F3.1, F5.1/F5.2, F4.1, F6.1 |
| Out of scope respected | Pass (SCOPE ignore list + media/second process; no scope expansion tasks) |
| File map single-process | Fixed: optional `browser_url.py` import-only; retire absolute `com.mk.activitylogger.plist` in F2.4 / file map |
| F3 × F5 `typing_pause` | Fixed: F3.2 clarifies key-flush cause vs F5 section trigger |

**Verdict: PLAN_ACCEPT**
