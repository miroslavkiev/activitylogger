# F3 — Improve flush model (P1)

**Status:** Implemented (F3_ACCEPT; FINAL_ACCEPT)  
Contract: [`00-SCOPE.md`](00-SCOPE.md).  
Depends on: F2 (config for intervals). Coordinates with: F5 (section trigger names).

---

## 1. Summary

Keep char-level keystroke capture. Add a **typing-pause burst flush**: after a short idle gap with no new keys, move the key buffer into the open section event list as one joined string. Keep the durable periodic **file flush** (default 30 s). Read both intervals from F2 config.

**Locked product rule:** typing-pause flush moves keys into `_current_events` only. It does **not** seal `_sections` and does **not** write Markdown. Section trigger `typing_pause` (F5) is therefore **not** emitted by this feature version.

---

## 2. Previous behavior (before F3)

Source of truth before F3: `interleaved_logger.py` (pre-typing-pause burst flush).

### 2.1 Buffers and section model

| Structure | Role |
|-----------|------|
| `_current_keystrokes: list[str]` | Char-level (and token) key buffer |
| `_current_events: list[str]` | Open section body (clicks, clipboard, screen, joined keys) |
| `_sections: list[dict]` | Sealed sections: `heading`, `events`, `timestamp` |

A sealed section is written to Markdown later by `flush_to_file()`.

### 2.2 Key encoding (`on_press`)

- While paused: return; do not append keys.
- Modifiers: track in `_current_modifiers` (CMD/CTRL/OPT/SHIFT).
- Special keys: Enter → `\n[ENTER]\n`; Tab → `[TAB]`; Space → ` `; Esc → `[ESC]`; Backspace → pop last buffer entry if any.
- Printable chars: append char, or `[MODS+CHAR]` when non-SHIFT modifiers are active.
- Keys stay in `_current_keystrokes` until a key flush runs. There is **no** idle timer today.

### 2.3 Key flush (`_flush_keys`)

If `_current_keystrokes` is non-empty:

1. Append `"".join(_current_keystrokes)` to `_current_events`.
2. Clear `_current_keystrokes`.

Callers today:

- `add_event` (before appending click / clipboard / screen / similar)
- Window heading change in `window_checker_loop`
- `flush_to_file` (before sealing the open section)

### 2.4 Event append (`add_event`)

Under lock: if paused, return. Else `_flush_keys()`, then append the event string.

### 2.5 Section seal (in memory)

When the window heading changes (and on file flush):

1. `_flush_keys()`
2. If `_current_events` non-empty → append `{heading, events, timestamp}` to `_sections` and clear `_current_events`
3. On window change: set new `_current_heading` (and clear last screen text)

Heading change does **not** write the file by itself.

### 2.6 File flush (`flush_to_file` / `file_writer_loop`)

- Loop: `sleep(FLUSH_INTERVAL_SEC)` then `flush_to_file()` (`FLUSH_INTERVAL_SEC = 30` hard-coded).
- Under lock: `_flush_keys()`; seal open events into `_sections` if any; take `to_write = list(_sections)` and clear `_sections`.
- Write Markdown `## heading` / `*timestamp*` / event lines / `---`.
- On write failure: restore `to_write` to the front of `_sections`.
- Shutdown (`KeyboardInterrupt`): one final `flush_to_file()`.

### 2.7 Privacy pause and buffers

On pause edge (`_recompute_paused_locked` when newly paused):

- Clear `_current_modifiers`
- Clear `_current_keystrokes`
- Do **not** flush keys into `_current_events` (discard in-flight typing)

Existing test: `test_recompute_clears_keystrokes_on_pause_edge`.

---

## 3. Goals / Non-goals

### Goals

- G1: After a configurable idle gap with no buffer-mutating key activity, flush the key buffer into `_current_events` as one burst string (same join semantics as `_flush_keys`).
- G2: Keep durable periodic file flush; interval owned by F2 (`flush_interval_sec`, default 30).
- G3: Keep char-level + hotkey encoding (no Screenpipe-style “keys off”).
- G4: Coordinate with F5 without contradiction: F3 does not seal on typing pause; later section triggers stay F5 seal causes (`file_flush`, `app_switch`, `click`, …).
- G5: No privacy regression: pause must still discard (not flush) the key buffer.

### Non-goals

- NG1: Do not remove or replace Markdown-only storage.
- NG2: Do not add JSONL / SQLite / query API / sidecars.
- NG3: Do not change secure-app / secure-field pause rules (F3 only clears/flushes buffers correctly around pause).
- NG4: Do not coalesce or redact key content in the cleaner as part of F3.
- NG5: Do not require a new TCC grant or signing change for this feature alone.
- NG6: Do not seal `_sections` on typing pause in this version (no F5 `typing_pause` section trigger from F3).

---

## 4. Definitions

Two different flush layers. Do not mix the names.

| Term | Layer | Definition |
|------|-------|------------|
| **Key buffer** | Memory | `_current_keystrokes`: ordered list of char/token strings for the current typing burst. |
| **Typing pause** | Idle rule | Continuous idle of at least `typing_pause_sec` with **no buffer-mutating key activity**, measured on a **monotonic** clock. |
| **Buffer-mutating key activity** | Idle rule | Any `on_press` path that appends to or pops from `_current_keystrokes` (printable char, hotkey token, Enter/Tab/Space/Esc token, backspace pop). Modifier-only press/release that does not change the buffer does **not** reset the idle timer. |
| **Typing-pause burst flush** | Key → events | On typing pause with a non-empty key buffer: run key flush into `_current_events` (join + clear buffer). Does **not** seal `_sections`. Does **not** change heading. Does **not** write the file. |
| **Section seal** | Events → sections | Move non-empty `_current_events` into `_sections` with current heading and timestamp. |
| **File flush** | Sections → disk | Seal open events if needed, then write sealed `_sections` to the daily Markdown file and clear the written batch (with restore-on-failure). |
| **Key-flush cause** | Internal | Why `_flush_keys` ran: `typing_pause`, `add_event`, `app_switch`, or `file_flush`. Used in tests/hooks. This is **not** an F5 section `trigger` unless a seal happens in the same call with that F5 name. |
| **Section trigger** | F5 | Closed-set name on a **sealed** section. F3 v1 never sets `typing_pause` here. |

Config keys (F2 owns names and defaults; F3 owns semantics):

| F2 key | Default | F3 use |
|--------|---------|--------|
| `typing_pause_sec` | **0.5** | Idle gap (seconds) before typing-pause burst flush |
| `flush_interval_sec` | **30** | Durable file-flush period |

Do **not** use `typing_pause_ms`. F2 owns the name `typing_pause_sec`.

If F2 also lists `file_flush_sec`, F3 uses **`flush_interval_sec` only** (one winner).

---

## 5. Functional requirements

**FR-F3-001** Char-level capture remains the default and only keystroke mode. Do not add a “keys off” mode in F3.

**FR-F3-002** While not paused, each buffer-mutating key event resets the typing-pause idle timer.

**FR-F3-003** When idle time reaches `typing_pause_sec` and the key buffer is non-empty, the system MUST flush the key buffer into `_current_events` as one joined string and clear the key buffer.

**FR-F3-004** When the idle check runs and the key buffer is empty, the system MUST NOT append an empty event.

**FR-F3-005** Typing-pause burst flush MUST NOT change `_current_heading`.

**FR-F3-006** Typing-pause burst flush MUST NOT seal `_sections` and MUST NOT write the Markdown file. File durability remains the periodic file flush (and shutdown flush). Other paths (window switch, F5 click/clipboard seal, file flush) still seal when their own rules say so.

**FR-F3-007** Existing key-flush callers (`add_event`, window heading change, `flush_to_file`) MUST keep current join semantics so mixed paths stay consistent.

**FR-F3-008** Periodic file flush MUST remain. Interval MUST come from F2 key `flush_interval_sec`, default **30**.

**FR-F3-009** Typing-pause idle duration MUST come from F2 key `typing_pause_sec`, default **0.5**.

**FR-F3-010** On privacy pause edge (newly paused): clear key buffer and modifiers; MUST NOT move those keys into `_current_events`; MUST cancel or ignore any pending typing-pause idle check for that buffer.

**FR-F3-011** While paused: no key appends. After unpause, the idle timer MUST NOT flush keys that were discarded on pause. A new burst starts only after new buffer-mutating keys.

**FR-F3-012** Backspace inside an open key buffer continues to pop within the buffer. After a typing-pause flush, backspace MUST NOT rewrite or delete the already flushed event string (same as today’s post-`_flush_keys` behavior).

**FR-F3-013** Hotkey tokens (`[CMD+C]`, etc.) participate in the same buffer and the same burst flush rules as normal chars.

**FR-F3-014** On window switch mid-buffer: existing order stands — flush keys into events, then seal section if events exist, then set new heading. Typing-pause timer resets for the new context (no carry of old idle deadline).

**FR-F3-015** Tests and optional hooks MAY observe key-flush cause `typing_pause` when FR-F3-003 runs. That cause MUST NOT be copied onto a later sealed section as F5 trigger `typing_pause`.

**FR-F3-016** When open events that already contain typing-pause bursts are sealed later by file flush, the section trigger (F5) MUST be `file_flush` (or `app_switch` / `click` / `clipboard` if that path seals). Burst chunking in the event list remains; the seal cause wins.

**FR-F3-017** Shutdown / interrupt flush MUST still call file flush so sealed sections and open events+keys are not lost beyond normal crash risk.

**FR-F3-018** Storage remains daily Markdown only. No JSONL, SQLite, or sidecar metadata files.

---

## 6. Interaction with pause / privacy

Must not regress:

1. Secure app or secure field → pause.
2. In-flight key buffer is **discarded**, not flushed to events or disk.
3. `add_event` remains a no-op while paused.
4. Clipboard markers may advance while paused without logging secret text (existing behavior).
5. After unpause, a new typing burst starts empty; idle timer starts only after new buffer-mutating keys.
6. A typing-pause timer that was armed before pause must not append discarded keys after pause or after unpause.

Regression tests from `tests/test_privacy_and_cleaner.py` remain mandatory. F3 adds pause-vs-idle-timer cases in §10.

---

## 7. Interaction with F5 triggers

| F3 / core path | Seals section? | F5 section `trigger` | Notes |
|----------------|----------------|----------------------|-------|
| Typing-pause: keys → events | **No** | *(none from this path)* | Key-flush cause may be `typing_pause` for tests only |
| Periodic / shutdown file write seal | Yes | `file_flush` | Even if body events came from earlier typing-pause flushes |
| Window heading change seal | Yes | `app_switch` | Existing path |
| `add_event` then later seal | Depends on F5 | Per F5 (`click`, `clipboard`, …) | F3 only ensures keys flush before the event |

Rules:

1. Use F5 closed-set spellings only: `typing_pause`, `file_flush`, `app_switch` (no `idle`, no `typing-pause`).
2. F3 v1 does **not** seal on typing pause, so it must **not** emit section trigger `typing_pause`.
3. F5 may keep `typing_pause` in the closed set as reserved for a future seal-on-burst mode. That mode is **out of F3 scope** until a new product decision revises FR-F3-006.
4. F3 does not define Markdown trigger syntax (F5 owns that).

---

## 8. Markdown examples before / after

Assume same window `Cursor — notes.md`. User types `hello`, waits ≥ `typing_pause_sec`, then clicks. A file flush has already run after the click (or F5 click seal + file write — write path ownership is F5/core).

### Before (today)

Keys often stay in memory until click / window change / 30 s file flush. After click + file flush, one section may look like:

```markdown
## Cursor — notes.md
*14:02:10*

hello

🖱️ **Клік:** button Button.left @ (100, 200)

---
```

If the user never clicks and never switches window, keys may appear only after the ~30 s file flush seals them (same join), with no mid-burst event boundary from idle alone.

### After (F3)

After typing `hello` and pausing ≥ `typing_pause_sec`, `hello` is already in `_current_events` (still may not be on disk until file flush). After click + file flush, visible Markdown can match today for this sequence.

The behavioral win is burst boundaries **inside** one open section when the user types, pauses, types again before seal:

```markdown
## Cursor — notes.md
*14:02:10 · trigger:file_flush*

first sentence

second sentence

---
```

(Trigger line shown only if F5 is enabled. Seal cause is `file_flush`, not `typing_pause`.)

---

## F0 impact

| F0 item | F3 effect |
|---------|-----------|
| K1 Launch + signing | Untouched. |
| K2 Keystrokes + hotkeys | Touched timing only: same encoding; idle flush moves buffer into events. |
| K3 Secure pause | Must discard (not flush) keys on pause edge; existing privacy tests stay green. |
| K4 Markdown-only | Untouched; file flush still writes Markdown only. |
| K5 Cleaner + prompt | Untouched. |
| K6 Single-process | Untouched (in-process idle checker). |
| B1–B4 Bans | Stay banned. |

---

## 9. Acceptance criteria

1. With `typing_pause_sec = 0.5`, typing `abc` then idle ≥ 0.5 s moves exactly one event `"abc"` into `_current_events` and clears the key buffer **without** a section seal and **without** a file write.
2. Continuous typing with inter-key gaps &lt; `typing_pause_sec` does not split the burst.
3. File still appears/updates on ~`flush_interval_sec` (default 30) when there is sealed content; interval is not hard-coded only in source after F2.
4. Pause mid-type discards buffer; log must not gain those characters after pause or after unpause.
5. Backspace before pause-flush edits the buffer; backspace after flush does not mutate the flushed event.
6. Window switch mid-buffer seals prior events under the old heading; new keys go to the new heading.
7. Hotkeys in a burst flush as part of the joined string.
8. Existing privacy and flush-restore unit tests still pass.
9. Typing-pause path does not set F5 section trigger `typing_pause`; a later file-flush seal of those events uses `file_flush` when F5 is present.
10. No JSONL / SQLite / sidecar files are introduced.

---

## 10. TDD test plan (Given / When / Then)

Use a testable monotonic clock and inject key/buffer helpers; do not require live pynput in unit tests. Prefer `typing_pause_sec=0.5` in tests unless the case asserts a different value.

### Idle flush happy path

**T-F3-01**  
Given: not paused; key buffer `["h","i"]`; last key activity at t=0; `typing_pause_sec=0.5`  
When: time advances to t=0.5 s and idle check runs  
Then: `_current_events` ends with `"hi"`; key buffer empty; `_sections` unchanged by this path; no file write required.

**T-F3-02**  
Given: empty key buffer; idle ≥ `typing_pause_sec`  
When: idle check runs  
Then: `_current_events` unchanged (no empty string event).

### Continuous typing

**T-F3-03**  
Given: keys at t=0.0, t=0.2, t=0.4 with `typing_pause_sec=0.5`  
When: time is t=0.6 (0.2 s since last key)  
Then: buffer still holds all chars; no burst flush yet.

**T-F3-04**  
Given: same as T-F3-03  
When: time advances to t=0.4 + 0.5 s without new keys  
Then: one joined event with full burst; buffer empty; still no section seal from typing pause.

### Backspace

**T-F3-05**  
Given: buffer `["a","b","c"]`  
When: backspace then idle flush  
Then: event `"ab"` only.

**T-F3-06**  
Given: event `"ab"` already flushed by typing pause; buffer empty  
When: backspace  
Then: `_current_events` still `["ab"]` (no pop from events).

**T-F3-07**  
Given: buffer `["a"]`  
When: backspace (buffer empty) then idle check  
Then: no new event appended.

### Hotkeys and special tokens

**T-F3-08**  
Given: buffer encodes `["a", "[CMD+C]"]` (or equivalent tokens from `on_press` rules)  
When: typing-pause flush  
Then: single event string contains both tokens in order.

**T-F3-09**  
Given: buffer includes `\n[ENTER]\n` token  
When: typing-pause flush  
Then: joined event preserves the token (no stripping).

### Pause / privacy

**T-F3-10**  
Given: buffer `["s","e","c"]`; not yet idle-flushed  
When: pause becomes true  
Then: buffer empty; `_current_events` does not gain `"sec"`; modifiers cleared.

**T-F3-11**  
Given: buffer non-empty; idle would fire at t=0.5 s  
When: pause at t=0.4 s, unpause at t=0.6 s, no new keys  
Then: no flush of the discarded keys at t=0.6 s or later.

**T-F3-12**  
Given: paused  
When: simulated key press  
Then: buffer stays empty; idle timer does not schedule a flush of those keys.

**T-F3-13**  
Given: paused with pending idle callback/timer from before pause  
When: timer fires while paused  
Then: no append to `_current_events`.

**T-F3-14**  
Given: unpaused; user types `"ok"` after a prior discard-on-pause  
When: typing-pause flush  
Then: only `"ok"` is appended (no resurrected pre-pause chars).

### Mid-type click / add_event

**T-F3-15**  
Given: buffer `["x"]`  
When: `add_event("🖱️ …")` before idle  
Then: events are `["x", "🖱️ …"]` (keys flushed first); same as today.

### Window switch mid-buffer

**T-F3-16**  
Given: heading A; buffer `["a"]`; events empty  
When: heading changes to B (window checker path)  
Then: sealed section under A contains `"a"` (or events path equivalent); buffer empty; heading B; new typing starts fresh; idle timer has no leftover deadline from A.

**T-F3-17**  
Given: heading A; events already `["hello"]` from prior typing pause; buffer `["!"]`  
When: heading changes to B  
Then: sealed section under A contains `hello` and `!` in order; nothing left in open events for A.

### File flush coordination

**T-F3-18**  
Given: open events from typing-pause flushes; `_sections` may be empty  
When: `flush_to_file` runs  
Then: keys flushed if any; open events sealed; Markdown write attempted; success clears batch (existing restore-on-failure tests still hold).

**T-F3-19**  
Given: F2 config sets `flush_interval_sec=5`  
When: file writer loop uses config  
Then: sleep/interval is 5, not hard-coded 30 only.

### F5 reason / trigger contract

**T-F3-20**  
Given: typing-pause flush runs  
When: key-flush cause is observed by test double / hook  
Then: cause equals `typing_pause`; `_sections` length is unchanged by this flush.

**T-F3-21**  
Given: events already chunked by typing pause; no app switch  
When: `flush_to_file` seals the open section (F5 enabled)  
Then: section trigger equals `file_flush` (not `typing_pause`).

### Modifier-only and races

**T-F3-22**  
Given: non-empty buffer; last buffer-mutating key at t=0; `typing_pause_sec=0.5`  
When: only modifier-only presses occur before t=0.5 s  
Then: idle flush still occurs at t=0.5 s (modifiers did not reset the timer).

**T-F3-23**  
Given: idle about to fire and `add_event` concurrent under lock  
When: both complete  
Then: no duplicate join of the same keystrokes; no lost click event; lock rules prevent double-append of the same buffer content.

**T-F3-24**  
Given: idle about to fire and window heading change concurrent under lock  
When: both complete  
Then: keys appear once under the correct heading; no duplicate burst event.

---

## 11. Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Idle too short | Many tiny events; noisier logs | Default 0.5 s; F2 tunable |
| Idle too long | Little gain vs today | Tunable; tests may use 0.5 s |
| Timer thread vs pynput thread races | Duplicate or lost bursts | Single lock around buffer + events; idle check under same lock |
| Pause vs pending timer | Secrets flushed after pause | Cancel/ignore timers; discard on pause edge; T-F3-10–14 |
| F5 expects seal-on-typing-pause | Spec clash | F3 locks no-seal; F5 must treat `typing_pause` as reserved until a new decision |
| Config name drift (`typing_pause_ms`) | Broken wiring vs F2 | Use `typing_pause_sec` only |
| Dual F2 flush keys | Ambiguous interval | F3 reads `flush_interval_sec` only |
| More events before file flush | Larger in-memory `_current_events` | Still bounded by file flush interval |

---

## 12. Implementation notes (high-level)

Implemented under FINAL_ACCEPT. Historical build notes:

1. Store last buffer-mutating activity as a monotonic timestamp.
2. Add an idle checker (short tick or dedicated loop) that respects `typing_pause_sec` and the shared lock.
3. Reuse `_flush_keys()` join/clear semantics; tag key-flush cause `typing_pause` for tests only.
4. Do **not** seal `_sections` and do **not** call `flush_to_file` from typing pause.
5. On pause edge: keep discard behavior; clear last-key timestamp or mark idle check inert until the next key after unpause.
6. Replace `FLUSH_INTERVAL_SEC` literal usage with F2 `flush_interval_sec`; keep default 30.
7. Unit tests in `tests/` (T-F3-*); keep existing privacy/flush-restore tests green.
8. After binary change: production path remains `./scripts/rebuild_and_restart.sh` (certificate leaf). Smoke: type, brief pause, wait ≤ file interval → `daily_log_*.md` grows with burst text.

---

## 13. Spec checklist

- [x] Char-level keys kept (no Screenpipe-style removal)
- [x] Typing-pause vs file-flush definitions separated
- [x] Privacy pause buffer clearing preserved
- [x] F5 coordination: no seal on typing pause → no section trigger `typing_pause` from F3 v1
- [x] Config aligned with F2: `typing_pause_sec` (default 0.5), `flush_interval_sec`
- [x] F5 `typing_pause` marked reserved (no seal from F3 v1)
- [x] TDD edges: backspace, hotkeys, pause mid-type, window switch, modifier-only, races
- [x] No JSONL / SQLite creep (NG2, FR-F3-018)
- [x] F5 spec marks `typing_pause` reserved until seal-on-burst is approved
- [x] Tests T-F3-01…24 (see `tests/`; implemented under FINAL_ACCEPT)
- [x] Privacy discard-on-pause reconfirmed in CI

---

## Critic revision log

**2026-08-15**

- Locked F3 v1: typing-pause = keys → `_current_events` only; no section seal; no file write.
- Removed F5 contradiction: F3 must not emit section trigger `typing_pause`; later seals use `file_flush` / other F5 causes.
- **Aggregate:** config aligned with F2 — `typing_pause_sec` default **0.5** (not `typing_pause_ms` / 800); `flush_interval_sec` is the only file-flush key.
- Clarified two-layer definitions (typing-pause burst flush vs file flush) and key-flush cause vs section trigger.
- Strengthened privacy: discard on pause; cancel/ignore pending idle; no resurrection after unpause.
- Expanded TDD: empty-after-backspace, Enter token, post-unpause burst, modifier-only idle, window+idle race.
- Added FR-F3-018 and AC10 against JSONL/SQLite/sidecars.
- F5 keeps `typing_pause` in the closed set as **reserved** until a future seal-on-burst decision.

**Verdict: FINAL_ACCEPT**
