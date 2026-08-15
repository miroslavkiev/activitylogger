# Spec review status

| Spec | Status |
|------|--------|
| [00-MASTER.md](00-MASTER.md) | **CONSISTENT_ACCEPT** (R3 independent aggregate verifier) |
| [00-SCOPE.md](00-SCOPE.md) | locked |
| [F0-constraints-and-non-goals.md](F0-constraints-and-non-goals.md) | ACCEPT |
| [F1-window-titles.md](F1-window-titles.md) | ACCEPT (aligned to F2 `[window_titles]`; §6.2 cross-ref fix) |
| [F2-config.md](F2-config.md) | ACCEPT (canonical schema) |
| [F3-flush-model.md](F3-flush-model.md) | ACCEPT (`typing_pause_sec=0.5`; no seal) |
| [F4-browser-url.md](F4-browser-url.md) | ACCEPT (`browser_url_capture`; F4 seals `url_change` when F5 ON) |
| [F5-capture-triggers.md](F5-capture-triggers.md) | ACCEPT (opt-in; `typing_pause` reserved; §6 syntax refs) |
| [F6-scroll-coalescing.md](F6-scroll-coalescing.md) | ACCEPT (`scroll_coalesce_ms=400`) |

## Aggregate critic note (2026-08-15)

Prior pass closed R1 config-key tensions. See [`00-MASTER.md`](00-MASTER.md) §3 and the aggregate revision log.

| Former tension | Locked resolution |
|----------------|-------------------|
| F2 vs F5 enable | `capture_triggers_enabled = false` (opt-in) in F2 + F5 |
| F2 vs F3 idle | `typing_pause_sec = 0.5` |
| F2 vs F6 scroll ms | `scroll_coalesce_ms = 400` |
| F2 vs F4 URL key | `browser_url_capture` |
| F3 vs F5 typing_pause | F3 keys→events only; F5 name reserved |
| F1 vs F2 AW keys | `window_titles.activitywatch_*` |

## Independent aggregate verifier (2026-08-15)

| Finding | Fix |
|---------|-----|
| F4 / F5 / MASTER disagreed on who seals for `url_change` | Locked: F5 OFF → event only; both ON → **F4 seals** with `url_change` |
| F5 Goal / Flag ON cited §5 for Markdown syntax | Point to §6 (sole normative grammar) |
| F1 resolver cited §8 for placeholders | Point to §6.2 |

**Verdict: NEEDS_ANOTHER_ROUND** — re-check seal wording across F4, F5, and `00-MASTER.md` after these edits.

## R3 independent aggregate verifier (2026-08-15)

Re-verified R2 locks and full quick sweep. No remaining inconsistencies. No further fixes.

| Check | Result |
|-------|--------|
| F4 / F5 / MASTER `url_change` seal ownership | Agree: F5 OFF → URL event only; F4 ON + F5 ON → F4 seals with `url_change` |
| F5 Markdown syntax sole at §6 | No stale §5 syntax refs |
| F1 placeholder → §6.2 | Correct |
| Leftover `typing_pause_ms` / 800, scroll 250, `browser_url_enabled`, triggers always-on, F3 emit `typing_pause` seal | None in normative text (rejected-alias / history only) |

**Verdict: CONSISTENT_ACCEPT**

## Final implementation aggregate gate (2026-08-15)

Product job remains: personal macOS input transcript → daily Markdown → cleaner → Gemini. Not a Screenpipe clone.

| Check | Result |
|-------|--------|
| F0–F6 vs MASTER / SCOPE | Pass |
| Suite `pytest -q tests/` | 161 passed |
| Signed production app | `certificate leaf` present; sources not newer than binary |

**Verdict: FINAL_ACCEPT** — see [`IMPL-STATUS.md`](IMPL-STATUS.md).
