#!/bin/bash
# Render and install the Launch Agent without text substitution.
set -euo pipefail
umask 077

_HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/resolve_repo_root.sh
source "${_HERE}/lib/resolve_repo_root.sh"
# shellcheck source=lib/ensure_log_dir.sh
source "${_HERE}/lib/ensure_log_dir.sh"
# shellcheck source=lib/require_certificate_leaf.sh
source "${_HERE}/lib/require_certificate_leaf.sh"

SOURCE_REPO="$(cd "${_HERE}/.." && pwd)"
resolve_repo_root "$SOURCE_REPO"
TEMPLATE="${SOURCE_REPO}/com.mk.activitylogger.plist.template"
OUT="${ACTIVITYLOGGER_PLIST_OUT:-${HOME}/Library/LaunchAgents/com.mk.activitylogger.plist}"
APP="${REPO}/dist/ActivityLoggerNative.app"

[[ -f "$TEMPLATE" ]] || { echo "FATAL: missing template: $TEMPLATE" >&2; exit 1; }
verify_activitylogger_app "$APP"
ensure_log_dir "${REPO}/logs"
/usr/bin/python3 "${SOURCE_REPO}/scripts/render_launch_agent.py" "$TEMPLATE" "$OUT" "$REPO"
/usr/bin/plutil -lint "$OUT" >/dev/null

echo "Wrote $OUT with mode 0600 (REPO=$REPO)"
echo "Next: ${SOURCE_REPO}/scripts/restart_logger.sh"
