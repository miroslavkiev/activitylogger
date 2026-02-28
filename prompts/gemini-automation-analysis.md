# Gemini Pro prompt: Weekly activity analysis & automation ideas

Copy the prompt below into Gemini (Pro). Either paste the past week’s log content directly after the prompt, or attach the `daily_log_YYYY-MM-DD.md` files for the last 7 days.

---

## Prompt

You are analyzing my **work activity logs** from the past week to suggest automations that save time, improve quality, or add other value.

**Data format:** I’m providing daily Markdown logs. Each day has:
- A title: `# Work Log — YYYY-MM-DD`
- Sections with:
  - `## App — Window title` (active app and window)
  - `*HH:MM:SS*` (time)
  - Events: keystrokes, hotkeys like `[CMD+C]`, `[ENTER]`, `[TAB]`, typed text, clipboard snippets, mouse clicks (with element roles when available), and sometimes visible screen text. Sections are separated by `---`.

**What to do:**

1. **Summarize patterns**
   - Which apps and types of work dominate (e.g. email, code, docs, browser, chat).
   - Recurring tasks (e.g. “every day you do X in app Y”).
   - Obvious time sinks or friction (repetitive copy-paste, manual lookups, repeated sequences).
   - Context-switching patterns (how often you change app/task and for what).

2. **Propose automations**
   For each idea, give:
   - **What:** Short name of the automation.
   - **Trigger/context:** When it should run (e.g. “when I open X”, “every morning”, “when I paste a link from Y”).
   - **Action:** What it does (e.g. “prefill template”, “run script”, “remind to Z”).
   - **Value:** Why it helps (save time / reduce errors / improve quality / reduce cognitive load / other).
   - **How (optional):** Possible tools (Shortcuts, Alfred, Keyboard Maestro, cron, script, Zapier, etc.) if obvious.

   Prioritize:
   - High-frequency, repetitive actions.
   - Things that clearly waste time or cause errors.
   - Small automations that are easy to implement and have quick payoff.

3. **Output format**
   - Start with a 1–2 paragraph “Week in review” summary.
   - Then a **Patterns** section (bullets).
   - Then **Suggested automations** as a numbered list, each with What / Trigger / Action / Value / How.
   - End with **Top 3** automations to try first and why.

**Constraints:** Assume I’m on macOS. Don’t suggest automations that require sharing these logs or sensitive content with third-party AI/APIs unless I explicitly ask. Prefer local or well-known tools (Shortcuts, Alfred, scripts, etc.).

---

**Instructions for me:** Paste or attach my `daily_log_YYYY-MM-DD.md` files for the last 7 days below (or in the next message).
