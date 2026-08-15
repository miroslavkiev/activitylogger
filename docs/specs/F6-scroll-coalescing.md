# F6 — Optional scroll coalescing (P2)

**Status:** Implemented (F6_ACCEPT; FINAL_ACCEPT; opt-in, default OFF)  
Depends on: F2 (config keys and defaults), F5 (trigger name `scroll_coalesce`)  
Scope contract: [`00-SCOPE.md`](00-SCOPE.md)  
Constraints: [`F0-constraints-and-non-goals.md`](F0-constraints-and-non-goals.md)

## 1. Summary

Scroll coalescing is an **opt-in** feature. Default is **off**.

When the user turns it on, ActivityLogger groups many scroll-wheel (or trackpad scroll) callbacks into **one** Markdown scroll line after a quiet period. That flush **seals a section** with F5 trigger name `scroll_coalesce` when F5 is on (same seal pattern as a click).

This feature:

- does **not** log mouse-move trails
- does **not** register `on_move`
- does **not** take screenshots or use Screen Recording
- must respect privacy pause (drop in-flight burst; ignore scrolls while paused)

With the flag OFF, the mouse listener handles **clicks only** (no `on_scroll`). With the flag ON, `on_scroll` is registered and idle flush uses `scroll_coalesce_ms`.

## 2. Problem / previous behavior (before F6)

| Area | Before F6 |
|------|--------|
| Mouse listener | `mouse.Listener(on_click=on_click)` only |
| Scroll wheel / trackpad scroll | Not observed; not logged |
| Clicks | AX hit-test → click line via `add_event`; F5 seals with `click` when F5 is on |
| Mouse move | Not tracked (keep this) |
| Screenshots / JPEG | Out of scope (F0 / scope ignore) |
| Privacy | `is_paused()` / `add_event` drop events while paused |

Without coalescing, one log line per scroll tick would flood the daily Markdown file and hurt Gemini analysis.

## 3. Goals / Non-goals

### Goals

- Optional scroll logging with burst coalescing after quiet time.
- One human-readable Markdown scroll line per quiet burst.
- On flush: seal the open buffer like a click (keys flushed first, then scroll line), with F5 trigger **`scroll_coalesce`** when F5 is active.
- Config keys and defaults owned by **F2** only; this spec states behavior, not a second schema.
- Full privacy-pause respect.

### Non-goals

- Mouse-move trails or hover paths.
- Screenshots, Screen Recording, OCR, or JPEG for scroll context.
- Per-tick scroll lines.
- Absolute cursor coordinates on scroll lines.
- AX screen-text `scan` after scroll (clicks may still scan as today).
- Ukrainian / locale label changes for existing event types.
- JSONL / SQLite sidecars.

## 4. User stories

1. As a user with the feature **off**, I see **no** scroll lines in the log (same as today).
2. As a user with the feature **on**, when I scroll a long page then stop, I see **one** scroll note after the quiet period, in a sealed section.
3. As a user who opens a password manager while scrolling, the logger **discards** the in-flight scroll burst and writes **no** scroll note from the paused period.
4. As a user who switches apps mid-scroll, the logger **flushes** the scroll burst under the prior app section, then starts a new burst under the new app if scrolling continues.

## 5. Functional requirements

| ID | Requirement |
|----|-------------|
| **FR-F6-001** | Default **off**. When `features.scroll_coalesce_enabled` is missing or `false` (F2 default), do not write scroll notes. Prefer not to attach `on_scroll` when disabled. |
| **FR-F6-002** | When enabled, register pynput `on_scroll` (or equivalent) on the existing mouse listener. Do **not** register `on_move`. |
| **FR-F6-003** | Each scroll callback updates one in-memory burst: tick count, net vertical delta, optional net horizontal delta, start time, last-event time, and frontmost app/heading at burst start. |
| **FR-F6-004** | After quiet time `features.scroll_coalesce_ms` (F2 default **400**) with no new scroll events, flush the burst as **one** Markdown scroll event, then **seal** the open section (same order as click: flush keystrokes → append scroll line → seal). |
| **FR-F6-005** | While `is_paused()` is true, ignore new scroll events. Do not append scroll notes. Do not seal for scroll. |
| **FR-F6-006** | When pause becomes true and a burst is open, **discard** the burst (no flush, no seal). Secure-app / secure-field pause must not regress. |
| **FR-F6-007** | On app / section heading change with an open burst: **flush and seal** the burst into the **prior** section context (trigger `scroll_coalesce` when F5 is on), then clear. New scrolls start a new burst under the new heading. |
| **FR-F6-008** | Coalesced scroll must not trigger screenshot / JPEG capture. Optional AX screen text scan after scroll is **out of scope** for F6. |
| **FR-F6-009** | When F5 is active (`capture_triggers_enabled`), the sealed section from a coalesced scroll flush uses trigger name **`scroll_coalesce`** (exact string; closed set in F5). Do not invent aliases such as `scroll`. |
| **FR-F6-010** | Config: **defer to F2**. Keys are `features.scroll_coalesce_enabled` (bool, default `false`) and `features.scroll_coalesce_ms` (int, default `400`). Do not invent a second loader or different defaults in F6 code. Invalid / missing values follow F2 validation and fallback rules. |
| **FR-F6-011** | If pynput cannot deliver scroll events on the host OS, the logger must stay up: clicks and keys continue; emit one diagnostic; write zero scroll notes. |
| **FR-F6-012** | On orderly shutdown or durable file-flush path: if a burst is open and not paused, flush and seal it (do not drop silently). If paused, discard. |

### Coalesce algorithm (normative)

1. **Tick** = one `on_scroll` callback (not physical distance).
2. On each tick while enabled and not paused: create or update the open burst; reset the quiet timer.
3. **Net direction** = sign of summed `dy` / `dx` over the burst:
   - vertical only → `net up` or `net down`
   - horizontal only → `net left` or `net right`
   - both axes non-zero net → `net mixed`
   - all sums zero → `net none` (still allowed; rare)
4. Quiet expiry, app-switch flush, or shutdown flush (not paused) → format one line → seal.
5. Pause enter → discard open burst; no line; no seal for that burst.

## 6. Config contract (F2 owns schema)

F6 does **not** load its own config file and does **not** redefine defaults.

F2 exposes under `[features]` (see F2 §6):

```toml
[features]
scroll_coalesce_enabled = false
scroll_coalesce_ms = 400
```

| Key (F2 path) | Type | Default (F2) | Meaning for F6 |
|---------------|------|--------------|----------------|
| `features.scroll_coalesce_enabled` | bool | `false` | Master switch; off = no scroll notes |
| `features.scroll_coalesce_ms` | int | `400` | Quiet period (ms) before flush |

Behavior notes (F6):

- Use F2’s validated value (default **400**). Do not invent a second default in F6.
- F2 validation requires `scroll_coalesce_ms` in `50..5000`. Do not fork that range in F6.

## 7. Markdown example

When F5 is on, the sealed section follows F5 syntax (one italic time+trigger line):

```markdown
## Safari — Example Docs
*18:42:10 · trigger:scroll_coalesce*

🖱️ **Scroll:** 28 ticks, net down (Safari)

---
```

When F5 is off, emit the same scroll body line under the normal section header rules (no ` · trigger:…` until F5 ships or is enabled).

Rules for the scroll **body** line:

- One line per flushed burst.
- Include tick count (number of `on_scroll` callbacks in the burst).
- Include net direction: `net up`, `net down`, `net left`, `net right`, `net mixed`, or `net none`.
- Include app name from burst-start context when known; otherwise omit the parenthetical.
- Do **not** include x/y cursor coordinates.
- Do **not** include raw per-tick deltas as a list.

F5 owns exact `*{HH:MM:SS} · trigger:{name}*` placement. F6 only requires the trigger **name** `scroll_coalesce` on the sealed section.

## 8. Privacy / security

- Same pause gates as keys, clicks, clipboard, and screen text.
- Discard open burst on pause enter (FR-F6-006).
- Ignore scroll while paused (FR-F6-005).
- Defense in depth: if a flush runs while `is_paused()` is true, append nothing and seal nothing for scroll (T-F6-08).
- No Screen Recording permission for this feature.
- No mouse-move logging.

## F0 impact

| F0 item | F6 effect |
|---------|-----------|
| K1 Launch + signing | Untouched. |
| K2 Keystrokes | Untouched. |
| K3 Secure pause | Discard open burst on pause; ignore scrolls while paused. |
| K4 Markdown-only | One scroll body line per burst; no sidecar. |
| K5 Cleaner + prompt | Scroll line is a normal event; trigger name owned by F5 when flag ON. |
| K6 Single-process | Untouched (`on_scroll` on existing listener). |
| B1–B3 Media / Screen Recording / OCR | Stay banned (no screenshot / scan on scroll). |
| B4 Other ignores | Stay banned. |

## 9. Acceptance criteria

1. Fresh install / default config: daily log never gains scroll lines from wheel/trackpad use.
2. With `scroll_coalesce_enabled = true`, a rapid scroll then silence ≥ `scroll_coalesce_ms` produces exactly one scroll Markdown line for that burst, and seals a section.
3. Enabling the feature never registers mouse-move handlers and never writes move trails.
4. Enabling the feature never requests or uses Screen Recording / JPEG capture for scroll.
5. Privacy pause during an open burst: no scroll line and no scroll seal for that burst; no scroll lines during the pause window.
6. App switch mid-scroll: prior burst flushes and seals under the prior heading; continued scroll forms a new burst under the new heading.
7. F5 integration: sealed coalesce uses trigger `scroll_coalesce` when F5 is enabled; never `scroll` or other aliases.
8. Certificate-signed rebuild path unchanged (`./scripts/rebuild_and_restart.sh`); TCC story unchanged beyond existing Input Monitoring / Accessibility.
9. If scroll callbacks never arrive on the host, capture of keys/clicks still works (FR-F6-011).

## 10. Test plan (TDD) — Given / When / Then

Write these tests **before** production scroll code. Prefer pure functions for burst state (`accumulate` / `should_flush` / `format_line` / `on_pause` / `on_app_switch` / `on_shutdown`) so pytest does not need a live GUI or real pynput.

### T-F6-01 — Default off

- **Given** config with `scroll_coalesce_enabled` absent or `false` (F2 default)
- **When** 50 synthetic scroll events arrive
- **Then** zero scroll Markdown events are produced
- **And** no section is sealed for scroll

### T-F6-02 — Rapid scroll coalesces to one note

- **Given** enabled, `scroll_coalesce_ms = 400` (F2 default) or a shorter test override
- **When** 40 scroll events arrive within 200 ms, then quiet ≥ configured ms
- **Then** exactly one scroll event string is emitted
- **And** tick count is 40
- **And** net direction matches dominant delta sign
- **And** exactly one section seal for that flush

### T-F6-03 — Quiet period resets on each tick

- **Given** enabled, `scroll_coalesce_ms = 400` (test override)
- **When** scrolls at t=0, t=300, t=600 (ms), then quiet until t=1000
- **Then** flush occurs once at/after last tick + 400 ms (not after the first gap)
- **And** still exactly one note for the continuous burst

### T-F6-04 — Pause during scroll discards burst

- **Given** enabled, open burst with N>0 ticks
- **When** privacy pause becomes true before quiet flush
- **Then** no scroll Markdown event is emitted for that burst
- **When** further scrolls arrive while paused
- **Then** they are ignored
- **When** pause clears and new scrolls + quiet occur
- **Then** a new note may be emitted only for post-pause ticks

### T-F6-05 — App switch mid-scroll

- **Given** enabled, open burst under heading `AppA — TitleA` with ticks > 0
- **When** heading changes to `AppB — TitleB` before quiet flush
- **Then** one scroll note is flushed and sealed under `AppA` (prior context)
- **And** the open burst is cleared
- **When** more scrolls occur under `AppB` then quiet
- **Then** a second scroll note is associated with `AppB`

### T-F6-06 — No mouse-move side effects

- **Given** enabled
- **When** only move events are simulated (no scroll)
- **Then** no scroll notes and no move trail lines are written
- **And** listener wiring asserts `on_move` is not registered (unit or thin integration stub)

### T-F6-07 — F5 trigger name

- **Given** F5 enabled and F6 enabled
- **When** a coalesced scroll flushes
- **Then** the sealed section `trigger` value is exactly `scroll_coalesce`
- **And** Markdown uses F5 form `*{HH:MM:SS} · trigger:scroll_coalesce*` (not a second `*trigger: …*` line)

### T-F6-08 — `add_event` / seal pause gate still applies

- **Given** enabled, burst ready to flush, but `is_paused()` is true at flush time
- **When** flush runs
- **Then** no scroll line is appended and no scroll seal occurs (defense in depth with FR-F6-006)

### T-F6-09 — Format contract

- **Given** a flushed burst with known ticks and net down
- **When** `format_scroll_event(...)` runs
- **Then** output matches `🖱️ **Scroll:** {n} ticks, net down` (optional app suffix)
- **And** output contains no cursor coordinate pattern such as `x=` or bare `(\d+, \d+)` from pointer position

### T-F6-10 — Scroll delivery failure (pynput / macOS)

- **Given** enabled, and a stub where scroll subscription raises or never delivers callbacks
- **When** the logger starts and receives keys/clicks only
- **Then** process stays up; keys/clicks still log
- **And** at most one diagnostic about scroll unavailability
- **And** zero scroll notes

### T-F6-11 — Shutdown / durable flush does not drop open burst

- **Given** enabled, open burst with ticks > 0, not paused
- **When** orderly shutdown or durable flush path runs
- **Then** one scroll note is flushed and sealed
- **Given** the same but paused
- **When** shutdown runs
- **Then** the burst is discarded (no scroll note)

### T-F6-12 — No screenshot / scan side effects

- **Given** enabled
- **When** a coalesced scroll flushes
- **Then** no screenshot / JPEG path is invoked
- **And** no AX screen-text `scan` is enqueued solely because of scroll (click scan paths remain unchanged)

### Manual smoke (signed `.app`, not pytest)

1. Enable `scroll_coalesce_enabled` in user config; rebuild/restart with `./scripts/rebuild_and_restart.sh`.
2. Scroll in Safari; wait quiet ms; confirm one scroll line in `logs/daily_log_*.md`.
3. Confirm wheel and trackpad both produce ticks when the OS delivers them; if neither produces lines, check diagnostic and keep keys/clicks working.
4. Do not re-grant TCC after a certificate-signed rebuild with the same identity.

## 11. Risks & closed decisions

| Risk | Impact | Mitigation |
|------|--------|------------|
| **pynput `on_scroll` on macOS** | Scroll callbacks may be missing, duplicate, or differ for mouse wheel vs trackpad; CGEvent path needs Accessibility / Input Monitoring (already required). | FR-F6-011 + T-F6-10; manual smoke on signed `.app`; never crash. |
| Delta units | Wheel notches vs trackpad deltas make “ticks” uneven. | Tick = one callback; net direction from sign of summed `dy`/`dx`. |
| Threading | Scroll callbacks on listener thread; flush must be lock-safe like `add_event`. | Reuse existing locks; unit-test burst helpers without threads first. |
| App switch race | Window checker interval (F2) may lag true switch. | Flush on the same heading-change path used today; short mis-attribution is acceptable and documented. |
| F5 timing | F5 may land before or after F6. | Without F5, emit scroll body + seal without trigger field; when F5 is on, wire `scroll_coalesce` only. |
| Quiet vs file flush | Periodic file flush must not drop an open burst silently. | FR-F6-012 + T-F6-11: flush if not paused; discard if paused. |

### Closed decisions (were open questions)

1. Quiet default ms: **400** — owned by F2; F6 must not invent a different product default.
2. Horizontal-only scroll: **yes** — same note with `net left` / `net right`.
3. AX `scan` after scroll: **no** for F6.
4. Seal model: **yes** — coalesced flush seals like click (not a floating event with no section trigger).

## 12. Implementation notes (high-level; after failing tests)

1. Extract a testable burst state machine (no pynput in unit tests).
2. Wire `on_scroll` only when `scroll_coalesce_enabled` is true.
3. Use a timer or “last scroll + check in existing loops” for quiet expiry; keep single-process design.
4. On successful flush, seal with F5 hook `scroll_coalesce` when F5 is enabled.
5. Rebuild with `./scripts/rebuild_and_restart.sh` after logger changes; confirm certificate leaf; smoke-test by enabling config and checking `logs/daily_log_*.md` after a scroll burst.

T-F6-* tests live under `tests/`; F6 is Implemented (FINAL_ACCEPT).

## Critic revision log

**Verdict: FINAL_ACCEPT**

Changes applied in this revision:

1. **Default OFF** — Restated as non-negotiable; FR-F6-001 prefers no `on_scroll` when disabled.
2. **Coalesce behavior** — Added normative algorithm; seal-on-flush like click; explicit no `on_move`, no screenshots, no AX scan.
3. **Privacy pause** — Kept discard-on-pause + ignore-while-paused; added FR-F6-012 and T-F6-08/T-F6-11 for flush/shutdown edges.
4. **Trigger name** — Aligned with F5: exact `scroll_coalesce`; Markdown example uses `*{HH:MM:SS} · trigger:scroll_coalesce*` (removed wrong two-line trigger format).
5. **Config** — Deferred fully to F2: `features.scroll_coalesce_*`, default **400** ms.

**Aggregate critic (2026-08-15):** Aligned `scroll_coalesce_ms` default to F2 (`400`).
6. **TDD** — Added T-F6-10 (pynput/macOS delivery failure), T-F6-11 (shutdown), T-F6-12 (no screenshot/scan), move-registration assert, and signed-app manual smoke.
7. **STE** — Shortened sentences; closed open questions; one term per concept (tick, burst, quiet, seal).

No code in this change. Residual product risk (macOS scroll delivery) is accepted with tests + manual smoke, not left as an open question blocking the spec.
