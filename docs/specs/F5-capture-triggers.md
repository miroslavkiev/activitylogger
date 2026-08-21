# F5 capture triggers and ordered click sections

**Status:** implemented, opt-in, and source-verified on 2026-08-21.

## Trigger annotations

`features.capture_triggers_enabled` defaults to `false`. When enabled, each ordinary sealed section carries exactly one cause from the closed set:

- `app_switch`
- `click`
- `clipboard`
- `file_flush`
- `scroll_coalesce`
- `url_change`

`typing_pause` is reserved and rejected if a caller attempts to emit it. The Markdown timestamp line includes the trigger token only when the option is enabled. Old and new logs remain parseable by the compactor and analysis prompt.

## Seal behavior

| Event | Annotations off | Annotations on |
|---|---|---|
| App switch | Seal old context | Seal with `app_switch` |
| File flush | Seal open context | Seal with `file_flush` |
| Clipboard change | Append to open context | Append and seal with `clipboard` |
| URL change | Append to open context | Append and seal with `url_change` |
| Scroll burst | Seal one burst section | Seal with `scroll_coalesce` |
| Typing idle | Join keys only | Join keys only |

Clicks use the ordered reservation model below in both annotation modes.

## Click ordering and privacy

The mouse callback performs a synchronous secure-app and secure-field check. If safe, it flushes earlier keys and events and reserves the click's exact section position with a capture timestamp, privacy generation, and window context. Accessibility enrichment then runs off the callback thread.

The placeholder is resolved only if its generation and context still match and capture remains safe. Resolution replaces the placeholder with the click description and adds the `click` annotation when enabled. Failure, timeout, shutdown, context change, or pause removes the placeholder without emitting fabricated or context-shifted data.

Persistence never writes beyond an unresolved click placeholder, so later events cannot overtake it. Pending reservations have a bounded expiry and are awakened by the file writer deadline.

## Structural safety

Headings and inline values are sanitized so captured text cannot inject structural Markdown headings, trigger fields, or fences. Dynamic fence handling and fence-aware parsing preserve untrusted captured text as content. The compactor is compatible but is not a security redactor.

## Acceptance

Tests cover the closed trigger set, default compatibility, each seal path, reserved typing behavior, click sequence reservation, asynchronous completion ordering, expiry, privacy generation mismatch, context mismatch, write barriers, and Markdown injection resistance.
