# ActivityLogger for macOS

Records active windows, keystrokes, clicks, screen text, and clipboard into daily Markdown for LLM analysis.

**Version:** 4.1.0 · **Runtime:** `dist/ActivityLoggerNative.app` · **Docs:** [`docs/MACOS_TCC.md`](docs/MACOS_TCC.md) · [`AGENTS.md`](AGENTS.md)

## Features
- ActivityWatch window titles (frontmost-app fallback)
- Keystrokes / hotkeys, AX clicks, periodic screen text, clipboard (plaintext when not paused)
- Privacy pause for password managers / AX secure fields; clipboard during pause is not logged later

## Setup (short)

```bash
cd ~/scripts/activitylogger
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./scripts/rebuild_and_restart.sh   # build + certificate-sign + kickstart
```

1. Grant **`dist/ActivityLoggerNative.app`** → Accessibility **and** Input Monitoring (**once**)
2. Install agent if needed:

```bash
cp com.mk.activitylogger.plist ~/Library/LaunchAgents/
launchctl bootout gui/$(id -u)/com.mk.activitylogger 2>/dev/null || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.mk.activitylogger.plist
launchctl kickstart -k gui/$(id -u)/com.mk.activitylogger
```

Do not also add the same app as a Login Item. Put ActivityWatch in Login Items if you want titles after reboot.

## After editing code

```bash
./scripts/rebuild_and_restart.sh
```

Uses a self-signed Code Signing cert so TCC survives rebuilds (no cdhash churn). Confirm typing updates `logs/daily_log_*.md`.

## Logs
- `logs/daily_log_YYYY-MM-DD.md` (dir mode `700`)
- `python3 clean_markdown_log.py logs/daily_log_YYYY-MM-DD.md` before LLM paste
- Prompt: `prompts/gemini-automation-analysis.md`

## Tests
`pytest -q`
