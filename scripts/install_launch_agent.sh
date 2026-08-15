#!/bin/bash
# Write ~/Library/LaunchAgents/com.mk.activitylogger.plist from the template.
# Does not read paths.log_dir — launchd logs always use $REPO/logs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Checkout that contains this script (source of the template).
SOURCE_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
# Paths written into the plist (may be overridden for install / tests).
REPO="${ACTIVITYLOGGER_REPO:-$SOURCE_REPO}"
TEMPLATE="${SOURCE_REPO}/com.mk.activitylogger.plist.template"
OUT="${ACTIVITYLOGGER_PLIST_OUT:-${HOME}/Library/LaunchAgents/com.mk.activitylogger.plist}"

if [[ ! -f "$TEMPLATE" ]]; then
  echo "FATAL: missing template: $TEMPLATE" >&2
  exit 1
fi

mkdir -p "$(dirname "$OUT")"
mkdir -p "${REPO}/logs" 2>/dev/null || true
chmod 700 "${REPO}/logs" 2>/dev/null || true

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
