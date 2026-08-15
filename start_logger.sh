#!/bin/bash
# Launch ActivityLoggerNative.app via Launch Services (open -W).
# Do not switch this back to python3 — see docs/MACOS_TCC.md.

set -euo pipefail

_HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/lib/resolve_repo_root.sh
source "${_HERE}/scripts/lib/resolve_repo_root.sh"
# shellcheck source=scripts/lib/ensure_log_dir.sh
source "${_HERE}/scripts/lib/ensure_log_dir.sh"
# shellcheck source=scripts/lib/require_certificate_leaf.sh
source "${_HERE}/scripts/lib/require_certificate_leaf.sh"

resolve_repo_root "${_HERE}"

LOG_DIR="${REPO}/logs"
APP="${REPO}/dist/ActivityLoggerNative.app"
TS() { date '+%Y-%m-%d %H:%M:%S'; }

ensure_log_dir "$LOG_DIR"

if [[ ! -d "$APP" ]]; then
  echo "[$(TS)] FATAL: missing $APP — run: ./scripts/rebuild_and_restart.sh" >> "$LOG_DIR/wrapper.log"
  exit 1
fi

if ! DR="$(require_certificate_leaf "$APP")"; then
  echo "[$(TS)] FATAL: $APP designated requirement lacks certificate leaf (ad-hoc/cdhash-only). Run: ./scripts/rebuild_and_restart.sh" >> "$LOG_DIR/wrapper.log"
  exit 1
fi

echo "[$(TS)] start_logger.sh opening $APP (Launch Services)" >> "$LOG_DIR/wrapper.log"

# -W: wait until the app exits so launchd KeepAlive tracks the real process
# Do NOT exec the inner MacOS binary directly — TCC attribution breaks.
exec /usr/bin/open -W "$APP"
