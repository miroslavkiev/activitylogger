# ActivityLogger — locked product decisions (2026-08-15)

This file is the contract for all feature specs. Do not expand scope.

Index of locked decisions and feature links: [`00-MASTER.md`](00-MASTER.md).

## Product job
Personal macOS input transcript → daily Markdown → cleaner → Gemini automation analysis.

## Approved constraints (KEEP)
- Certificate-signed `.app` + `open -W` launchd chain (TCC identity)
- Char-level keystrokes + hotkey encoding
- Secure app/field pause with tests
- Daily Markdown as primary (and only) log artifact
- `clean_markdown_log.py` + Gemini prompt (no new redaction requirement)
- Single-process Python capture core

## Approved work items
| ID | Priority | Feature |
|----|----------|---------|
| F1 | P0 | Decouple window titles from hard ActivityWatch dependency (native first) |
| F2 | P0 | Replace hard-coded paths/tunables with config |
| F3 | P1 | Improve flush model (typing-pause burst flush; keep durable file flush) |
| F4 | P0 | Optional browser URL capture |
| F5 | P1 | Capture-trigger metadata on sections |
| F6 | P2 | Optional scroll coalescing |
| F0 | Avoid | Do NOT build JPEG / audio / pipes platform (another app covers that) |

## Explicitly ignored (out of scope)
- JSONL / SQLite sidecars
- Cleaner secret redaction pass
- Locale / Ukrainian label changes
- Broader ignore-lists for apps/windows
- Local query API / MCP
- Retention policy automation
- OCR fallback

## Shared non-negotiables
- No Screen Recording / mic / JPEG capture pipeline in ActivityLogger
- Markdown-only storage for user-facing logs
- Privacy pause for password managers and AX secure fields must not regress
- Production rebuild remains `./scripts/rebuild_and_restart.sh` with certificate leaf DR
- Specs must be test-driven: acceptance criteria + failing-test list before implementation notes
