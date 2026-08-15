# ActivityLogger for macOS

Records active windows, keystrokes, clicks, screen text, and clipboard into daily Markdown for LLM analysis.

**Version:** 4.1.0 · **Runtime:** `dist/ActivityLoggerNative.app` · **Docs:** [`docs/MACOS_TCC.md`](docs/MACOS_TCC.md) · [`AGENTS.md`](AGENTS.md)

## Features
- Native window titles (NSWorkspace + Accessibility); optional ActivityWatch enricher
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
./scripts/install_launch_agent.sh
launchctl bootout gui/$(id -u)/com.mk.activitylogger 2>/dev/null || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.mk.activitylogger.plist
launchctl enable gui/$(id -u)/com.mk.activitylogger
launchctl kickstart -k gui/$(id -u)/com.mk.activitylogger
```

Do not also add the same app as a Login Item. ActivityWatch is optional (fills empty titles only when `window_titles.activitywatch_enricher` is true).

## Config (optional)

Capture tunables live outside the signed app.
Repo-root [`config.example.toml`](config.example.toml) is the human schema copy of code defaults.

```bash
mkdir -p ~/.config/activitylogger
cp config.example.toml ~/.config/activitylogger/config.toml
chmod 700 ~/.config/activitylogger
chmod 600 ~/.config/activitylogger/config.toml
```

Edit feature flags in that file (for example `features.browser_url_capture`).

- **Config-only edit:** restart the agent (no rebuild):

```bash
launchctl kickstart -k gui/$(id -u)/com.mk.activitylogger
```

- **Logger source change:** rebuild and restart:

```bash
./scripts/rebuild_and_restart.sh
```

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
