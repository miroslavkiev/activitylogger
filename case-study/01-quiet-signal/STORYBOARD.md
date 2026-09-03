---
format: 1920x1080
duration: 84s
message: "Observed work can become enough context to remember what matters"
arc: "Question to fragments to readable day to recognition to reflection"
audience: "privacy-minded people doing complex work on one Mac"
mode: collaborative
fps: 30
music: "restrained tactile electronic score with warm low pulse"
captions: open
status: proposal
---

# STORYBOARD - Quiet Signal

This video tells a privacy-minded Mac user that ActivityLogger can turn observed work into enough context to remember a day and check a possible pattern.

## Story choice

- Result: recognition
- Human action: the person reviews and redacts the files, then chooses one possible pattern to check in a trusted review tool
- Hook: "What do you remember from Tuesday?"
- Culmination: fragments from the week resolve into one readable pattern with source context
- Ending: remembering is useful because it supports a choice, not because it measures time

## Video direction

- Look: dark, sparse, and product-object-led. Deep graphite `#0B1119`, non-text steel `#273646`, accessible secondary text `#A4B4C0`, soft white `#EEF4F7`, cyan `#2DE2D3`, and amber `#FFB000`. These are concept colors sampled by eye from the real app icon, not a formal product brand system.
- Type: large neutral sans display, restrained sans body, and a small mono role for time and scope labels. Do not use Sora, Manrope, or the Ciklum grid.
- Layout: one main subject fills at least 40 percent of the useful canvas. Product screens sit alone on dark fields. No dashboard wall.
- Signature motion: one brief cyan trace connects reviewed fragments at the recognition peak. It turns amber only after the person selects the pattern to check.
- Camera: one large decelerating zoom-out in Frame 3. Other frames use locked cameras, short focus moves, or clean cuts.
- Rhythm: question, fast fragments, held reveal, clear trust beat, guided review, fastest recognition peak, quiet close.
- Reveal rule: each item appears when its spoken cue arrives. No frame loads all content in its first quarter.
- Stillness: Frames 4 and 7 hold. No breathing cards, drifting camera, random particles, bounce, flash, or endless motion.
- Safety: 5 percent safe margin, bottom 17 percent clear for captions, AA contrast, no color-only state, and `Illustrative data` on every reconstructed screen.

## Frame 1 - Tuesday

- time: 00:00-00:08
- scene: A single question types onto a nearly black field, then the word Tuesday holds alone.
- voiceover: "What do you remember from Tuesday? The decisions, the detours, the small things you had to do twice?"
- script_line: QS-01
- duration: 8s
- transition_in: cut
- status: outline
- src: compositions/frames/01-tuesday.html
- type: hook
- persuasion: Curiosity through a familiar memory gap
- beat: curiosity
- blueprint: typewriter-reveal (Adapt)
- asset_direction: authored HTML and SVG only
- focal: the word Tuesday
- roles: question = supporting; Tuesday = focal; caret = foreground cue
- on_screen: "What do you remember from Tuesday?"
- source_claims: C01, C12
- sfx: none

narrativeRole: Ask a human question before naming the product.
keyMessage: Useful work can become hard to recall.

Adapt: keep the human typing signature. Remove the usual brand pop and let the unanswered day remain.

Scene 1 (0.0-2.2s): the first half of the question types on with a caret in the upper third. The field is almost empty and the camera is locked.
Scene 2 (2.2-5.0s): the rest of the question types in two short cues. The word `Tuesday` gains the only cyan highlight.
Scene 3 (5.0-8.0s): all words except `Tuesday` fade to accessible secondary text `#A4B4C0`. Hold the complete question still for 3 seconds.

## Frame 2 - The context fades

- time: 00:08-00:20
- scene: Three useful work fragments appear, change state, and leave before they can form a whole.
- voiceover: "Most work does not disappear. Its context does. One window becomes another, one thought becomes a message, and the shape of the day fades."
- script_line: QS-02
- duration: 12s
- transition_in: cut
- status: outline
- src: compositions/frames/02-context-fades.html
- type: pain_point
- persuasion: Recognition without blame
- beat: tension
- blueprint: kinetic-type-beats (Adapt)
- asset_direction: authored HTML and SVG only
- focal: three changing work fragments
- roles: Weekly update = focal; Review comment = supporting; Project note = supporting; Illustrative data label = proof label
- on_screen: "window" / "thought" / "message" / "context"
- source_claims: C02, C03, C12
- sfx: none

narrativeRole: Show why recall fails even when useful work happened.
keyMessage: The missing thing is context, not effort.

Adapt: keep the phrase-by-phrase rhythm. Replace full-screen type with large sanitized app fragments and no moving trace.

Scene 1 (0.0-3.2s): a large `Weekly update` document plane enters from the left as the first sentence lands. `Illustrative data` stays visible.
Scene 2 (3.2-6.4s): it hard-cuts to a browser note, then a mail reply, each filling a different part of the frame as the voice names the change.
Scene 3 (6.4-9.6s): the three planes overlap for one beat, but their labels no longer line up. The word `context` arrives last at upper right.
Scene 4 (9.6-12.0s): the planes dim and leave only three small time marks. Hold the marks without camera movement.

## Frame 3 - A readable trail

- time: 00:20-00:32
- scene: A macro detail from the real app icon pulls back into a local daily Markdown trail.
- voiceover: "ActivityLogger keeps a private, human-readable journal of observed work on your Mac, including app and window context, typing and hotkeys, clicks, and clipboard changes."
- script_line: QS-03
- duration: 12s
- transition_in: zoom-through
- status: outline
- src: compositions/frames/03-readable-trail.html
- type: product_intro
- persuasion: Concrete product role
- beat: clarity
- blueprint: zoom-out-workspace-reveal (Adapt)
- asset_candidates: assets/activitylogger-icon-source.png - real ActivityLogger app icon
- focal: assets/activitylogger-icon-source.png
- roles: app icon = focal; daily Markdown rows = supporting; local file label = proof label
- on_screen: "Observed context. Local daily Markdown. Examples shown."
- source_claims: C01, C02, C03
- sfx: none

narrativeRole: Name the product only after the value is clear.
keyMessage: Observed context becomes a readable local record.

Adapt: keep one continuous pull-back. Start inside the cyan icon node, reveal the whole icon, then reveal the daily record around it.

Scene 1 (0.0-2.5s): an extreme close view of the icon's cyan node sits at center. It sharpens as `ActivityLogger` is spoken.
Scene 2 (2.5-7.2s): one smooth decelerating zoom-out reveals the full icon at left and a local Markdown page at right. No second zoom.
Scene 3 (7.2-9.0s): four example rows reveal in spoken order: app and window, typing and hotkeys, clicks, clipboard change. Each uses text plus a simple shape.
Scene 4 (9.0-12.0s): `Local daily Markdown` and `Examples shown` lock below the page. The frame holds still.

## Frame 4 - It knows when to step back

- time: 00:32-00:44
- scene: The journal stops at a secure field, then shows manual pause and the three capture exclusions.
- voiceover: "It captures no screenshots, audio, or video. Configured secure apps, secure fields, and a manual pause tell it when to step back."
- script_line: QS-04
- duration: 12s
- transition_in: blur-crossfade 0.4s
- status: outline
- src: compositions/frames/04-step-back.html
- type: feature_showcase
- persuasion: Trust through clear limits
- beat: reassurance
- blueprint: fixed-anchor-cycle (Adapt)
- asset_direction: authored HTML and SVG only
- focal: a fixed local journal panel
- roles: journal = focal; secure field = supporting; pause control = supporting; exclusion labels = proof labels
- on_screen: "No screenshots" / "No audio" / "No video" / "Paused"
- source_claims: C04, C05, C13
- sfx: none

narrativeRole: Earn trust without stopping the story for a feature list.
keyMessage: Clear limits and pause states are part of the product value.

Adapt: the journal stays fixed while the reason beside it changes. No signal travels between states.

Scene 1 (0.0-3.4s): the journal holds at left. `Sensitive plaintext` is visible from the first frame. `No screenshots`, `No audio`, and `No video` appear by 2.0 seconds and remain visible.
Scene 2 (3.4-7.7s): configured secure-app and secure-field labels appear in sequence. The journal state changes from `Active` to `Paused`, with both word and icon changing.
Scene 3 (7.7-9.0s): a large manual pause control presses once. The same `Paused` state remains.
Scene 4 (9.0-12.0s): all motion stops on `Capture steps back`. The plaintext note remains readable.

## Frame 5 - Five completed days

- time: 00:44-00:58
- scene: A faithful sanitized Review Center uses its real end-date field, period menu, status text, and create button.
- voiceover: "When five consecutive completed calendar days pass their integrity checks, ActivityLogger prepares private review files. It does not upload or analyze them."
- script_line: QS-05
- duration: 14s
- transition_in: push-slide LEFT 0.4s
- status: outline
- src: compositions/frames/05-five-days.html
- type: feature_showcase
- persuasion: Show the real review flow and its boundary
- beat: control
- blueprint: cursor-ui-demo (Adapt)
- asset_direction: authored HTML and SVG only
- focal: the real `Create review files` controls and status
- roles: Review Center = focal; end date and 5 days controls = supporting; status and limit text = proof labels; cursor = human action cue
- on_screen: "Weekly Activity Review" / "5 days" / "Create review files" / "Ready to create files for Day 1 through Day 5." / "ActivityLogger creates the files. It does not analyze or send them."
- source_claims: C06, C07, C08, C09
- sfx: none

narrativeRole: Move from daily memory to a review the person controls.
keyMessage: The exact review window must be ready, and ActivityLogger only prepares the files.

Adapt: use the cursor to complete one real three-step surface, but stop after file creation. Do not show capture resuming.

Scene 1 (0.0-3.8s): the Review Center enters as one large native window. It shows an end-date field with `Illustrative Day 5`, the real `5 days` menu, and the fixed `Create review files` button.
Scene 2 (3.8-7.8s): the real status changes from `Checking selected days...` to the sanitized `Ready to create files for Day 1 through Day 5.` The button label does not change. The coverage note says file checks do not prove every activity was captured.
Scene 3 (7.8-10.8s): the enabled `Create review files` button is pressed. The status becomes `Review files are ready for Day 1 through Day 5.` No captured text appears.
Scene 4 (10.8-14.0s): the line `It does not analyze or send them` reveals and holds for more than 3 seconds.

## Frame 6 - Tuesday has a shape

- time: 00:58-01:16
- scene: A separate trusted review tool links three reviewed fragments back to their source context and offers one possible pattern to check.
- voiceover: "You review and redact the files, then choose a trusted tool. Possible patterns can surface: a repeated task or changed focus. Not exact time. Clues worth checking."
- script_line: QS-06
- duration: 18s
- transition_in: crossfade 0.4s
- status: outline
- src: compositions/frames/06-tuesday-shape.html
- type: benefit_highlight
- persuasion: Evidence before interpretation
- beat: recognition
- blueprint: transcript-scroll-artifact-reveal (Adapt)
- asset_direction: authored HTML and SVG only
- focal: one possible pattern with three source links
- roles: reviewed summary = focal; trusted tool = supporting; cyan trace = short signature motion; amber selection = human choice; limits = proof labels
- on_screen: "Reviewed and redacted by you" / "Trusted review tool chosen by you" / "Possible pattern" / "Not exact time" / "Illustrative data"
- source_claims: C08, C09, C10, C12
- sfx: none

narrativeRole: Deliver recognition as the emotional and visual peak.
keyMessage: A possible pattern is useful because its source and limits remain visible.

Adapt: keep the document traversal and artifact reveal. The artifact is a possible pattern in a separate tool, not a result made by ActivityLogger.

Scene 1 (0.0-4.5s): `Reviewed and redacted by you` appears before a sanitized workload summary moves through three source contexts. The frame label says `Illustrative data`.
Scene 2 (4.5-8.8s): a separate panel labeled `Trusted review tool chosen by you` arrives. `Repeated task` and `Changed focus` appear only as the voice names them.
Scene 3 (8.8-12.8s): the only cyan trace in the film draws from the three source fragments to one `Possible pattern` card over 2.2 seconds.
Scene 4 (12.8-14.5s): the person selects the `Possible pattern` card itself. An outline and check icon mark selection, and the trace segment turns amber. This is the fastest motion peak.
Scene 5 (14.5-18.0s): `Not exact time` and `Clues worth checking` settle below. Camera and trace stop.

## Frame 7 - Remember enough

- time: 01:16-01:24
- scene: The real icon and one final thought hold in silence.
- voiceover: "Remember enough to choose what matters next."
- script_line: QS-07
- duration: 8s
- transition_in: blur-crossfade 0.5s
- status: outline
- src: compositions/frames/07-remember-enough.html
- type: branding
- persuasion: Reflective resolution
- beat: calm
- blueprint: titlecard-reveal (Reproduce)
- asset_candidates: assets/activitylogger-icon-source.png - real ActivityLogger app icon
- focal: assets/activitylogger-icon-source.png
- roles: app icon = focal; final line = supporting
- on_screen: "Remember enough to choose."
- source_claims: C01, C12
- sfx: none

narrativeRole: Return to the opening question with a calm answer.
keyMessage: The value is human recall and choice, not minute-by-minute measurement.

Scene 1 (0.0-1.0s): the icon fades in at center-left with one smooth settle. The final line appears at center-right.
Scene 2 (1.0-4.0s): the voice lands the final thought. Nothing else enters.
Scene 3 (4.0-8.0s): four-second still hold. Music reaches one warm note and fades naturally.

## Storyboard check

- Seven beats, not a repeated feature tour
- Value appears in the first two frames
- Recognition, not the cyan trace, is the climax
- Five consecutive completed calendar days are named with exact scope
- Analysis is shown in a separate trusted tool
- Work spans are not shown as exact time
- No real private data or real local date appears
- Final four-second hold is inside the 84-second total
