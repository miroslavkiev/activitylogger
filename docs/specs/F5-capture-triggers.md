# F5 — Capture-trigger metadata on sections

| Field | Value |
|-------|--------|
| ID | F5 |
| Priority | P1 |
| Status | Implemented (F5_ACCEPT; FINAL_ACCEPT) |
| Scope contract | [`00-SCOPE.md`](00-SCOPE.md) |
| Depends on | Section model in `interleaved_logger.py`; cleaner parse in `clean_markdown_log.py`; F2 key `features.capture_triggers_enabled` |
| Coordinates with | F3 (`typing_pause`), F4 (`url_change`), F6 (`scroll_coalesce`) |
| Out of scope | JSONL / SQLite; Screen Recording; OCR; new redaction; rewrite of old logs |

## 1. Summary

When the operator enables capture triggers, each new Markdown **section** records **why** the logger sealed that section.

The tag is one token from a **closed set**. The log stays human-readable. Gemini and `clean_markdown_log.py` accept both new and old files.

**Default: OFF.** F2 key `features.capture_triggers_enabled` defaults to `false` (opt-in). With the flag OFF, seal and Markdown behaviour match today (no trigger field, no click/clipboard seal from F5).

## 2. Previous behaviour (baseline before F5)

As of the code under test today:

1. In-memory section shape: `{heading, events, timestamp}` (no trigger).
2. Seal into `_sections` happens when:
   - the active heading changes and `_current_events` is non-empty (`window_checker_loop`);
   - the durable file flush runs and `_current_events` is non-empty (`flush_to_file`).
3. Markdown write format:

```markdown
## {app} — {title}
*{HH:MM:SS}*

{event}

---
```

4. Clicks and clipboard changes call `add_event` only. They do **not** seal a section.
5. `clean_markdown_log.py` treats the line after `##` as optional timestamp via  
   `RE_TIMESTAMP_LINE = ^\*\d{2}:\d{2}:\d{2}\*\s*$`.
6. `prompts/gemini-automation-analysis.md` describes heading + `*HH:MM:SS*` only.

## 3. Goal

1. Add field `trigger` on every section sealed while the feature is ON.
2. Write that field into Markdown with one fixed syntax (see §6).
3. Use one closed enum shared with F3 / F4 / F6.
4. Gate all F5 behaviour on `capture_triggers_enabled` (default `false`).
5. Do **not** rewrite existing log files.
6. Keep privacy pause behaviour unchanged.

## 4. Feature flag (F2)

| Item | Rule |
|------|------|
| Config key | `features.capture_triggers_enabled` (F2) |
| Default | **`false` (opt-in)** |
| Missing key | Treat as `false` |
| Why opt-in | Matches F2: triggers are metadata. Operators enable after F5 ships. Avoids new tokens and new section cuts in default logs. |

### Flag OFF (default)

1. Do not set or require `trigger` on sealed sections.
2. Write the legacy timestamp line: `*{HH:MM:SS}*`.
3. Do **not** seal on click or clipboard (same as baseline §2).
4. Sibling features may still run. They must not write `trigger:…` into Markdown while this flag is OFF.

### Flag ON

1. Every newly sealed section has exactly one closed-set `trigger`.
2. Write `*{HH:MM:SS} · trigger:{name}*` (§6).
3. Apply F5 click and clipboard seal paths (FR-F5-005 / FR-F5-006).
4. Sibling seal paths that run under this flag use their reserved names (FR-F5-007).

Mid-day toggle: only sections sealed after the effective ON state get triggers. Prior lines in the same file stay as written. No backfill.

## 5. Closed set of trigger names

Canonical names (snake_case, ASCII). Writers use **only** these strings.

| Name | Meaning | Owner | Status |
|------|---------|--------|--------|
| `app_switch` | Prior section sealed because the active app/window heading changed | Core + F5 | Active when flag ON |
| `click` | Prior open buffer sealed because a mouse click was logged | F5 | Active when flag ON |
| `typing_pause` | Reserved for a future seal-on-burst mode | F3 (future) | **Reserved — unused in F3 v1** |
| `clipboard` | Prior open buffer sealed because a clipboard change was logged | F5 | Active when flag ON |
| `file_flush` | Open buffer sealed by durable periodic or shutdown file flush with no higher-priority seal cause | Core + F5 | Active when flag ON |
| `url_change` | Prior section sealed because the F4 URL-change path sealed the buffer | F4 | Active when F4 ON and F5 flag ON (F4 seals on URL change) |
| `scroll_coalesce` | Section sealed for an F6 coalesced scroll summary | F6 | Active when F6 seals and flag ON |

### Naming rules

- Do not invent aliases (`idle`, `window_change`, `paste`, `scroll`).
- Do not write `unknown` or empty trigger from the producer.
- Parsers may treat a **missing** trigger on old files (or flag-OFF files) as “unspecified”. That is not a writer value.
- One section → exactly one trigger when the flag is ON.
- **`typing_pause` is reserved.** F3 v1 only moves keys into `_current_events` (no section seal). Producers MUST NOT emit `typing_pause` until a later product decision revises F3. Keep the name in the closed set so enum tests stay stable.

### Priority when more than one cause could apply

At seal time, choose the **initiating** cause of that seal call. Do not summarise later body events.

Examples:

- Heading change while a timer is also due → `app_switch`.
- Click that also flushes keys → `click`.
- Periodic flush with no other seal call → `file_flush`.
- F3 typing-pause burst that only flushes keys → **no** section seal; a later `file_flush` (or `click` / `app_switch`) owns the trigger.
- Do **not** stamp `typing_pause` on a later seal that merely contains earlier typing-pause bursts.

## 6. Exact Markdown syntax

This section is the **only** normative trigger markup. Sibling specs must not define a second layout.

### 6.1 New section header block (flag ON)

```markdown
## {app} — {title}
*{HH:MM:SS} · trigger:{name}*

{event lines…}

---
```

Concrete example:

```markdown
## Safari — Example Domain
*14:02:11 · trigger:url_change*

> [URL]: https://example.com

---

## Safari — Example Domain
*14:02:40 · trigger:file_flush*

hello world

---

## Code — interleaved_logger.py
*14:03:05 · trigger:app_switch*

[CMD+S]

---
```

Note: `typing_pause` does **not** appear in live examples until a future F3 seal-on-burst decision. The closed set still lists it as reserved.
### 6.2 Grammar

- Timestamp line (flag ON): `*{HH:MM:SS} · trigger:{name}*`
- Timestamp line (flag OFF or legacy): `*{HH:MM:SS}*`
- Literal separator between time and trigger: space, middle dot `·` (U+00B7), space.
- Prefix `trigger:` is required (lowercase, **no space** after the colon).
- `{name}` is one token from the closed set.
- No other metadata on that line.
- Do **not** use a second italic line such as `*trigger: name*`.
- Do **not** put a space after `trigger:`.
- Heading line `## …` is unchanged (F1 still owns title source).
- Event body format is unchanged.
- Section separator `---` is unchanged.

### 6.3 Rejected alternatives (do not use)

- HTML comments (`<!-- trigger:… -->`) — weak Gemini visibility.
- JSON / YAML front matter per section — out of Markdown-only product job.
- Trigger in the `##` heading — breaks app/title parse and secure-pause labels.
- Second metadata line after the timestamp — harder for humans; prefer one italic line.
- `*trigger: name*` with a space after the colon — not valid.

## 7. Functional requirements

### FR-F5-000 — Opt-in flag

Runtime MUST read `features.capture_triggers_enabled` from F2 config.  
Default and missing key MUST be `false`.  
All FR-F5-001…007 and FR-F5-012 apply only when the flag is `true`, except FR-F5-009 / FR-F5-010 (readers and prompt stay dual-format).

### FR-F5-001 — Section dict carries trigger

When the flag is ON, every call that appends to `_sections` MUST set `trigger` to a closed-set name.

### FR-F5-002 — Markdown emits trigger

When the flag is ON, `flush_to_file` (and any write path) MUST emit  
`*{timestamp} · trigger:{trigger}*` for every new section.  
When the flag is OFF, emit legacy `*{timestamp}*` only.

### FR-F5-003 — `app_switch` seal

When the flag is ON, the heading changes, and the prior buffer is sealed, `trigger` MUST be `app_switch`.

### FR-F5-004 — `file_flush` seal

When the flag is ON and the durable periodic flush (or orderly shutdown flush) seals the open buffer **without** another seal cause, `trigger` MUST be `file_flush`.

### FR-F5-005 — `click` seal

When the flag is ON and a click is logged (privacy not paused):

1. Flush keystrokes into events.
2. Append the click event.
3. Seal the non-empty buffer into `_sections` with `trigger=click`.
4. Leave heading unchanged; start a new empty open buffer.

When the flag is OFF, keep baseline: `add_event` only; do not seal.

### FR-F5-006 — `clipboard` seal

When the flag is ON and a clipboard event is logged (privacy not paused):

1. Flush keystrokes into events.
2. Append the clipboard event.
3. Seal the non-empty buffer with `trigger=clipboard`.

When the flag is OFF, keep baseline: `add_event` only; do not seal.

### FR-F5-007 — Reserved names for sibling features

- **`typing_pause`:** reserved in the closed set. F3 v1 MUST NOT emit it (keys → events only; no seal). A future seal-on-burst mode may use this name after F3 is revised.
- **F4 + F5 ON:** F4’s URL-change path MUST seal after appending `> [URL]: …`, with trigger `url_change` (same seal pattern as click). F4 alone (F5 OFF) MUST NOT seal.
- **F6 + F5 ON:** F6 MUST use `scroll_coalesce` when a coalesced scroll note seals.
- F5 owns the closed-set names and Markdown syntax (§6). Sibling features own their seal paths. F5 does **not** seal URL or scroll by itself.
- Until F4/F6 seal paths land, the producer MUST NOT emit `url_change` / `scroll_coalesce` except via those features.
- Sibling features MUST NOT write trigger markup when `capture_triggers_enabled` is `false`.

### FR-F5-008 — Closed-set enforcement

A shared constant (for example `CAPTURE_TRIGGERS: frozenset[str]`) is the single source of truth.  
When the flag is ON, tests MUST reject any other string at the write boundary.

### FR-F5-009 — Cleaner compatibility

`clean_markdown_log.py` MUST:

1. Accept legacy `*HH:MM:SS*` lines.
2. Accept new `*HH:MM:SS · trigger:{name}*` lines.
3. Keep trigger lines out of “noise event” treatment (same class as timestamps: metadata, not body events).
4. Preserve the trigger line in cleaned output when the section is kept.

### FR-F5-010 — Gemini prompt update

`prompts/gemini-automation-analysis.md` documents:

- optional ` · trigger:{name}` on the time line;
- the closed set and short meanings;
- that older logs and flag-OFF runs may omit the trigger.

Do not re-edit that prompt in docs-only passes.

### FR-F5-011 — No sidecar formats

Do not add JSONL, SQLite, or parallel metadata files for triggers.

### FR-F5-012 — No rewrite of old logs

Do not ship migration tooling that edits existing `daily_log_*.md` files.  
Only sections sealed after F5 is ON get `trigger`.

## 8. Privacy

| Rule | Requirement |
|------|-------------|
| P-F5-1 | While secure-app or secure-field pause is active, do not seal sections that contain paused keystrokes or secrets (existing pause rules stay). |
| P-F5-2 | Trigger names carry no user content (no URL, title, or clipboard text in the trigger token). |
| P-F5-3 | Click / clipboard seal paths must still call through `is_paused()` / existing pause gates before logging or sealing. |
| P-F5-4 | Secure pause headings (`🔒 [SECURE …]`) remain heading text only; do not invent a `secure_pause` trigger. |
| P-F5-5 | Flag ON or OFF must not weaken pause. Trigger metadata is never a bypass. |

## F0 impact

| F0 item | F5 effect |
|---------|-----------|
| K1 Launch + signing | Untouched. |
| K2 Keystrokes | Untouched encoding; click/clipboard may seal earlier when flag ON. |
| K3 Secure pause | Seal paths must still respect pause (P-F5-*). |
| K4 Markdown-only | Trigger lives on the italic time line; no sidecar. |
| K5 Cleaner + prompt | Cleaner must accept legacy and new timestamp lines; prompt documents triggers. |
| K6 Single-process | Untouched. |
| B1–B4 Bans | Stay banned. |

Default OFF keeps cadence unchanged until the operator opts in.

## 9. Acceptance criteria

1. With default config (`capture_triggers_enabled` false / unset): new sections use `*{HH:MM:SS}*` only; click and clipboard do not seal.
2. With flag ON: new sections in `daily_log_*.md` always include ` · trigger:{name}` with a closed-set name.
3. App switch seals use `app_switch`.
4. Timer-only seals use `file_flush`.
5. A click after typing (flag ON) produces a sealed section with `trigger:click` that includes the typed text and the click event (order defined in tests).
6. A clipboard change after typing (flag ON) produces `trigger:clipboard`.
7. Legacy files without triggers still clean and still work with the Gemini prompt.
8. No existing log file is rewritten by migration tooling.
9. Unit tests listed in §10 fail before implementation and pass after.
10. Privacy tests still pass; paused click/clipboard does not create a triggered section with secret text.

## 10. TDD — failing tests first

Implement tests before production code. Suggested module: `tests/test_capture_triggers.py` (plus cleaner updates in `tests/test_privacy_and_cleaner.py`).

### T-F5-01 — Closed set constant

- **Given** the public trigger set  
- **Then** it equals exactly  
  `{app_switch, click, typing_pause, clipboard, file_flush, url_change, scroll_coalesce}`.

### T-F5-02 — Reject unknown trigger on write

- **Given** flag ON and a section dict with `trigger="idle"`  
- **When** formatting the Markdown timestamp line  
- **Then** the writer raises / asserts (fail closed); no line is written.

### T-F5-03 — Format helper

- **Given** timestamp `14:02:11` and trigger `app_switch`  
- **When** formatting  
- **Then** output is exactly `*14:02:11 · trigger:app_switch*` (newline policy fixed in one place in the test; no space after `trigger:`).

### T-F5-04 — App switch seals with `app_switch`

- **Given** flag ON; open events under heading A  
- **When** heading changes to B  
- **Then** one section is appended with `trigger == "app_switch"` and heading A.

### T-F5-05 — Periodic flush seals with `file_flush`

- **Given** flag ON; open events, same heading  
- **When** `flush_to_file()` seals them without an app switch  
- **Then** the written Markdown contains `trigger:file_flush`.

### T-F5-06 — Click seals with `click`

- **Given** flag ON; typed keys in the open buffer (not paused)  
- **When** a click is processed  
- **Then** a section is sealed with `trigger == "click"` and events include the typed text and the click line.

### T-F5-07 — Clipboard seals with `clipboard`

- **Given** flag ON; typed keys (not paused)  
- **When** a clipboard event is applied  
- **Then** a section is sealed with `trigger == "clipboard"`.

### T-F5-08 — Paused click does not seal secrets

- **Given** flag ON; pause active  
- **When** click occurs  
- **Then** no new section with user keystrokes is sealed; trigger path does not bypass pause.

### T-F5-09 — Paused clipboard does not seal secrets

- **Given** flag ON; pause active and clipboard text changes  
- **When** `apply_clipboard_change` / checker path runs  
- **Then** markers advance per existing privacy tests; no `trigger:clipboard` section with that text.

### T-F5-10 — Cleaner accepts legacy timestamp

- **Given** a section with only `*12:00:00*`  
- **When** `split_into_preamble_and_sections` / clean runs  
- **Then** the section is parsed; no crash.

### T-F5-11 — Cleaner accepts trigger timestamp

- **Given** `*12:00:00 · trigger:app_switch*`  
- **When** clean runs  
- **Then** the line is kept as metadata and the section body is cleaned as today.

### T-F5-12 — Cleaner does not count trigger line as noise event

- **Given** a section whose only non-separator content is the trigger timestamp line plus blank lines  
- **When** meaningful-content checks run  
- **Then** behaviour matches “timestamp-only” sections (empty / drop), not “has event text”.

### T-F5-13 — File output round-trip

- **Given** flag ON; a sealed section `{heading, events, timestamp, trigger}`  
- **When** written via the real write path to a temp log  
- **Then** the file contains the heading, the exact trigger timestamp line, events, and `---`.

### T-F5-14 — Sibling name reservation (contract tests)

- **Given** F3/F4/F6 not implemented or F3 v1 only  
- **Then** contract tests document that `typing_pause`, `url_change`, and `scroll_coalesce` are valid enum members.  
- **And** `typing_pause` is marked reserved: F3 key-flush must not set section `trigger=typing_pause`.  
- **And** optional stub tests show the intended seal → name mapping for F4 (`url_change` when F4+F5 ON) and F6 (`scroll_coalesce`).

### T-F5-15 — Gemini prompt mentions triggers

- **Given** `prompts/gemini-automation-analysis.md`  
- **When** read by test (substring asserts)  
- **Then** it mentions `trigger:` and at least `app_switch` and `file_flush`, and notes older logs may omit the field.

### T-F5-16 — Flag OFF writes legacy timestamp

- **Given** `capture_triggers_enabled = false` (or unset)  
- **When** a section is sealed by app switch or file flush and written  
- **Then** the timestamp line matches `*{HH:MM:SS}*` and does **not** contain `trigger:`.

### T-F5-17 — Flag OFF does not seal on click

- **Given** flag OFF; typed keys in the open buffer  
- **When** a click is processed  
- **Then** the click is appended via `add_event` semantics; no section is sealed solely for the click.

### T-F5-18 — Flag OFF does not seal on clipboard

- **Given** flag OFF; typed keys in the open buffer  
- **When** a clipboard event is applied  
- **Then** no section is sealed solely for the clipboard event.

### T-F5-19 — No migration rewrite

- **Given** a fixture that copies a sample legacy `daily_log_*.md`  
- **When** F5 code paths run (load / clean / write new sections elsewhere)  
- **Then** the legacy fixture bytes are unchanged.

## 11. Migration (existing logs)

| Rule | Decision |
|------|----------|
| Rewrite old `daily_log_*.md` | **No** |
| Backfill triggers | **No** |
| Reader behaviour | Missing trigger = unspecified |
| Cleaner | Dual regex / dual predicate for timestamp lines |
| Gemini | Prompt states triggers are optional on historical files and when the flag is OFF |
| In-memory only | Only sections sealed **after** F5 is ON get `trigger` |
| Flag default | `false` until the operator opts in |

No migration script. No one-shot rewrite job.

## 12. Gemini prompt impact

Shipped Data format bullets in `prompts/gemini-automation-analysis.md` cover:

1. Optional ` · trigger:{name}` on the same italic line.
2. Closed set with one-line meanings.
3. Use triggers when present; do not invent them for older sections.
4. Existing guidance on keystrokes, hotkeys, clipboard, and clicks.

Do not re-edit that prompt in docs-only passes. Do not change the automation output schema (Week in review / Patterns / Suggested automations / Top 3).

## 13. Coordination matrix (F3 / F4 / F6)

| Feature | Uses trigger | When |
|---------|--------------|------|
| F3 | `typing_pause` | **Reserved.** F3 v1 does not seal on typing idle. Do not emit this trigger until F3 is revised. |
| F4 | `url_change` | When F4 ON and F5 ON: F4 seals on URL change with this trigger. When F5 OFF: F4 appends `> [URL]:` only (no seal). |
| F5 | Owns enum, Markdown syntax, flag gating, and `app_switch` / `click` / `clipboard` / `file_flush` | This spec |
| F6 | `scroll_coalesce` | When a coalesced scroll summary seals or creates a section per F6 |

If F3 only flushes keys into the open event list and does **not** seal, it must **not** set `typing_pause` on a later `file_flush` section. The seal cause wins.

Sibling Markdown examples that show a second `*trigger: …*` line are **non-normative**. §6 of this file wins.

## 14. Implementation notes (after tests fail)

Order:

1. Wire `capture_triggers_enabled` (default `false`) from F2.
2. Add `CAPTURE_TRIGGERS` and format/parse helpers.
3. Extend section dict; update all `_sections.append` call sites behind the flag.
4. Change click and clipboard paths to seal only when the flag is ON (FR-F5-005/006).
5. Update `RE_TIMESTAMP_LINE` (or split legacy vs new predicates).
6. Gemini prompt already documents triggers (leave unchanged in docs-only work).
7. Rebuild signed app only when the logger binary changed: `./scripts/rebuild_and_restart.sh`.

Do not expand scope beyond Markdown section triggers.

## 15. Traceability

| AC / FR | Tests |
|---------|-------|
| FR-F5-000, AC1 | T-F5-16, T-F5-17, T-F5-18 |
| FR-F5-001–002, AC2 | T-F5-03, T-F5-13 |
| FR-F5-003, AC3 | T-F5-04 |
| FR-F5-004, AC4 | T-F5-05 |
| FR-F5-005, AC5 | T-F5-06 |
| FR-F5-006, AC6 | T-F5-07 |
| FR-F5-008 | T-F5-01, T-F5-02 |
| FR-F5-009, AC7 | T-F5-10–12 |
| FR-F5-010, AC7 | T-F5-15 |
| FR-F5-011 | Spec + review (no sidecar files) |
| FR-F5-012, AC8 | T-F5-19 |
| Privacy P-F5-* / AC10 | T-F5-08, T-F5-09 |
| Migration AC8 | T-F5-19; no rewrite of real logs |

---

## Critic revision log

**Verdict: FINAL_ACCEPT**

| Checklist item | Finding | Change |
|----------------|---------|--------|
| 1. Closed trigger enum vs F3/F4/F6 | Names matched; F3 does not seal | Kept enum; marked `typing_pause` **reserved / unused** for F3 v1 |
| 2. Markdown human + Gemini friendly | One italic line with `· trigger:{name}` | Locked §6 as sole normative syntax |
| 3. Default enable vs F2 | Opt-in vs always-on | **Aggregate:** F2 and F5 both use `capture_triggers_enabled = false` |
| 4. No JSONL/SQLite | Already out of scope | Kept FR-F5-011 |
| 5. TDD adequacy | Flag-OFF and no-rewrite | T-F5-16…19; reserved-name contract in T-F5-14 |
| 6. Old logs not rewritten | Stated | FR-F5-012 + T-F5-19 |
| 7. STE clarity | Flag behaviour | Explicit OFF/ON lists |

**Aggregate critic (2026-08-15):** Flag matches F2. `typing_pause` reserved. Examples use `file_flush` instead of a live `typing_pause` seal.

**Independent aggregate verifier (2026-08-15):** Fixed §5→§6 Markdown syntax cross-refs. Locked F4+F5 ON → F4 seals with `url_change` (was “optional per F4”).

*End of F5 spec.*
