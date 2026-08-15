#!/bin/bash
# Launch ActivityLoggerNative.app via Launch Services (open -W).
# Do not switch this back to python3 — see docs/MACOS_TCC.md.

set -euo pipefail

# Prefer ACTIVITYLOGGER_REPO; else resolve from this script's directory.
if [[ -n "${ACTIVITYLOGGER_REPO:-}" ]]; then
  REPO="$ACTIVITYLOGGER_REPO"
else
  REPO="$(cd "$(dirname "$0")" && pwd)"
fi

LOG_DIR="${REPO}/logs"

mkdir -p "$LOG_DIR"
chmod 700 "$LOG_DIR" 2>/dev/null || true

if [[ ! -d "${REPO}/dist/ActivityLoggerNative.app" ]]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] FATAL: missing ${REPO}/dist/ActivityLoggerNative.app — run: pyinstaller ActivityLoggerNative.spec --noconfirm" >> "$LOG_DIR/wrapper.log"
  exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] start_logger.sh opening ${REPO}/dist/ActivityLoggerNative.app (Launch Services)" >> "$LOG_DIR/wrapper.log"

# -W: wait until the app exits so launchd KeepAlive tracks the real process
# Do NOT exec the inner MacOS binary directly — TCC attribution breaks.
exec /usr/bin/open -W "${REPO}/dist/ActivityLoggerNative.app"
