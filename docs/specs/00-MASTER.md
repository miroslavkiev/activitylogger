# ActivityLogger — master spec index

**Status:** aggregate — CONSISTENT_ACCEPT (2026-08-15 R3)  
**Authority:** [`00-SCOPE.md`](00-SCOPE.md) for product bounds; [`F2-config.md`](F2-config.md) for config names; this file for cross-feature contract.

Do not expand scope beyond [`00-SCOPE.md`](00-SCOPE.md).

---

## 1. Product summary

Personal macOS input transcript → daily Markdown → cleaner → Gemini automation analysis.

Production capture uses certificate-signed `dist/ActivityLoggerNative.app` via Launch Agent `start_logger.sh` → `open -W`.

Markdown is the only user-facing log artifact. No JPEG, audio, OCR, or Screen Recording pipeline.

---

## 2. Spec map

| Doc | Role |
|-----|------|
| [`00-SCOPE.md`](00-SCOPE.md) | Locked product decisions and ignore list |
| [`F0-constraints-and-non-goals.md`](F0-constraints-and-non-goals.md) | KEEP / AVOID regression gates |
| [`F1-window-titles.md`](F1-window-titles.md) | Native-first titles; AW optional enricher |
| [`F2-config.md`](F2-config.md) | **Canonical** TOML schema and load rules |
| [`F3-flush-model.md`](F3-flush-model.md) | Typing-pause keys→events; durable file flush |
| [`F4-browser-url.md`](F4-browser-url.md) | Opt-in browser URL event lines |
| [`F5-capture-triggers.md`](F5-capture-triggers.md) | Opt-in section trigger metadata + seal paths |
| [`F6-scroll-coalescing.md`](F6-scroll-coalescing.md) | Opt-in scroll burst coalesce + seal |
| [`STATUS.md`](STATUS.md) | Review status board |

---

## 3. Locked decisions (cross-spec)

| Topic | Decision |
|-------|----------|
| Config authority | F2 owns all key names and defaults. Sibling specs must match F2 §6. |
| ActivityWatch keys | `window_titles.activitywatch_enricher`, `window_titles.activitywatch_base_url` |
| Typing idle key | `timing.typing_pause_sec` default **0.5** (not ms) |
| File flush key | `timing.flush_interval_sec` only (no `file_flush_sec`) |
| Browser URL key | `features.browser_url_capture` default **false** |
| Capture triggers key | `features.capture_triggers_enabled` default **false** (opt-in) |
| Scroll coalesce | `features.scroll_coalesce_enabled` default **false**; `scroll_coalesce_ms` default **400** |
| F3 typing-pause | Keys → `_current_events` only. **No** section seal. **No** Markdown write. |
| F5 `typing_pause` | **Reserved** in closed set. Not emitted until a future seal-on-burst decision. |
| F4 URL | Event line only when F5 OFF. When F4 ON and F5 ON: F4 seals after URL emit with `url_change`. |
| F5 Markdown syntax | Sole normative: `*{HH:MM:SS} · trigger:{name}*` |
| Log artifact | Daily Markdown only |
| Media / OCR / Screen Recording | Banned (F0) |

Privacy-safer defaults: URL, triggers, and scroll are all opt-in (`false`).

---

## 4. Canonical config snippet

Primary path: `~/.config/activitylogger/config.toml` (see F2 for discovery order).

```toml
# ActivityLogger capture config (F2) — defaults

[paths]
log_dir = "~/scripts/activitylogger/logs"

[timing]
window_check_sec = 5
flush_interval_sec = 30
typing_pause_sec = 0.5
secure_field_cache_sec = 0.35
diag_min_interval_sec = 30.0
secure_app_check_sec = 0.15

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
ax_max_children = 40
ax_scan_debounce_sec = 3.0

[window_titles]
activitywatch_enricher = true
activitywatch_base_url = "http://localhost:5600"
aw_backoff_sec = 45.0

[buffers]
max_keystrokes = 2000
max_events = 500
max_sections = 200

[features]
browser_url_capture = false
capture_triggers_enabled = false
scroll_coalesce_enabled = false
scroll_coalesce_ms = 400
```

**Rejected aliases (do not ship):** `aw_enabled`, `aw_base_url`, `[activitywatch]`, `browser_url_enabled`, `typing_pause_ms`, `file_flush_sec`.

---

## 5. Canonical Markdown grammar

### 5.1 Section shape (always)

```markdown
## {app} — {title}
*{timestamp line}*

{event lines…}

---
```

- Em dash in heading: ` — ` (U+2014).
- Empty native title → `Unknown window` at heading build (F1).
- No URL / trigger / other metadata inside the `##` line.

### 5.2 Timestamp line

| Mode | Line |
|------|------|
| Legacy / F5 flag OFF | `*{HH:MM:SS}*` |
| F5 flag ON | `*{HH:MM:SS} · trigger:{name}*` |

Separator: space, middle dot `·` (U+00B7), space. No space after `trigger:`.

### 5.3 Stable event tokens

| Kind | Form | Spec |
|------|------|------|
| Browser URL | `> [URL]: {absolute_url}` | F4 |
| Scroll burst | `🖱️ **Scroll:** {n} ticks, net {dir}` (optional app) | F6 |
| Keystrokes / hotkeys / clicks / clipboard | Existing logger forms | F0 K2 + core |

---

## 6. Closed trigger enum (F5)

Writers use **only** these names when `capture_triggers_enabled` is true:

| Name | Status | Owner |
|------|--------|--------|
| `app_switch` | Active | Core + F5 |
| `click` | Active (flag ON seals) | F5 |
| `clipboard` | Active (flag ON seals) | F5 |
| `file_flush` | Active | Core + F5 |
| `url_change` | Active when F4 ON + F5 ON | F4 |
| `scroll_coalesce` | Active when F6 seals | F6 |
| `typing_pause` | **Reserved — unused in F3 v1** | F3 (future) |

No aliases (`idle`, `scroll`, `window_change`, …).

---

## 7. Ordered TDD implementation sequence

Run F0 guards first. Then features in this order so contracts stay green.

| Order | Focus | Why first | Primary tests |
|-------|-------|-----------|---------------|
| 0 | F0 constraint suite | Blocks media / TCC / privacy regressions | `tests/test_privacy_and_cleaner.py`, `tests/test_f0_constraints.py` |
| 1 | F2 config load | All later features read these keys | `tests/test_config.py` (TC-F2-*) |
| 2 | F1 native titles | Headings + secure-app inputs | `tests/test_window_titles.py` |
| 3 | F3 typing-pause flush | Keys→events; no seal | T-F3-* |
| 4 | F5 triggers (flag OFF then ON) | Markdown grammar + seal causes | `tests/test_capture_triggers.py` |
| 5 | F4 browser URL | Event lines; F5 ON → seal `url_change` | `tests/test_browser_url.py` |
| 6 | F6 scroll coalesce | Opt-in; seal + `scroll_coalesce` | T-F6-* |

**Rule:** write failing tests for the next row before production code. After logger binary changes: `./scripts/rebuild_and_restart.sh`; confirm `certificate leaf`; smoke-check `logs/daily_log_*.md` growth.

Suggested dependency for implementers:

1. F2 → F1 (titles need enricher keys)
2. F2 → F3 (intervals)
3. F2 + F3 → F5 (triggers / seals; F3 does not emit `typing_pause`)
4. F2 + F1 + F5 → F4 (`url_change` seal when both F4 and F5 flags ON)
5. F2 + F5 → F6 (`scroll_coalesce`)

---

## 8. Coordination quick reference

| Interaction | Rule |
|-------------|------|
| F3 × F5 | Typing pause never seals in F3 v1; later seal uses `file_flush` / `click` / `app_switch` / … |
| F4 × F5 | F5 OFF: `> [URL]:` only. Both ON: F4 seals with `url_change` |
| F6 × F5 | Coalesce flush seals like click; trigger `scroll_coalesce` when F5 flag ON |
| F1 × F4 | Heading from F1; URL never in `##` line |
| All × F0 | Each Fx has an **F0 impact** section; F0 suite stays green |

---

## Aggregate critic revision log

**2026-08-15 — aggregate consistency pass**

| Tension | Resolution |
|---------|------------|
| F2 vs F5 enable flag | Restored `features.capture_triggers_enabled = false` in F2 (privacy-safer opt-in for new seal cadence). F5 already matched. |
| F2 vs F3 idle key | Locked `timing.typing_pause_sec = 0.5`. Updated F3 off `typing_pause_ms` / 800. |
| F2 vs F6 scroll ms | Locked `scroll_coalesce_ms = 400`. Updated F6. |
| F2 vs F4 URL key | Locked `features.browser_url_capture`. Updated F4 off `browser_url_enabled`. |
| F1 vs F2 AW keys | Locked `[window_titles] activitywatch_*`. Updated F1 off `[activitywatch]` / `aw_*`. |
| F3 vs F5 typing_pause | F3 = keys→events only. F5 keeps `typing_pause` **reserved / unused**. |
| F5 vs F6 Markdown | F5 §6 remains sole trigger syntax; F6 examples already one italic line. |
| F0 impact missing | Added F0 impact sections to F2–F6 (F1 already had one). |

**Verdict (prior pass): CONSISTENT_ACCEPT** — later independent verifier found remaining issues (below).

**2026-08-15 — independent aggregate verifier**

| Tension | Resolution |
|---------|------------|
| F4 × F5 × MASTER `url_change` seal owner | Locked: F5 OFF → event only; F4 ON + F5 ON → **F4 seals** after URL emit with `url_change`. Removed F4 “F5 owns seal”, F5 “optional per F4”, and MASTER “only if F5 seals”. |
| F5 Markdown cross-refs | Goal / Flag ON cited §5 for syntax; normative grammar is §6. Fixed to §6. |
| F1 placeholder cross-ref | Resolver text cited §8; heading build is §6.2. Fixed. |

**Verdict: NEEDS_ANOTHER_ROUND** (fixes applied in place; re-verify seal wording + § refs).

No remaining intentional product blockers under the locked R1 config claims; the round is for the seal-ownership lock above.

**2026-08-15 — R3 independent aggregate verifier**

Re-checked F4 / F5 / MASTER `url_change` seal ownership, F5 §6 syntax-only refs, F1 §6.2 placeholder cross-ref, and the config-alias / F3 no-seal sweep. No further fixes.

**Verdict: CONSISTENT_ACCEPT**
