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
Because macOS has strict security (TCC) for background input monitoring, the script must be compiled into a native `.app` bundle. Run this in the project directory:
```bash
pyinstaller --onefile --windowed --name ActivityLoggerNative interleaved_logger.py
```
The compiled app will be generated at `dist/ActivityLoggerNative.app`.

### 3. Grant macOS Permissions
To allow the app to monitor your activity globally:
1. Open **System Settings** → **Privacy & Security**
2. Click the `+` button in **Input Monitoring** and add `dist/ActivityLoggerNative.app`.
3. Click the `+` button in **Accessibility** and add `dist/ActivityLoggerNative.app`.

### 4. Enable Autostart
To make the logger run silently in the background every time you turn on your Mac:
1. Open **System Settings** → **General** → **Login Items**.
2. Add `dist/ActivityLoggerNative.app` to the "Open at Login" list.

## Log Files
Logs are saved daily in the `logs/` directory formatted as `daily_log_YYYY-MM-DD.md`.
