#!/bin/bash
# Write ~/Library/LaunchAgents/com.mk.activitylogger.plist from the template.
# Does not read paths.log_dir — launchd logs always use $REPO/logs.

set -euo pipefail

_HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/resolve_repo_root.sh
source "${_HERE}/lib/resolve_repo_root.sh"
# shellcheck source=lib/ensure_log_dir.sh
source "${_HERE}/lib/ensure_log_dir.sh"
# shellcheck source=lib/require_certificate_leaf.sh
source "${_HERE}/lib/require_certificate_leaf.sh"

# Checkout that contains this script (source of the template).
SOURCE_REPO="$(cd "${_HERE}/.." && pwd)"
# Paths written into the plist (may be overridden for install / tests).
resolve_repo_root "$SOURCE_REPO"
TEMPLATE="${SOURCE_REPO}/com.mk.activitylogger.plist.template"
OUT="${ACTIVITYLOGGER_PLIST_OUT:-${HOME}/Library/LaunchAgents/com.mk.activitylogger.plist}"

if [[ ! -f "$TEMPLATE" ]]; then
  echo "FATAL: missing template: $TEMPLATE" >&2
  exit 1
fi

APP="${REPO}/dist/ActivityLoggerNative.app"
if [[ ! -d "$APP" ]]; then
  echo "FATAL: missing $APP — run: ./scripts/rebuild_and_restart.sh" >&2
  exit 1
fi
if ! DR="$(require_certificate_leaf "$APP")"; then
  echo "FATAL: $APP designated requirement lacks certificate leaf (ad-hoc/cdhash-only)." >&2
  echo "Run: ./scripts/rebuild_and_restart.sh" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT")"
ensure_log_dir "${REPO}/logs"

# Escape & and \ for sed replacement (BSD sed on macOS).
ESCAPED_REPO="${REPO//\\/\\\\}"
ESCAPED_REPO="${ESCAPED_REPO//&/\\&}"
sed "s|@REPO@|${ESCAPED_REPO}|g" "$TEMPLATE" > "$OUT"

if grep -q '@REPO@' "$OUT"; then
  echo "FATAL: @REPO@ placeholder remains in $OUT" >&2
  exit 1
fi

echo "Wrote $OUT (REPO=$REPO)"
echo "Next: launchctl bootout gui/\$(id -u)/com.mk.activitylogger 2>/dev/null || true"
echo "      launchctl bootstrap gui/\$(id -u) \"$OUT\""
echo "      launchctl enable gui/\$(id -u)/com.mk.activitylogger"
echo "      launchctl kickstart -k gui/\$(id -u)/com.mk.activitylogger"
