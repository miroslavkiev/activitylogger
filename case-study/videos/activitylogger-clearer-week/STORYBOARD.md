---
format: 1920x1080
duration: 90s
message: "Evidence can suggest a useful change, but the person decides what it means"
arc: "Human question to ready review to local evidence to limits to a chosen next step"
audience: "privacy-minded people and Ciklum teams reviewing a practical local tool"
mode: collaborative
fps: 30
music: none
captions: open
status: approved
---

# STORYBOARD - Clearer Week

This video begins inside a real review choice. It follows evidence toward one human decision through the supplied Ciklum visual system.

## Story choice

- Result: agency
- Human action: the person chooses one next step after checking evidence and limits
- Hook: "What is worth changing?" appears inside the Review Center, not as a brand promise
- Culmination: one teal human-review path stops before the person opens the real outcome menu and records a choice
- Ending: patterns may emerge, but only a person can decide what they mean

## Ciklum source and boundary

- Source: the supplied Ciklum design handoff and its `DESIGN.md`.
- Palette: Canvas `#F9FAFB`, Primary 900 `#001FBA`, Primary 500 `#284FF0`, Teal `#00CFAC`, Accent 500 `#00FFBD`, Positive / delta-up `#009E84`, Text Primary `#0F173D`, Text Secondary `#4E5D85`, and border gray `#D8E0F2`.
- Type: Sora for display and Manrope for body and labels. Obtain and pin licensed local font files after this option is selected.
- Source layout: open white space, large left-aligned statements, rounded evidence cards, flexible component grids, a `1fr / 1.6fr` data-slide grid, blue fields, and restrained blue-to-teal accents.
- Added film rule: use a 12-column production grid for safe, repeatable video alignment. This grid is not a sourced Ciklum token.
- Source gap: the handoff has a CSS-only text wordmark treatment, but no approved official Ciklum logo asset, icon set, font files, token file, or motion rules. This storyboard is therefore an unbranded Ciklum-style proposal. If it becomes a branded Ciklum film, obtain the approved official wordmark before the build. Do not use the CSS text treatment as the official mark.
- Ownership: use the Ciklum visual system as requested, but do not imply that Ciklum built, owns, or endorses ActivityLogger.
- Reuse rule: borrow palette, type roles, spacing, and evidence hierarchy. Do not copy a finished slide, client copy, client data, or old Relay media.

## Video direction

- Look: bright, open, evidence-led, and human. Ciklum blue carries chapters, teal marks a possible signal, and white space keeps each message clear. Use ink or Ciklum Blue for text on white. Use teal as a shape, line, or background accent with an accessible text color.
- Layout: one main subject per frame. Use the added 12-column film grid to align statement, evidence, and action. Avoid a dashboard wall.
- Signature motion: one accessible teal `#009E84` human-review path appears only in Frame 7. It moves from reviewed evidence toward the person's cursor, then stops before the person acts in the Review Center.
- Camera: locked. Use clean section cuts, grid assembly, short masks, and one cursor action.
- Rhythm: human question, ready scope, observed trail, privacy limits, review boundary, evidence with limits, human choice, reflective close.
- Reveal rule: each card or line enters when the voice names it. Nothing useful appears before its cue.
- Motion grammar: use smooth long-tail `power3` settles, short mask reveals, discrete state swaps, and one seek-safe GSAP timeline per frame. Keep the camera locked.
- Stillness: Frames 4 and 8 hold. No decorative glow trail, full-film relay line, parallax, bounce, random motion, flash, or endless loop.
- Safety: 5 percent safe margin, bottom 17 percent clear for captions, AA contrast, no color-only state, and `Illustrative data` on every reconstructed screen.

## Frame 1 - What is worth changing?

- time: 00:00-00:09
- scene: A large sanitized Review Center fills the white field. A cursor pauses beside the review choice while one question appears.
- voiceover: "At the end of a busy week, the hardest question can be the simplest: what is worth changing?"
- script_line: CW-01
- duration: 9s
- transition_in: cut
- status: animated
- src: compositions/frames/01-worth-changing.html
- type: hook
- persuasion: A human question inside a useful action
- beat: curiosity
- blueprint: cursor-ui-demo (Adapt)
- asset_candidates: assets/ui-primitives.svg - local reusable UI symbols
- focal: the question above the Review Center
- roles: question = focal; Review Center = supporting; cursor = human cue; illustrative label = proof label
- on_screen: "What is worth changing?" / "Illustrative data"
- source_claims: C06, C10, C12
- sfx: none

narrativeRole: Put the person and the decision before product description.
keyMessage: A busy week needs a useful question, not a score.

Adapt: open inside one real product surface. Keep the white canvas mostly empty and do not show an answer yet.

Scene 1 (0.0-2.2s): the Review Center assembles across columns 2 to 8 with a short item cascade (`center-outward-expansion`). The cursor glides beside `Create review files` (`cursor-click-ripple`, move only) and stops without clicking.
Scene 2 (2.2-6.0s): the question reveals left to right in Sora across columns 7 to 12 (`dynamic-content-sequencing`) as the voice asks it.
Scene 3 (6.0-9.0s): all motion stops. The question and cursor hold with `Illustrative data` visible.

## Frame 2 - A ready window

- time: 00:09-00:20
- scene: The real Review Center controls and status text show a ready five-day window.
- voiceover: "Start with what was observed. Choose five consecutive completed calendar days. Each one must pass its checks before the review can begin."
- script_line: CW-02
- duration: 11s
- transition_in: push-slide LEFT 0.4s
- status: animated
- src: compositions/frames/02-ready-window.html
- type: feature_showcase
- persuasion: Confidence through exact scope
- beat: control
- blueprint: cursor-ui-demo (Adapt)
- asset_candidates: assets/ui-primitives.svg - local reusable UI symbols
- focal: the end-date field, 5 days menu, status text, and create button
- roles: exact Review Center controls = focal; scope statement = supporting; status and coverage text = proof labels; cursor = human cue
- on_screen: "5 consecutive completed calendar days" / "5 days" / "Create review files" / "Ready to create files for Day 1 through Day 5." / "File checks do not prove that every activity was captured."
- source_claims: C06, C07
- sfx: none

narrativeRole: Define the evidence window before showing what it contains.
keyMessage: Every required day must be ready.

Adapt: keep the real controls and status areas. Use Ciklum layout and color around the window without inventing a row of day cards.

Scene 1 (0.0-2.8s): a Ciklum Blue field fills the frame. `5 consecutive completed calendar days` reveals in white across the upper span (`dynamic-content-sequencing`).
Scene 2 (2.8-6.0s): a faithful Step 1 window settles across columns 2 to 11 (`spring-pop-entrance`, restrained). Its end-date field, real `5 days` menu, fixed `Create review files` button, and `Checking selected days...` arrive in a short ordered cascade.
Scene 3 (6.0-8.0s): the status swaps in place to `Ready to create files for Day 1 through Day 5.` (`discrete-text-sequence`) and the button becomes enabled without changing its label.
Scene 4 (8.0-11.0s): the coverage text `File checks do not prove that every activity was captured.` reveals below the controls (`dynamic-content-sequencing`) and holds. No older or substitute day enters.

## Frame 3 - The quiet local trail

- time: 00:20-00:32
- scene: A local daily Markdown page builds from four observed context rows beside the real ActivityLogger icon.
- voiceover: "Behind that moment is a quiet trail in daily Markdown, including app and window context, typing and hotkeys, clicks, and clipboard changes."
- script_line: CW-03
- duration: 12s
- transition_in: cut
- status: animated
- src: compositions/frames/03-quiet-trail.html
- type: product_intro
- persuasion: Concrete product role
- beat: clarity
- blueprint: grid-card-assemble (Adapt)
- asset_candidates: assets/activitylogger-icon-source.png - real ActivityLogger app icon
- focal: one daily Markdown page
- roles: daily page = focal; app icon = supporting; four observed rows = evidence; local label = proof label
- on_screen: "Examples shown" / "Observed context" / "Local daily Markdown"
- source_claims: C01, C02, C03
- sfx: none

narrativeRole: Explain what sits behind the review action.
keyMessage: Observed context becomes a readable daily trail on the Mac.

Adapt: use the Ciklum evidence-card hierarchy around one large document, but keep the original ActivityLogger icon unfiltered.

Scene 1 (0.0-2.5s): the real icon and white document card settle into an asymmetric 30/70 layout across columns 1 to 11 (`spring-pop-entrance`, restrained). The icon remains unfiltered.
Scene 2 (2.5-8.5s): example rows reveal in spoken order with a compact waterfall (`waterfall-entry`): app and window, typing and hotkeys, clicks, clipboard change. `Examples shown` remains visible.
Scene 3 (8.5-9.0s): `Local daily Markdown` arrives as a small blue proof pill under the page (`spring-pop-entrance`, restrained).
Scene 4 (9.0-12.0s): the page and proof label hold with no camera movement.

## Frame 4 - Clear limits

- time: 00:32-00:44
- scene: A dark-blue trust frame states sensitive plaintext and three capture exclusions, then shows secure and manual pause states.
- voiceover: "The files are sensitive plaintext. Configured secure apps, secure fields, and manual pause make capture step back. There are no screenshots, audio, or video."
- script_line: CW-04
- duration: 12s
- transition_in: cut
- status: animated
- src: compositions/frames/04-clear-limits.html
- type: feature_showcase
- persuasion: Trust through plain limits
- beat: reassurance
- blueprint: fixed-anchor-cycle (Adapt)
- asset_candidates: assets/ui-primitives.svg - local reusable UI symbols
- focal: `Sensitive plaintext` and the paused state
- roles: trust statement = focal; secure reason = supporting; pause control = supporting; exclusion labels = proof labels
- on_screen: "Sensitive plaintext" / "Configured secure app" / "Secure field" / "Manual pause" / "No screenshots, audio, or video"
- source_claims: C04, C05, C13
- sfx: none

narrativeRole: State the privacy limits before any review leaves the product.
keyMessage: Private does not mean encrypted, and capture knows when to step back.

Adapt: keep one fixed status panel. Replace its reason labels in spoken order and then stop all motion.

Scene 1 (0.0-2.8s): `Sensitive plaintext` reveals in white on Ciklum Blue with a simple file icon (`dynamic-content-sequencing`). It pins and does not move again.
Scene 2 (2.8-7.0s): `Configured secure app`, `Secure field`, and `Manual pause` replace one another in one fixed slot beside a fixed `Paused` status (`discrete-text-sequence`). The pause card stays still.
Scene 3 (7.0-9.8s): `No screenshots`, `No audio`, and `No video` enter as three readable proof labels in a full-width strip (`center-outward-expansion`, short-path variant).
Scene 4 (9.8-12.0s): the full trust frame holds. No glow, scan, or security shield animation runs.

## Frame 5 - Review, redact, choose

- time: 00:44-00:58
- scene: Three large Ciklum-style steps show ActivityLogger preparing files, the person reviewing them, and a separate trusted tool receiving only the chosen copy.
- voiceover: "ActivityLogger prepares the review files. You review and redact them. Then you choose a trusted tool to look for repeated work, friction, and possible errors."
- script_line: CW-05
- duration: 14s
- transition_in: cut
- status: animated
- src: compositions/frames/05-review-redact-choose.html
- type: process
- persuasion: Control through a clear handoff boundary
- beat: agency
- blueprint: grid-card-assemble (Adapt)
- asset_candidates: assets/ui-primitives.svg - local reusable UI symbols; assets/brands/chatgpt.svg, assets/brands/gemini.svg, assets/brands/claude-code.svg - tool brand marks used as equal examples
- focal: the person's review and redact step
- roles: prepare = supporting; review and redact = focal; chosen tool = supporting; boundary labels = proof
- on_screen: "1. ActivityLogger prepares" / "2. You review and redact" / "3. You choose a trusted tool" / "Examples" / "ChatGPT" / "Gemini" / "Claude Code" / "Selected by you"
- source_claims: C06, C08, C09, C10
- sfx: none

narrativeRole: Make the product boundary and the person's control easy to understand.
keyMessage: ActivityLogger prepares files; the person controls review and sharing.

Adapt: place three steps on the added 12-column film grid. Do not connect them with the film's signal path yet.

Scene 1 (0.0-3.5s): Step 1 enters across columns 1 to 4 with a local file icon and `Prepares files` (`center-outward-expansion`, short-path variant).
Scene 2 (3.5-7.5s): Step 2 settles into the central columns as the largest card (`spring-pop-entrance`, restrained). `Review and redact` uses ink text, and its teal underline draws once (`svg-path-draw`).
Scene 3 (7.5-11.5s): Step 3 enters across columns 9 to 12, labeled `You choose a trusted tool`. ChatGPT, Gemini, and Claude Code appear with equal weight under `Examples` and `Selected by you` (`center-outward-expansion`, short-path variant).
Scene 4 (11.5-14.0s): all three steps hold. There is no automatic upload arrow or automatic insight.

## Frame 6 - Evidence, with limits

- time: 00:58-01:10
- scene: A possible pattern and its three source contexts appear beside an explicit limits panel.
- voiceover: "A careful review can link each possible pattern to its day and context. Work spans are not exact time records. Gaps stay unknown."
- script_line: CW-06
- duration: 12s
- transition_in: cut
- status: animated
- src: compositions/frames/06-evidence-with-limits.html
- type: benefit_highlight
- persuasion: Credibility through source and limit proximity
- beat: recognition
- blueprint: compose
- asset_candidates: assets/ui-primitives.svg - local reusable UI symbols
- focal: one possible pattern with its limits
- roles: possible pattern = focal; three source contexts = proof; limits panel = proof; illustrative label = proof label
- on_screen: "Possible pattern" / "Not exact time" / "Unknown gaps stay unknown" / "Day and context linked" / "Illustrative data"
- source_claims: C10, C12
- sfx: none

narrativeRole: Present value and uncertainty in the same frame.
keyMessage: Evidence can support a check without becoming a time claim.

Compose with the `dynamic-content-sequencing`, `anchored-layout-expand`, and `scale-swap-transition` rules. Use one strong finding card and one limits card. Do not turn evidence into a score, graph, or certainty badge.

Scene 1 (0.0-3.2s): `Illustrative data` appears first and remains visible. `Possible pattern` then settles in a large white card on a pale canvas (`spring-pop-entrance`, restrained).
Scene 2 (3.2-5.0s): three source chips labeled Day 1, Day 3, and Day 5 reveal under the pattern with short context labels (`dynamic-content-sequencing`).
Scene 3 (5.0-8.8s): the blue limits card expands into the right 40 percent (`anchored-layout-expand`). `Not exact time` and then `Unknown gaps stay unknown` reveal in spoken order (`discrete-text-sequence`).
Scene 4 (8.8-12.0s): `Day and context linked` holds with `Illustrative data`. No signal line has appeared yet.

## Frame 7 - The signal stops with you

- time: 01:10-01:22
- scene: One teal path marks the person's review from a separate trusted-tool result to the real Review Center outcome menu, then stops before the person acts.
- voiceover: "Your chosen review tool can suggest. It cannot decide. You may try one small idea, record a result in ActivityLogger, or choose no action."
- script_line: CW-07
- duration: 12s
- transition_in: cut
- status: animated
- src: compositions/frames/07-signal-stops.html
- type: culmination
- persuasion: Human agency at the visual peak
- beat: decision
- blueprint: compose
- asset_candidates: assets/ui-primitives.svg - local reusable UI symbols
- focal: the selected human outcome
- roles: trusted-tool result = supporting; human-review path = short meaning cue; outcome popup and save button = focal; cursor = human action cue
- on_screen: "Trusted review tool chosen by you" / "Human review" / "Choose a result" / "Found an idea to try" / "Tried a change" / "No action" / "Save review result" / "Review result saved locally." / "You decide"
- source_claims: C08, C11
- sfx: none

narrativeRole: Deliver the film's only signature motion and return control to the person.
keyMessage: A chosen review tool can suggest, but the person decides and records the result.

Adapt: draw one path inside this scene only and label it `Human review`. It is a meaning cue, not an automatic data transfer.

Scene 1 (0.0-3.0s): a result card labeled `Trusted review tool chosen by you` settles at left while Step 3 of the Review Center appears at right (`spring-pop-entrance`, restrained). The menu is closed and `Save review result` is visible. `You decide` reveals above the control.
Scene 2 (3.0-5.2s): a single accessible teal `#009E84` SVG path labeled `Human review` draws toward the cursor (`svg-path-draw`). It stops before reaching the Review Center control. This is the motion peak.
Scene 3 (5.2-8.2s): the cursor moves to the anchored menu (`cursor-click-ripple`), opens it (`anchored-layout-expand`), holds all three choices, and selects `Found an idea to try`. The menu also shows `Tried a change` and `No action`.
Scene 4 (8.2-12.0s): the cursor presses `Save review result` once (`press-release-spring`) and `Review result saved locally.` swaps into place (`discrete-text-sequence`). `You decide` remains the main subject. No task, upload, automation, or automatic return path starts.

## Frame 8 - What it means

- time: 01:22-01:30
- scene: The real app icon and final line sit on open white space with a short static teal period.
- voiceover: "Patterns may emerge. You decide what they mean."
- script_line: CW-08
- duration: 8s
- transition_in: crossfade 0.4s
- status: animated
- src: compositions/frames/08-what-it-means.html
- type: branding
- persuasion: Reflective resolution
- beat: calm
- blueprint: titlecard-reveal (Adapt)
- asset_candidates: assets/activitylogger-icon-source.png - real ActivityLogger app icon
- focal: the final line
- roles: final line = focal; app icon = supporting; teal period = static accent
- on_screen: "You decide what they mean."
- source_claims: C01, C08, C12
- sfx: none

narrativeRole: End with the person's judgment, not a brand claim.
keyMessage: The tool supports meaning; it does not assign it.

Adapt: use the open Ciklum statement layout without a Ciklum wordmark. Keep the teal period static.

Scene 1 (0.0-1.5s): the ActivityLogger icon and first phrase settle at left and across columns 3 to 10 (`scale-swap-transition`, restrained). The icon remains unfiltered and above the caption band.
Scene 2 (1.5-4.0s): `You decide what they mean.` reveals once from left to right (`dynamic-content-sequencing`). A single teal period appears on the final word and remains still.
Scene 3 (4.0-8.0s): four-second still hold. No logo animation or end hit.

## Storyboard check

- Eight beats move from a human question to a human choice
- The exact Ciklum palette and type roles, plus its open-space and evidence hierarchy, are used only in this option
- No missing Ciklum logo, icon, font, token, or motion asset is invented
- Five consecutive completed calendar days are named with exact scope
- Sensitive plaintext and capture exclusions are stated before the review handoff
- ActivityLogger never appears to analyze, upload, decide, or act
- The teal human-review path appears once, for 2.2 seconds, and stops before the person acts
- No real private data, client claim, or copied Relay layout appears
