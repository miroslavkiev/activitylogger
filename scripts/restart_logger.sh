#!/bin/bash
# Restart the installed app after a config-only change without rebuilding it.
set -euo pipefail
umask 077

_HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/resolve_repo_root.sh
source "${_HERE}/lib/resolve_repo_root.sh"
# shellcheck source=lib/require_certificate_leaf.sh
source "${_HERE}/lib/require_certificate_leaf.sh"
# shellcheck source=lib/exact_process_lifecycle.sh
source "${_HERE}/lib/exact_process_lifecycle.sh"

resolve_repo_root "${_HERE}/.."
APP="$REPO/dist/ActivityLoggerNative.app"
APP_EXECUTABLE="$APP/Contents/MacOS/ActivityLoggerNative"
LAUNCH_DOMAIN="gui/$(/usr/bin/id -u)"
LAUNCH_LABEL="$LAUNCH_DOMAIN/com.mk.activitylogger"
LAUNCH_PLIST="${ACTIVITYLOGGER_LAUNCH_PLIST:-${HOME}/Library/LaunchAgents/com.mk.activitylogger.plist}"

[[ $# -eq 0 ]] || {
  printf 'Usage: %s\n' "$0" >&2
  exit 2
}
verify_activitylogger_app "$APP"
validate_launch_agent_plist \
  "$LAUNCH_PLIST" "com.mk.activitylogger" "$REPO/start_logger.sh"
if ! restart_exact_app_via_launch_agent \
  "$APP_EXECUTABLE" "$LAUNCH_LABEL" "$LAUNCH_DOMAIN" "$LAUNCH_PLIST"; then
  printf '%s\n' 'FATAL: ActivityLogger did not reach a stable fresh process state.' >&2
  exit 1
fi
printf '%s\n' 'OK: ActivityLogger restarted with a fresh verified process.'
