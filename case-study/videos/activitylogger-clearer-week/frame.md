---
version: 1
name: "Clearer Week - Ciklum-style video frame"
unit: "1920x1080 frame"
principle: "Evidence is clear, limits stay close, and the person keeps control"

colors:
  bg: "#F9FAFB"
  canvas: "#F9FAFB"
  card: "#FFFFFF"
  surface-soft: "#F4F7FF"
  tint: "#EDF2FF"
  primary: "#001FBA"
  ink-blue: "#1238D8"
  primary-500: "#284FF0"
  blue-mid: "#3C5EF5"
  teal: "#00CFAC"
  accent: "#00FFBD"
  positive: "#009E84"
  text: "#0F173D"
  text-muted: "#4E5D85"
  text-light: "#6F7CA1"
  border: "#D8E0F2"
  on-primary: "#FFFFFF"

typography:
  display: { fontFamily: "Sora", weight: 800, lineHeight: 1.05, tracking: "-0.035em" }
  section: { fontFamily: "Sora", weight: 700, lineHeight: 1.15, tracking: "-0.025em" }
  card-title: { fontFamily: "Sora", weight: 700, lineHeight: 1.2, tracking: "-0.02em" }
  body: { fontFamily: "Manrope", weight: 400, lineHeight: 1.6, color: "text" }
  label: { fontFamily: "Manrope", weight: 700, tracking: "0.1em", upper: true, color: "text-muted" }
  proof: { fontFamily: "Manrope", weight: 500, lineHeight: 1.4, color: "text-muted" }

spacing:
  safe-x: "96px"
  safe-y: "54px"
  grid-columns: 12
  grid-gutter: "24px"
  caption-band-top: "896px"
  card-padding: "60px"

radii:
  evidence-card: "16px"
  item: "10px"
  button: "8px"
  pill: "20px"

components:
  evidence-card:
    backgroundColor: "#FFFFFF"
    border: "2px solid #D8E0F2"
    rounded: "16px"
    shadow: "0 8px 24px rgba(0,31,186,0.07)"
  proof-pill:
    backgroundColor: "#EDF2FF"
    textColor: "#1238D8"
    rounded: "20px"
  soft-evidence:
    backgroundColor: "#F4F7FF"
    border: "2px solid #D8E0F2"
    rounded: "10px"
  chapter-field:
    backgroundColor: "#001FBA"
    textColor: "#FFFFFF"
---

# Clearer Week frame system

## Source design values

- Use the supplied palette exactly. Do not invent extra brand colors.
- Use local Sora for display text and local Manrope for body, labels, and captions.
- Keep open white space, large left-aligned statements, rounded evidence cards, blue chapter fields, and restrained teal accents.
- Use the source `1fr / 1.6fr` split only when a frame compares source and evidence.

## Film-specific values

- Use a 12-column grid with 96px side margins and 24px gutters.
- Keep useful content above y=896px for open captions.
- Use one main subject per frame and no dashboard wall.
- Use 96px focal text, 72px section text, 40px card titles, 30px body text, 20px labels, and 18px proof text as starting sizes.
- Use 2px borders and 60px card padding so the system remains visible in video.
- Use teal `#009E84` for the Frame 7 human-review path because it supports accessible meaning on the light canvas.
- Use the bright accent `#00FFBD` only as a non-text focal detail, including the final static period.

## Boundaries

- Do not show a Ciklum mark until an approved official asset is supplied.
- Do not imply that Ciklum owns, built, or endorses ActivityLogger.
- Do not use teal text on a white background.
- Do not use client data, private logs, scores, time claims, gradients as text fill, or decorative motion without meaning.
- Every reconstructed product screen must show `Illustrative data`.
