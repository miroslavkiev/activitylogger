# ActivityLogger for macOS

An AI-ready interleaved activity logger for macOS. It records your active windows, keystrokes, mouse clicks, visible screen text, and clipboard history, formatting them into a daily Markdown file optimized for LLM analysis.

## Features
- **ActivityWatch Integration**: Tracks active application and window titles.
- **Keystroke & Hotkey Logging**: Captures typing and modifier combinations (e.g., `[CMD+C]`, `[ENTER]`).
- **Accessibility API (AX) Support**: Logs clicked elements and their roles.
- **Screen Text Extraction**: Periodically extracts visible text from the active window (with smart >10% change deduplication).
- **Clipboard Monitoring**: Logs clipboard changes securely.
- **Privacy First**: Automatically pauses logging when interacting with password managers or `SecureTextField` elements.

## Prerequisites
- macOS
- Python 3.9+
- [ActivityWatch](https://activitywatch.net/) running locally on port 5600.

## Installation & Setup

### 1. Install Dependencies
Install the required python packages:
```bash
pip3 install pynput requests pyobjc pyinstaller
```

### 2. Build the Native macOS App
Because macOS has strict security (TCC) for background input monitoring, the script must be compiled into a native `.app` bundle. Run this in the project directory (use the `pyinstaller` from your user Python bin):
```bash
cd /Users/mk/scripts/activitylogger
/Users/mk/Library/Python/3.9/bin/pyinstaller --onefile --windowed --name ActivityLoggerNative --noconfirm interleaved_logger.py
```
(`--noconfirm` skips the “remove output directory?” prompt on rebuilds.)
The compiled app will be generated at `dist/ActivityLoggerNative.app`.

### 3. Grant macOS Permissions
To allow the app to monitor your activity globally:
1. Open **System Settings** → **Privacy & Security**
2. Click the `+` button in **Input Monitoring** and add `dist/ActivityLoggerNative.app`.
3. Click the `+` button in **Accessibility** and add `dist/ActivityLoggerNative.app`.

### 4. Enable Autostart (survives reboot)
**Recommended: Launch Agent** — starts at login and restarts if the logger exits:
```bash
# Install the Launch Agent (one-time)
cp /Users/mk/scripts/activitylogger/com.mk.activitylogger.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.mk.activitylogger.plist
```
The agent uses `start_logger.sh` (Python script). Ensure **Python** (or **Terminal**) has **Input Monitoring** and **Accessibility** in System Settings → Privacy & Security if you run the script this way.

**Alternative: Login Items** — add `dist/ActivityLoggerNative.app` to **System Settings** → **General** → **Login Items** ("Open at Login"). Less reliable than a Launch Agent for a headless logger.

### 5. ActivityWatch: start at login (for window titles)
This logger gets **window and app titles** from [ActivityWatch](https://activitywatch.net/) (localhost:5600). To have ActivityWatch start after every reboot:

1. Install ActivityWatch if needed: download the [macOS .app from the releases page](https://github.com/ActivityWatch/activitywatch/releases) (or `brew install activitywatch`) and open it once.
2. **System Settings** → **General** → **Login Items** → **Open at Login**.
3. Click **+** and add **ActivityWatch** (the app you installed, e.g. from `/Applications/ActivityWatch.app`).
4. Optionally drag it above your Activity Logger in the list so it starts first and the API is ready when the logger runs.

After a reboot, ActivityWatch will start and the logger will show real window titles instead of the fallback “(ActivityWatch not running)”.

## Log Files
Logs are saved daily in the `logs/` directory formatted as `daily_log_YYYY-MM-DD.md`.

## Debugging (app not logging?)
1. **Check diagnostics** — After starting the app, open `~/scripts/activitylogger/logs/diagnostics.log` (or `/tmp/activitylogger_diagnostics.log` if the logs dir isn’t writable). You should see lines like `ActivityLogger starting`, `Log file created`, and `Keyboard and mouse listeners started`. If you see `FATAL:` then the traceback explains the crash.
2. **ActivityWatch** — Window titles only appear if [ActivityWatch](https://activitywatch.net/) is running on port 5600. If it’s not running, the logger still records keystrokes and mouse clicks under a fallback heading.
3. **Permissions** — Ensure **ActivityLoggerNative** (or **Python** if using the Launch Agent) has **Input Monitoring** and **Accessibility** in System Settings → Privacy & Security. Without these, no keyboard/mouse events are captured.
4. **Rebuild after code changes** — If you edited `interleaved_logger.py`, rebuild the `.app` with the pyinstaller command above, then start the new app.
