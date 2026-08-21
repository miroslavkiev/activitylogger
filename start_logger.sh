#!/bin/bash
# Launch ActivityLoggerNative.app through Launch Services with open -W.
set -euo pipefail
umask 077

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
if ! VERIFIED="$(verify_activitylogger_app "$APP" 2>&1)"; then
  printf '[%s] %s\n' "$(TS)" "$VERIFIED" >> "$LOG_DIR/wrapper.log"
  chmod 600 "$LOG_DIR/wrapper.log"
  exit 1
fi

printf '[%s] opening %s wrapper_pid=%s (%s)\n' \
  "$(TS)" "$APP" "$$" "$VERIFIED" >> "$LOG_DIR/wrapper.log"
chmod 600 "$LOG_DIR/wrapper.log"

# Keep the launchd wrapper alive while Launch Services waits for the app.
# Running the inner executable directly breaks TCC attribution.
if /usr/bin/open -W "$APP"; then
  OPEN_STATUS=0
else
  OPEN_STATUS=$?
fi
printf '[%s] open -W exited wrapper_pid=%s status=%s\n' \
  "$(TS)" "$$" "$OPEN_STATUS" >> "$LOG_DIR/wrapper.log"
chmod 600 "$LOG_DIR/wrapper.log"
exit "$OPEN_STATUS"
