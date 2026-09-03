# ActivityLogger film research

## Research method

This research was read-only. It covered the current repository, the supplied Relay learning guide, the Ciklum design handoff, the HyperFrames product video workflow, and a current official Apple presentation reference. No private activity log or review file was opened.

The product source was `main` at commit `8df97d6` on 2026-09-03. The worktree was clean before this case-study folder was added.

## Product truth

ActivityLogger is a private work journal for one person on a Mac. It records observed work context into daily Markdown. It can prepare a private review pack for an exact window of five or seven consecutive completed calendar days. The person reviews and redacts the files, chooses a trusted review tool, and decides whether to act on any possible finding.

The useful story is not "track every minute." The useful story is "remember enough observed context to notice a pattern worth checking."

## Claim register

Release approval is not granted by this research. Recheck every claim against current `main` and get owner approval before public release.

| ID | Factual claim | Source and scope | Safe film wording | Limits |
|---|---|---|---|---|
| C01 | ActivityLogger is a private work journal for one person on a Mac. | `README.md`, lines 3-9 | "A private work journal for your Mac." | It is a managed local installation, not a public download-and-run product. |
| C02 | It writes observed activity into one private Markdown file per local calendar day. | `README.md`, lines 22-29; `docs/specs/00-MASTER.md`, lines 7-11 | "Observed context becomes a local daily Markdown trail." | Do not say it captures everything. |
| C03 | Base capture includes app and window context, typed characters and hotkeys, clicks, changed Accessibility text, and changed clipboard text. | `README.md`, lines 31-42; `docs/specs/00-MASTER.md`, lines 7-11 | "Examples include app and window context, typing and hotkeys, clicks, and clipboard changes." | Browser URLs, trigger labels, and scroll capture are optional. Do not present the short film list as complete. |
| C04 | It does not capture screenshots, Screen Recording, OCR, camera, microphone, audio, or video. | `README.md`, line 44; `docs/specs/00-SCOPE.md`, lines 55-69 | "No screenshots. No audio. No video." | Do not extend this into a general no-network claim. |
| C05 | Configured secure apps, secure fields, manual pause, the visible Review Center, and unknown privacy states pause capture through a fail-closed gate. | `README.md`, lines 56 and 71-73; `docs/specs/00-MASTER.md`, lines 22-26 | "Privacy controls tell capture when to step back." | An app must be on the configured secure-app list. Resume clears only the manual pause. Other secure reasons can remain. |
| C06 | The Review Center is payload-free and has three steps: create files, review files, and record what happened. | `README.md`, lines 46-58; `review_center.py`, lines 558-688 | Use the real three labels in a sanitized UI reconstruction. | Review files can contain captured private text even though the window does not show it. |
| C07 | A weekly pack uses exactly five or seven consecutive completed calendar days. Missing or unready days are not replaced. | `README.md`, lines 24-29; `weekly_review.py`, lines 69-131 | "Five completed calendar days. Every one ready." | A ready proof checks integrity, not continuous capture coverage. |
| C08 | ActivityLogger creates review files but does not analyze, upload, contact anyone, act on suggestions, or create an automation. | `README.md`, line 5; `docs/specs/00-SCOPE.md`, lines 30-40 | "It prepares the review. You choose the tool and the next step." | Never show ActivityLogger itself producing an insight. |
| C09 | ActivityLogger does not upload review files. The person must review and redact private text before any online use and chooses whether to share a copy. | `README.md`, lines 13-20 and 52-58; `docs/specs/00-SCOPE.md`, lines 38-40 | "Review it. Redact it. You decide whether to share a copy." | Files are sensitive plaintext, not encrypted. Optional unsafe remote ActivityWatch access is a separate network boundary and warns at startup. |
| C10 | A trusted review can look for repeated work, friction, possible errors, and small improvement ideas. | `README.md`, lines 11-18; `weekly_review.py`, lines 170-178 | "Possible patterns begin to surface." | Findings are suggestions that require human review. No result is promised. |
| C11 | Review outcomes are "Found an idea to try," "Tried a change," or "No action," with an optional value note. | `README.md`, lines 50-54; `review_center.py`, lines 643-667 | Use the real option labels. | Any task, idea, or value shown in the film must be marked illustrative. |
| C12 | ActivityLogger is not an exact time tracker. Work spans show observed activity, not proven effort time. Gaps can have several causes. | `README.md`, line 20; `weekly_review.py`, lines 159-168 | "Not proof of time spent. Clues worth checking." | Never infer wasted time or full coverage from timestamps. |
| C13 | Private directories use mode 700 and private files use mode 600. Files remain sensitive plaintext, are not redacted, and are not deleted automatically. | `README.md`, lines 75-91 | Keep this in the production trust notes, not the emotional peak. | Do not use "encrypted," "zero knowledge," or "automatic cleanup." |
| C14 | The latest recorded acceptance on 2026-09-01 reported 514 tests passed, 1 skipped, plus signed build and live Review Center checks. | `docs/specs/IMPL-STATUS.md`, lines 1-35 | Optional small proof label: "Recorded verification, Sep 1 2026: 514 passed, 1 skipped." | This is dated evidence, not a promise of future coverage. Keep it out of voiceover. |

## Safe simulated demo

No real data from `logs/` or `private_analysis_review/` may appear in the film.

Use these illustrative labels only:

- Apps: Notes, Browser, Mail, Editor
- Work items: Weekly update, project note, review comment
- Dates: Day 1 through Day 7, never a real local date
- Possible pattern: "The same weekly update starts from the same three parts"
- Possible human choice: "Try a local update template"
- Outcome: "Found an idea to try"

Every reconstructed screen must carry a small visible label: `Illustrative data`.

## Transferable lessons from the Relay guide

Source: the supplied Adidas Origo Relay repository's `docs/LEARNINGS.md`.

- Start with a claim register and keep source, scope, meaning, confidence, safe wording, and release approval clear.
- Give the story one human action. Put proof next to the event it explains.
- Give each scene one main subject. Use one signature motion only when it adds meaning.
- Put the fastest motion at the culmination. Earn the calm ending.
- Reuse visual rules, not old client layouts, copy, media, or private evidence.
- Reserve logo, caption, and safe areas before frame design.
- Test voice samples early. Measure final audio before locking scene starts.
- Render the supported master directly from HTML and vector source.
- Use automated checks and a full human watch and listen pass.
- Keep raw research, private source exports, render caches, and old renders out of Git.

## Recent Apple presentation reference

The current reference was Apple's official 84-second [Get ready for WWDC26](https://developer.apple.com/videos/play/wwdc2026/394/) film, reviewed on 2026-09-03. The [Apple Events page](https://www.apple.com/apple-events/) lists WWDC on June 8, 2026 as the latest completed event at that time.

Observed patterns, not Apple rules:

- A human opens and closes the story.
- Product screens are isolated on dark fields with much open space.
- One device or one message owns most frames.
- A dense people grid appears only as a short energy peak.
- Full-frame color changes mark chapters.
- The logo close is quiet and long enough to read.

The concepts borrow focus, pace, scale, clean product isolation, and a calm close. They do not copy Apple assets, layouts, gradients, transitions, or product staging.

## Ciklum design source

Source: the supplied Ciklum design handoff and its `DESIGN.md`.

The source is a static card catalog, not a component or motion library. `DESIGN.md`, lines 13-69 define the observed colors. Lines 81-105 define Sora and Manrope type roles. Lines 171-206 describe the card, chart, hero, and data slide treatments.

Important gaps are recorded in `DESIGN.md`, lines 227-239:

- No official Ciklum logo file
- No icon set
- No self-hosted font files
- No token file
- No motion rules

Option 3 uses the exact observed palette, type roles, spacing feel, and evidence layout. It does not show a Ciklum wordmark, claim Ciklum ownership, or copy a finished Ciklum slide.

## Timing conclusion

The HyperFrames product-launch workflow is strongest around 30 to 90 seconds. The three proposals sit at 84, 90, and 90 seconds. At the draft target of 2.1 to 2.3 spoken words per second, Quiet Signal leaves about 15 to 21 seconds without speech, The Work Between leaves about 8 to 15 seconds, and Clearer Week leaves about 11 to 18 seconds. Quiet Signal uses the most stillness. The Work Between uses the tightest rhythm.

All timecodes are draft limits. Final starts, cuts, captions, transitions, and holds must be rebuilt from measured narration at the chosen frame rate. Extend a scene if a fact cannot be read. Do not make the voice faster to protect an old timecode.
