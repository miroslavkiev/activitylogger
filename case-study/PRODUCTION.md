# HyperFrames production plan

This plan starts only after one storyboard is selected. The current case study stops at the script and storyboard gate.

## Production boundary

- Use HyperFrames only for picture, motion, captions, audio placement, preview, and render.
- Build visuals from HTML and SVG with styling in CSS.
- Put all motion on one paused, finite, seek-safe GSAP timeline per composition.
- Do not use generated video, stock footage, screen recordings, camera footage, or another video editor.
- Import only the real ActivityLogger app icon from `assets/activitylogger-icon-source.png`.
- Rebuild any Review Center scene from the real controls and status text in `review_center.py`. If a scene uses an abstract day or evidence graphic, label it `Explanatory view` and keep it visually separate from the app window.
- Mark all task names, dates, patterns, and results as `Illustrative data`.
- Never open or copy real files from `logs/` or `private_analysis_review/` into the video project.

## Delivery recommendation

- Planning canvas: 1920x1080, 16:9
- Planning and master rate: 30 fps
- Final master after approval: native 3840x2160 at 30 fps, rendered from source
- Review proxy: 1920x1080 at 30 fps
- Color: BT.709
- Captions: open captions plus an SRT file
- Final still hold: 4 seconds, included inside the stated duration

Use 60 fps only if the chosen delivery channel needs it. If that changes, rebuild every cut and transition on the new frame grid before rendering.

## Shared visual rules

- Keep a 5 percent safe margin.
- Keep important content out of the bottom 17 percent caption area.
- Use one main subject per scene and at least two clear visual layers.
- Reveal each item when the voice names it. Do not load the full frame in the first quarter.
- Use smooth long-tail motion. No bounce-heavy entrances.
- Use no more than one ambient movement in a scene. Stillness is valid.
- Use no flash, glitch, random particles, endless loops, or decorative motion with no meaning.
- Do not use wall-clock time, `Math.random`, infinite repeat, CSS keyframe motion, or live network content.
- Use a clean cut for a deliberate change and a matched handoff only when one object truly continues.
- Use only supported transition names: `cut`, `crossfade`, `blur-crossfade`, `push-slide`, `zoom-through`, or `squeeze`.

## Accessibility

- Meet WCAG AA contrast for all useful text.
- Never use color as the only meaning. Add a word, icon, shape, or state label.
- Keep the film flash-free.
- Check every main statement at full speed with at least 3 seconds of readable time.
- Provide open captions and SRT captions from the same locked script.
- Make a reduced-motion version with the same facts, order, and duration. Replace camera travel with cuts or short fades.
- Keep caption line length short and avoid covering the Review Center controls.

## Audio and timing

1. Test two short voice samples before making the full narration.
2. Aim for a warm, clear, grounded voice at about 2.1 to 2.3 words per second.
3. Keep visible copy separate from speech-provider text.
4. Measure the final narration and word timings.
5. Recalculate scenes, cuts, captions, transitions, music, and final silence together.
6. Check pronunciation, tone, clipping, dropouts, loudness, peaks, music balance, and the final fade by ear.

Music should support movement, not create false drama. Use small interface sounds only for a real action, such as a pause, ready state, file creation, or saved result.

The proposal storyboards set `sfx: none` so draft prose cannot be treated as a sound-library lookup. After one option is selected and narration is measured, add only confirmed cue names at the real action times.

## Asset and rights register

| Asset | Source | Use | Rule |
|---|---|---|---|
| ActivityLogger icon | `assets/activitylogger-icon-source.png` | Product reveal and close | Keep its shape and colors. Do not stretch or filter it. |
| Review Center UI | Reconstructed from `review_center.py`, lines 270-329, 558-688, 1097-1129, and 1192-1229 | Product demo | Use real controls, statuses, and save actions with illustrative data only. No real local screenshot is needed. |
| Sora and Manrope for Option 3 | Official Google Fonts source, to be obtained after selection | Ciklum type roles | Store local font files and their license. Do not depend on a CDN at render time. |
| Fonts for Options 1 and 2 | Local licensed font files, to be chosen after selection | Display, body, and mono roles | Pin the exact files used by the chosen project. |
| Ciklum wordmark | No approved official logo asset is present; the handoff only has a CSS text treatment | None in this unbranded proposal | If Option 3 becomes a branded Ciklum film, an approved official wordmark is a required release gate. Do not use the CSS treatment as the official mark. |

## Build order

1. Select one option.
2. Write the confirmed `BRIEF.md` for that option.
3. Initialize one clean HyperFrames project and pin its version.
4. Copy the selected storyboard and script into that project.
5. Build static wireframe compositions with the real screen words.
6. Review a contact sheet and correct layout before motion.
7. Test two voice samples and lock one voice.
8. Generate and measure the final narration.
9. Add motion, one frame at a time, using the storyboard cues.
10. Inspect every frame midpoint and both sides of every cut.
11. Preview the full film and get render approval.
12. Render the native master and reduced-motion version from the same source.

## QA gate

Automated checks:

- HyperFrames lint and check pass
- Every composition is finite and seek-safe
- No text overflow, collisions, caption overlap, or unsafe contrast
- No black or empty frames
- Every transition matches the storyboard
- Resolution, rate, codec, and color metadata are correct
- Full video decode succeeds
- Caption order and timing match the script
- Audio loudness and peak are within the chosen delivery target
- Checksums exist for final files
- No real private content, credentials, browser state, or forbidden dash characters exist in tracked artifacts

Human checks:

- Watch all scene midpoints and cuts at full size
- Read every claim against `RESEARCH.md`
- Confirm all illustrative content is labeled
- Check the icon shape and color
- Listen for voice tone, pronunciation, music balance, silence, and dropouts
- Watch the final four-second hold without scrubbing

## Repository rule

Track source, scripts, storyboards, captions, licenses, and small QA records. Keep rendered videos, raw research, private source data, browser state, snapshots, caches, and old experiments out of normal Git history.
