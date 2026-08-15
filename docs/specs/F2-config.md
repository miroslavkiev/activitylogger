# F2 — Config file for paths and tunables (TDD)

**Status:** Spec only (no implementation in this change)  
**Priority:** P0  
**Scope contract:** [`00-SCOPE.md`](00-SCOPE.md)  
**Depends on / coordinates with:** F1, F3–F6 (F2 owns key names; other specs must use this schema)  
**F0:** Keep TCC launch chain, Markdown-only logs, and privacy pause.

---

## 1. Summary

Replace hard-coded paths and capture tunables with one TOML config file.

**Primary path:** `~/.config/activitylogger/config.toml` (XDG).

The signed `.app` must load that user file from outside the bundle.  
Launch Agent install must not keep a hard-coded `/Users/mk/scripts/activitylogger` path in checked-in install artifacts.

Code defaults must match today’s constants. Behavior stays the same until the user edits config.

Config is read once at process start. After a config edit, restart the agent (kickstart). No hot reload in F2.

---

## 2. Problem / current behavior

| Area | Current behavior |
|------|------------------|
| Log directory | `_resolve_log_dir()` always uses `$HOME/scripts/activitylogger/logs` |
| Tunables | Module constants in `interleaved_logger.py` |
| Secure apps | Hard-coded set of name substrings |
| AX text walk | Hard-coded max depth `7` in `extract_text` |
| Launch wrapper | `start_logger.sh` sets `REPO="${HOME}/scripts/activitylogger"` and `HOME` fallback `/Users/mk` |
| Launch Agent | `com.mk.activitylogger.plist` embeds absolute `/Users/mk/scripts/activitylogger` paths |
| Cleaner | Separate tunables in `clean_markdown_log.py` (out of F2) |
| Feature roadmap | No stable keys for F1 / F3–F6 |

Problems:

1. Rebuild or repo move needs code or plist edits.
2. Tunable changes need a certificate-signed rebuild for production.
3. Other machines cannot reuse the checked-in Launch Agent plist.
4. F1–F6 need stable config keys before those features land.

---

## 3. Goals / Non-goals

### Goals

- One TOML schema for capture paths, intervals, secure-app list, AX limits, and F1/F3–F6 keys.
- Deterministic load order. Safe behavior when the file is missing or invalid.
- Bundled `ActivityLoggerNative.app` finds config without paths baked into the signed bundle.
- Launch Agent + `start_logger.sh` migration off hard-coded `/Users/mk/...`.
- Pytest-first: failing tests exist before production wiring.

### Non-goals

- JSONL / SQLite / retention / MCP (see `00-SCOPE.md`).
- Any second log format or config-driven sidecar. Markdown daily logs only.
- Cleaner (`clean_markdown_log.py`) keys in this feature.
- Default `config.toml` inside the `.app` as the only source of truth.
- GUI settings UI.
- Hot reload of config without process restart.
- Broader ignore-lists beyond the existing secure-app substring list.
- Changing secure-field AX pause rules (only the secure-app **list** becomes configurable).
- Screen Recording / mic / JPEG (forbidden by scope).

---

## 4. User stories

1. As the operator, I set `log_dir` so daily Markdown lands where I choose, without editing Python.
2. As the operator, I change `window_check_sec` and `flush_interval_sec` in the TOML file, then restart the agent.
3. As the operator, I add or remove secure-app name substrings when I install a new password manager.
4. As the operator, I enable F4 later with `browser_url_capture = true`, and F5 with `capture_triggers_enabled = true`, without a second config format.
5. As a maintainer, I install the Launch Agent with a script that writes paths from the repo root, not from a committed `/Users/mk/...` string.
6. As a developer, I set `ACTIVITYLOGGER_CONFIG` to a temp file in tests and CI.

---

## 5. Functional requirements

### FR-F2-001 — Config format and primary path

The product SHALL use TOML for configuration.

**Primary path:**

- `$XDG_CONFIG_HOME/activitylogger/config.toml`
- If `XDG_CONFIG_HOME` is unset: `~/.config/activitylogger/config.toml`

**Why not project-root as primary:**

- The signed `.app` must not depend on the repo directory for user settings.
- Rebuild via `./scripts/rebuild_and_restart.sh` replaces `dist/`; user settings must survive.
- XDG works with Launch Agents that only know `$HOME`.

**Optional secondary (dev only):** `<repo>/config.toml` — see §7. Never required for production Launch Agent.

### FR-F2-002 — Keys covered in F2

Config SHALL cover exactly the key groups in §6 (no extra product surfaces).

| Key group | Purpose |
|-----------|---------|
| `paths.log_dir` | Daily Markdown + in-app diagnostics + instance lock |
| `timing.*` | Poll / flush / cache / diag intervals |
| `privacy.secure_apps` | Substring list for secure-app pause |
| `ax.*` | AX worker and text-walk limits |
| `window_titles.*` | F1 ActivityWatch enricher |
| `features.*` | F4 / F5 / F6 flags and tunables |

F5 uses `features.capture_triggers_enabled` (default `false`).  
New seal cadence (click / clipboard seals + trigger tokens) is opt-in.

### FR-F2-003 — Defaults match current constants

When no config file exists, runtime values SHALL equal current code defaults (§6.2).

### FR-F2-004 — Bundled app discovery

`ActivityLoggerNative.app` SHALL resolve config as follows:

1. Read `ACTIVITYLOGGER_CONFIG` if set and non-empty.
2. Else read the XDG path under the real user home (`HOME`, else `pwd.getpwuid`, same spirit as today’s log-dir home resolution).
3. SHALL NOT require a `config.toml` inside `Contents/Resources` for normal operation.
4. SHALL NOT walk the filesystem for a repo `config.toml` when running frozen (`sys.frozen`).
5. Repo `config.toml` MAY apply only on **source** runs per §7 steps 3–4.

`start_logger.sh` MAY export `HOME` and MAY export `ACTIVITYLOGGER_CONFIG` if the operator sets it.  
It MUST NOT bake `/Users/mk` into committed defaults. Use a generic `$HOME` requirement only.

### FR-F2-005 — Launch Agent path migration

Checked-in install artifacts MUST NOT be the long-term source of `/Users/mk/scripts/activitylogger`.

Required migration:

1. Add `scripts/install_launch_agent.sh` that:
   - Detects repo root from the script location, or accepts `ACTIVITYLOGGER_REPO`.
   - Writes `~/Library/LaunchAgents/com.mk.activitylogger.plist` with absolute paths from install time.
   - Points `ProgramArguments` at `$REPO/start_logger.sh`.
   - Sets `WorkingDirectory` to `$REPO`.
   - Sets stdout/stderr to `$REPO/logs/launchd-stdout.log` and `$REPO/logs/launchd-stderr.log`.
2. Keep a **template** plist in the repo (e.g. `com.mk.activitylogger.plist.template`) with placeholders such as `@REPO@`, not a personal absolute path.
3. `start_logger.sh` resolves `REPO` from the script directory (`cd "$(dirname "$0")" && pwd`), with optional override `ACTIVITYLOGGER_REPO`.
4. Document one-time: unload old agent, run install script, load new plist.

**Launchd vs capture log_dir:**  
Install script MUST NOT read `paths.log_dir` to place launchd stdout/stderr.  
Wrapper and launchd logs stay under `$REPO/logs`.  
`paths.log_dir` affects only in-app daily Markdown, diagnostics, and the instance lock.

### FR-F2-006 — Failure behavior

| Condition | Behavior |
|-----------|----------|
| No config file discovered | Use defaults; continue; one info line (`config: using defaults`) |
| `ACTIVITYLOGGER_CONFIG` set, missing or unreadable | Fatal |
| Discovered file (XDG or repo) exists but unreadable | Fatal |
| Invalid TOML syntax | Fatal (path + parse error) |
| Validation error (type or range) | Fatal (name the key); whole file rejected |
| Unknown keys | Ignore; one warning listing unknown keys; continue |
| Cannot create `log_dir` | Fatal |

Do not coerce invalid values into “safe-looking” numbers.  
Empty `secure_apps = []` is allowed only when the user sets that list explicitly. AX secure-field detection stays on.

### FR-F2-007 — Apply without changing TCC identity

Config loading is pure file I/O in-process.  
It MUST NOT change how launchd starts the app (`open -W` via `start_logger.sh`).  
Certificate-signed rebuild rules in `AGENTS.md` / `docs/MACOS_TCC.md` stay unchanged.

### FR-F2-008 — Module API for tests

Provide a small load API (name flexible), e.g. `load_config(path: Path | None = None) -> AppConfig`, used by the logger at startup and by pytest without starting listeners.

### FR-F2-009 — Markdown-only storage

Config MUST NOT introduce JSONL, SQLite, or any second user-facing log format.  
`log_dir` holds Markdown daily logs plus existing text diagnostics and the lock file only.

### FR-F2-010 — Read once at startup

Load config once when the process starts.  
A later edit to the TOML file has no effect until process restart (agent kickstart).

---

## 6. Config schema

**Authority:** This section locks key names for F1–F6. Sibling specs must use these names.

### 6.1 Complete example (defaults = current behavior + reserved feature keys)

File: `~/.config/activitylogger/config.toml`

```toml
# ActivityLogger capture config (F2)
# Paths may be absolute or start with ~/

[paths]
# Default today: $HOME/scripts/activitylogger/logs
log_dir = "~/scripts/activitylogger/logs"

[timing]
window_check_sec = 5
flush_interval_sec = 30
# F3 — typing idle before burst flush (unused until F3)
typing_pause_sec = 0.5
secure_field_cache_sec = 0.35
diag_min_interval_sec = 30.0

[privacy]
# Substrings matched against lowercased app name and window title
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
# F1 — ActivityWatch optional enricher (native titles first)
activitywatch_enricher = true
activitywatch_base_url = "http://localhost:5600"

[features]
# F4 — optional browser URL capture (off until F4 ships)
browser_url_capture = false
# F5 — capture-trigger metadata + click/clipboard seals (opt-in)
capture_triggers_enabled = false
# F6 — scroll coalescing (off until F6 ships)
scroll_coalesce_enabled = false
scroll_coalesce_ms = 400
```

### 6.2 Default table (code must match)

| TOML key | Current constant / behavior | Default |
|----------|----------------------------|---------|
| `paths.log_dir` | `_resolve_log_dir()` | `$HOME/scripts/activitylogger/logs` |
| `timing.window_check_sec` | `WINDOW_CHECK_SEC` | `5` |
| `timing.flush_interval_sec` | `FLUSH_INTERVAL_SEC` | `30` |
| `timing.typing_pause_sec` | F3 (not used yet) | `0.5` |
| `timing.secure_field_cache_sec` | `SECURE_FIELD_CACHE_SEC` | `0.35` |
| `timing.diag_min_interval_sec` | `_DIAG_MIN_INTERVAL` | `30.0` |
| `privacy.secure_apps` | `SECURE_APPS` | list in §6.1 |
| `ax.ax_queue_maxsize` | `AX_QUEUE_MAXSIZE` | `16` |
| `ax.ax_max_depth` | hard-coded `depth > 7` | `7` |
| `ax.screen_compare_max_chars` | `SCREEN_COMPARE_MAX_CHARS` | `4000` |
| `window_titles.activitywatch_enricher` | F1; today AW always attempted | `true` |
| `window_titles.activitywatch_base_url` | `AW_BASE_URL` | `http://localhost:5600` |
| `features.browser_url_capture` | F4 | `false` |
| `features.capture_triggers_enabled` | F5 | `false` |
| `features.scroll_coalesce_enabled` | F6 | `false` |
| `features.scroll_coalesce_ms` | F6 | `400` |

**Removed / rejected aliases (do not ship):**

| Rejected name | Reason |
|---------------|--------|
| `aw_enabled` / `aw_base_url` / `[activitywatch]` | Use `[window_titles]` keys above |
| `browser_url_enabled` | Canonical name is `browser_url_capture` |
| `typing_pause_ms` | Canonical name is `typing_pause_sec` (default `0.5`) |
| `file_flush_sec` | Duplicate of `flush_interval_sec`; F3 uses one key |
| `scroll_coalesce_ms = 250` | Canonical default is `400` |

### 6.3 Coordination keys (other features)

| Feature | Keys | F2 duty |
|---------|------|---------|
| **F1** | `activitywatch_enricher`, `activitywatch_base_url` | Define + load; F1 implements native-first; enricher runs only when true |
| **F3** | `typing_pause_sec`, `flush_interval_sec` | Define defaults; until F3, only `flush_interval_sec` drives the flush thread |
| **F4** | `browser_url_capture` | Default `false`; F4 no-ops when false |
| **F5** | `capture_triggers_enabled` | Default `false`; F5 owns Markdown trigger syntax; no-ops when false |
| **F6** | `scroll_coalesce_enabled`, `scroll_coalesce_ms` | Default off; F6 no-ops when disabled |

### 6.4 Validation rules

- `window_check_sec >= 1`
- `flush_interval_sec >= 1`
- `typing_pause_sec >= 0.05`
- `secure_field_cache_sec >= 0`
- `diag_min_interval_sec >= 1`
- `ax_queue_maxsize >= 1`
- `ax_max_depth` in `1..32`
- `screen_compare_max_chars >= 100`
- `scroll_coalesce_ms` in `50..5000`
- `activitywatch_base_url` non-empty; must start with `http://` or `https://`
- `log_dir` after `~` expand must be absolute; create with mode `0700` when used (same as today)
- Booleans must be TOML booleans, not strings
- `secure_apps` must be a list of strings (may be empty if explicit)

---

## 7. Loading order / precedence / failure behavior

### 7.1 Discovery order (which file)

Resolve **one** config file path:

1. If `ACTIVITYLOGGER_CONFIG` is set → that path (must exist and be readable, or fatal).
2. Else if `$XDG_CONFIG_HOME/activitylogger/config.toml` exists → use it  
   (`XDG_CONFIG_HOME` default `~/.config`).
3. Else if `ACTIVITYLOGGER_REPO` is set and `$ACTIVITYLOGGER_REPO/config.toml` exists → use it.
4. Else if **not frozen** (source run): walk parents from `interleaved_logger.py` / project root; if a directory contains both `config.toml` and (`ActivityLoggerNative.spec` or `.git`) → use that `config.toml`.
5. Else → no file (defaults only).

**Production Launch Agent:** use step 2 (XDG). Do not depend on step 3 or 4 for the signed app.

### 7.2 Value precedence

For each key:

1. Built-in defaults (§6.2).
2. Values from the single resolved TOML file (override defaults).
3. Optional env overrides (narrow set only):
   - `ACTIVITYLOGGER_LOG_DIR` → overrides `paths.log_dir`
   - `ACTIVITYLOGGER_CONFIG` is path-only (not a value dump)

No merge of multiple TOML files in v1.  
If both XDG and repo files exist, discovery picks **one** file; XDG wins when `ACTIVITYLOGGER_CONFIG` is unset (step 2 before step 3/4).

### 7.3 Startup logging

On start, write one diagnostics line with:

- `config_path=<path|defaults>`
- `log_dir=<resolved>`
- selected feature booleans only (`activitywatch_enricher`, `browser_url_capture`, `capture_triggers_enabled`, `scroll_coalesce_enabled`)

Do not dump the full `secure_apps` list into diagnostics by default.

### 7.4 Failure matrix

| Condition | Behavior |
|-----------|----------|
| No file | Defaults; continue |
| `ACTIVITYLOGGER_CONFIG` set, missing/unreadable | Fatal |
| Discovered file unreadable | Fatal |
| Parse error | Fatal |
| Validation error | Fatal with key name |
| Unknown key | Warn once; continue |
| Cannot create `log_dir` | Fatal |

---

## 8. Privacy / security (config file permissions)

1. Recommended mode for `~/.config/activitylogger/`: `0700`.
2. Recommended mode for `config.toml`: `0600`.
3. Install / first-run helper SHOULD create the directory and a default file with those modes when the operator asks to scaffold config.
4. If the config file is group- or world-readable, log a **warning** (do not refuse by default). Document that `secure_apps` and paths are sensitive operational data.
5. Do not write secrets into config. `activitywatch_base_url` is local only.
6. `log_dir` remains `0700` as today.
7. Config must not weaken secure-field pause. Empty `secure_apps` only if the user sets `secure_apps = []` (AX secure-field detection stays on).

---

## F0 impact

| F0 item | F2 effect |
|---------|-----------|
| K1 Launch + signing | Untouched runtime chain. Install script must keep `open -W`. |
| K2 Keystrokes | Untouched. |
| K3 Secure pause | Touched list only: `privacy.secure_apps` becomes configurable; empty list allowed only when explicit. Secure-field pause stays on. |
| K4 Markdown-only | Enforced: no JSONL/SQLite config fields (FR-F2-009). |
| K5 Cleaner + prompt | Untouched (cleaner keys out of F2). |
| K6 Single-process | Untouched. |
| B1–B4 Bans | Stay banned. |

---

## 9. Acceptance criteria

1. With no config file, capture intervals, `log_dir`, `secure_apps`, and AX depth match pre-F2 behavior.
2. An XDG `config.toml` that sets `log_dir` to a temp path causes new `daily_log_*.md` writes there after restart.
3. Changing `window_check_sec` / `flush_interval_sec` in config changes loaded values (unit tests); production picks them up after agent restart.
4. `secure_apps` from config drives `is_secure_context`-style matching (privacy tests inject config).
5. Signed app + Launch Agent still use `start_logger.sh` → `open -W`; config load does not exec the inner binary.
6. Checked-in repo no longer requires `/Users/mk/scripts/activitylogger` in the **installed** plist; template + install script produce machine-local paths.
7. `start_logger.sh` resolves repo from its own location (or `ACTIVITYLOGGER_REPO`), not a hard-coded user home name.
8. Invalid TOML or failed validation prevents startup with a clear error.
9. F1 / F3 / F4 / F5 / F6 keys in §6 parse and round-trip even if those features are not implemented yet.
10. `AppConfig` exposes no JSONL/SQLite path fields.
11. Frozen discovery never uses repo walk (step 4).
12. Pytest cases in §10 exist and pass after implementation (write as failing tests first).

---

## 10. Test plan (TDD)

Target module ideas: `activitylogger_config.py` or `config.py` next to the logger; tests under `tests/test_config.py`. Use `tmp_path` and `monkeypatch` for env and home.

### TC-F2-01 — Defaults when file missing

- **Given** no `ACTIVITYLOGGER_CONFIG`, no XDG file, no repo file  
- **When** `load_config()` runs  
- **Then** `log_dir` resolves to `$HOME/scripts/activitylogger/logs`, `window_check_sec == 5`, `flush_interval_sec == 30`, `typing_pause_sec == 0.5`, `secure_apps` equals today’s set, `ax_max_depth == 7`, `activitywatch_enricher is True`, `browser_url_capture is False`, `capture_triggers_enabled is False`, `scroll_coalesce_enabled is False`, `scroll_coalesce_ms == 400`

### TC-F2-02 — XDG file overrides log_dir

- **Given** `XDG_CONFIG_HOME=tmp/xdg` and `activitylogger/config.toml` with `log_dir = "<tmp>/mylogs"`  
- **When** config loads  
- **Then** resolved `log_dir` is that path (tilde/`~` tested in TC-F2-04)

### TC-F2-03 — ACTIVITYLOGGER_CONFIG wins over XDG

- **Given** both an XDG file and `ACTIVITYLOGGER_CONFIG` pointing at another file with different `flush_interval_sec`  
- **When** config loads  
- **Then** values come from `ACTIVITYLOGGER_CONFIG` only

### TC-F2-04 — Tilde expansion

- **Given** `log_dir = "~/custom/alogs"` and `HOME` set to `tmp/home`  
- **When** config loads  
- **Then** resolved path is `tmp/home/custom/alogs`

### TC-F2-05 — Invalid TOML fatal

- **Given** `ACTIVITYLOGGER_CONFIG` points to a file with broken TOML  
- **When** `load_config()` runs  
- **Then** it raises a clear error (or returns a Result type that main treats as fatal); does not return defaults silently

### TC-F2-06 — Validation ranges

- **Given** `window_check_sec = 0`  
- **When** config loads  
- **Then** validation error names `window_check_sec`

### TC-F2-07 — Unknown key warning

- **Given** TOML with `features.not_a_real_flag = true`  
- **When** config loads  
- **Then** load succeeds; warning hook/log records unknown key

### TC-F2-08 — secure_apps from config

- **Given** `secure_apps = ["vaultwarden"]` only  
- **When** privacy helper uses loaded config  
- **Then** app name containing `vaultwarden` pauses; `1password` alone does not

### TC-F2-09 — Env log_dir override

- **Given** config file `log_dir = "/from/file"` and `ACTIVITYLOGGER_LOG_DIR=/from/env`  
- **When** config loads  
- **Then** resolved log dir is `/from/env`

### TC-F2-10 — Explicit empty secure_apps

- **Given** `secure_apps = []`  
- **When** config loads  
- **Then** loaded list is empty (AX secure-field path still unit-tested elsewhere as unchanged)

### TC-F2-11 — Feature key round-trip

- **Given** TOML sets `activitywatch_enricher = false`, `browser_url_capture = true`, `capture_triggers_enabled = true`, `scroll_coalesce_enabled = true`, `scroll_coalesce_ms = 100`, `typing_pause_sec = 0.8`  
- **When** config loads  
- **Then** all values match (even if F1/F3–F6 code paths ignore them for now)

### TC-F2-12 — Missing ACTIVITYLOGGER_CONFIG path

- **Given** `ACTIVITYLOGGER_CONFIG` set to a non-existent path  
- **When** config loads  
- **Then** fatal error (not defaults)

### TC-F2-13 — Permissions warning (optional unit)

- **Given** config file mode `0644`  
- **When** config loads  
- **Then** load succeeds and a warning is emitted about permissions

### TC-F2-14 — start_logger repo resolution (shell or subprocess test)

- **Given** `start_logger.sh` lives under a temp repo copy with `dist/ActivityLoggerNative.app` stub dir  
- **When** script resolves `REPO`  
- **Then** `REPO` equals the script’s parent directory, not a hard-coded `/Users/mk/scripts/activitylogger`

### TC-F2-15 — Install template substitution

- **Given** plist template with `@REPO@`  
- **When** install script runs with `REPO=/tmp/al`  
- **Then** output plist contains `/tmp/al` and does not contain the literal `@REPO@` or `/Users/mk/scripts/activitylogger`  
- **And** launchd stdout/stderr paths are under `/tmp/al/logs/`, not under a custom `paths.log_dir`

### TC-F2-16 — Frozen app skips repo walk

- **Given** frozen mode simulated (`sys.frozen` true), no `ACTIVITYLOGGER_CONFIG`, no XDG file, and a repo `config.toml` that would match step 4 on a source run  
- **When** config loads  
- **Then** defaults apply (repo file ignored)

### TC-F2-17 — Unreadable discovered file is fatal

- **Given** XDG config path exists but is unreadable  
- **When** config loads  
- **Then** fatal error (not defaults)

### TC-F2-18 — No JSONL/SQLite surface

- **Given** default or example config  
- **When** `load_config()` returns `AppConfig`  
- **Then** the object has no fields that point at `.jsonl` or `.sqlite` log sidecars

### TC-F2-19 — scroll_coalesce_ms floor

- **Given** `scroll_coalesce_ms = 10`  
- **When** config loads  
- **Then** validation error names `scroll_coalesce_ms`

---

## 11. Migration plan for existing install

1. **Ship code** that loads XDG config with defaults identical to today (behavior-neutral).
2. **Scaffold (optional):**  
   `mkdir -p ~/.config/activitylogger && cp docs/examples/config.default.toml ~/.config/activitylogger/config.toml && chmod 700 ~/.config/activitylogger && chmod 600 ~/.config/activitylogger/config.toml`  
   (create the example file during implementation.)
3. **Rebuild** with `./scripts/rebuild_and_restart.sh` so the signed app includes the loader.
4. **Replace Launch Agent paths:**
   - `launchctl bootout gui/$(id -u)/com.mk.activitylogger` (or unload equivalent).
   - Run `scripts/install_launch_agent.sh`.
   - `launchctl bootstrap` / `enable` / `kickstart` as documented in a short `docs/MACOS_TCC.md` update.
5. **Update `start_logger.sh`:** resolve `REPO` from script dir; keep `open -W` on `dist/ActivityLoggerNative.app`.
6. **Retire hard-coded plist:** move committed absolute plist to template; do not leave `/Users/mk/scripts/activitylogger` in new installs.
7. **Smoke-check:** type text; `daily_log_*.md` under configured `log_dir` grows within ~30s (or `flush_interval_sec`).
8. **TCC:** certificate leaf unchanged → no re-grant expected.

Rollback: remove or rename `config.toml`, restart agent → defaults restore prior paths/tunables.

---

## 12. Risks & open questions

| Risk / question | Notes |
|-----------------|-------|
| Frozen PyInstaller home | Must resolve `HOME` the same way as today’s `_resolve_log_dir` when Launch Agent environment is sparse |
| Sibling specs | F1–F6 must use §6 names only; see [`00-MASTER.md`](00-MASTER.md) |
| Repo `config.toml` accidental ship | Do not commit operator-specific paths; add `config.toml` to `.gitignore` if repo-secondary is supported |
| launchd and `~` | launchd does not reliably expand `~` in ProgramArguments — install script must write absolute paths |
| Cleaner out of scope | Operators may expect one file for cleaner tunables; defer or add `[cleaner]` later |
| `activitywatch_enricher` default `true` | Preserves today’s AW attempts; F1 changes fallback copy when enricher is off or AW is down |
| tomllib | Bundled app uses frozen runtime; confirm PyInstaller Python has `tomllib` or vendor `tomli` |

---

## 13. Implementation notes (high-level)

Do not implement in the spec phase. When implementing:

1. Add a pure `load_config` / `AppConfig` dataclass module with validation; no pynput imports.
2. Write §10 tests first; confirm they fail.
3. Wire `interleaved_logger.py` to call `load_config()` once at startup; replace module-level constants with values from the loaded config.
4. Replace hard-coded `depth > 7` with `ax_max_depth`.
5. Change `_resolve_log_dir` to use `paths.log_dir` from config / env.
6. Update `start_logger.sh` repo discovery; add install script + plist template.
7. Document config path and install steps in `docs/MACOS_TCC.md` (short section) and `AGENTS.md` pointer.
8. Do **not** change the Launch Services `open -W` chain.
9. After Python changes that ship in the app: `./scripts/rebuild_and_restart.sh`, verify `certificate leaf` in designated requirement, smoke-check log growth.

---

## Document control

- Spec ID: F2  
- Filename: `docs/specs/F2-config.md`  
- Scope: `docs/specs/00-SCOPE.md`  
- Related runtime: `interleaved_logger.py`, `start_logger.sh`, `com.mk.activitylogger.plist`, `scripts/rebuild_and_restart.sh`

---

## Critic revision log

| Item | Finding | Change |
|------|---------|--------|
| Schema vs F1 | Competing AW key names | Locked `[window_titles] activitywatch_enricher` + `activitywatch_base_url` |
| Schema vs F3 | `typing_pause_ms` vs `typing_pause_sec` | Locked `typing_pause_sec=0.5`; single `flush_interval_sec` |
| Schema vs F4 | `browser_url_enabled` vs `browser_url_capture` | Locked `browser_url_capture` |
| Schema vs F5 | Always-on vs opt-in | **Aggregate:** restored `capture_triggers_enabled = false` (privacy-safer for new seal cadence) |
| Schema vs F6 | `250` vs `400` | Locked `scroll_coalesce_ms = 400` |
| Launch Agent + log_dir | Install could read config for launchd log paths | Install always uses `$REPO/logs` for launchd I/O |
| Frozen discovery | Repo walk could leak into signed `.app` | No repo walk when frozen; TC-F2-16 |
| Failure safety | Unreadable XDG path vague | Fatal for discovered unreadable file; TC-F2-17 |
| Hot reload | Implied live edits | FR-F2-010: read once; kickstart after edit |
| Markdown-only | Implicit only | FR-F2-009 + TC-F2-18 |
| Validation | Missing ranges | Expanded §6.4; TC-F2-19 |

**Aggregate critic (2026-08-15):** This file is the sole config authority. Sibling specs must match §6. Privacy-safer defaults: URL, triggers, and scroll are all opt-in (`false`).

**Verdict: ACCEPT**
