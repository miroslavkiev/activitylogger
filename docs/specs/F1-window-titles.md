# F1 native-first window titles

**Status:** implemented and source-verified on 2026-08-21.

## Contract

ActivityLogger resolves the frontmost application and window title from macOS first. `NSWorkspace` supplies application context and Accessibility supplies window context. ActivityWatch is an optional enricher that fills only fields that native resolution left empty. It never overwrites a non-empty native field.

`window_titles.activitywatch_enricher` defaults to `true`, but the endpoint defaults to `http://localhost:5600` and only loopback hosts are accepted unless `activitywatch_allow_remote` is explicitly enabled. Remote access emits a privacy warning. User information in the ActivityWatch URL is rejected.

## Privacy behavior

Window resolution and secure-app matching are one privacy decision. Secure-app substrings are normalized and checked against both app and title. If the frontmost context cannot be verified, the logger does not treat that as safe. It preserves or enters a paused state until a safe result is known.

Every asynchronous application of a resolved window uses a generation guard. A stale result cannot clear a newer pause or attach capture to a newer context.

## Failure behavior

- Native resolution is authoritative when it returns data.
- ActivityWatch failure never stops key or click capture.
- ActivityWatch calls use short timeouts and per-source backoff after failure.
- An empty display title uses the runtime fallback heading without weakening the privacy decision.
- No Screen Recording or OCR fallback is permitted.

## Config keys

```toml
[window_titles]
activitywatch_enricher = true
activitywatch_base_url = "http://localhost:5600"
activitywatch_allow_remote = false
aw_backoff_sec = 45.0
```

All keys, validation bounds, and discovery rules are owned by [`F2-config.md`](F2-config.md).

## Acceptance

Tests cover native precedence, optional enrichment, empty fields, loopback validation, remote opt-in warnings, timeouts, failure backoff, secure matching, and stale-generation rejection.
