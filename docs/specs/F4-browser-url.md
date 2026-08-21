# F4 optional browser URL capture

**Status:** implemented, opt-in, and source-verified on 2026-08-21.

## Feature and sources

`features.browser_url_capture` defaults to `false`. When disabled, ActivityLogger does not poll a browser and does not send Apple Events.

When enabled for a supported frontmost browser, the provider tries Accessibility first and Apple Events second. A browser may produce a native Automation prompt for the Apple Events fallback. No screenshot, Screen Recording, pixel read, or OCR path is allowed.

## Privacy normalization

The default `privacy.unsafe_full_browser_urls = false` applies total query neutralization:

1. Accept only a valid supported URL shape.
2. Remove user information.
3. Remove the fragment.
4. Replace every query parameter name and value with neutral placeholders, including repeated and blank fields.
5. Apply the output length cap.

The safe representation keeps useful scheme, host, port, and path context without retaining query secrets or even query key names.

`unsafe_full_browser_urls = true` is an explicit privacy-risk opt-in and emits a startup warning. It may retain sensitive path and query material, but still removes user information and fragments. The compactor does not make unsafe URLs safe.

## Event and trigger behavior

Only a changed normalized URL is recorded. The Markdown event starts with the stable URL marker consumed by the analysis prompt. With capture-trigger annotations off, the event remains in the open section. With annotations on, the URL event seals the section with `url_change`.

## Fail-closed asynchronous behavior

Every URL observation records the privacy generation and browser context before external work. The result is discarded if capture pauses, privacy generation changes, the frontmost browser changes, or shutdown starts. A provider failure is diagnostic-only and never stops other capture.

Accessibility and Apple Events calls have time budgets. Repeated failures enter per-source and per-application backoff to prevent tight retry loops and repeated consent noise.

## TCC behavior

Base capture requires Accessibility and Input Monitoring. Browser URL capture may additionally require Automation for an enabled browser. The option is off by default specifically to avoid expanding capture and TCC scope without operator consent.

## Acceptance

Tests cover disabled-provider silence, supported browser mapping, Accessibility precedence, Apple Events fallback, total query neutralization, user information and fragment removal in both modes, output caps, privacy generations, context changes, timeouts, backoff, and trigger integration.
