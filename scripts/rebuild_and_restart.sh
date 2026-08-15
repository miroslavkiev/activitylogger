#!/bin/bash
# Canonical rebuild path: PyInstaller → certificate sign → kickstart Launch Agent.
# Keeps TCC Accessibility/Input Monitoring stable across rebuilds (cert leaf, not cdhash).
#
# Agents/humans: after changing interleaved_logger.py (or the .spec), run THIS script.
# Do not ship an ad-hoc-signed dist/ActivityLoggerNative.app.
set -euo pipefail

_HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/resolve_repo_root.sh
source "${_HERE}/lib/resolve_repo_root.sh"
# shellcheck source=lib/require_certificate_leaf.sh
source "${_HERE}/lib/require_certificate_leaf.sh"

resolve_repo_root "${_HERE}/.."
cd "$REPO"

APP="$REPO/dist/ActivityLoggerNative.app"
PYINSTALLER="${PYINSTALLER:-}"
if [[ -z "$PYINSTALLER" ]]; then
  if [[ -x "$REPO/.venv/bin/pyinstaller" ]]; then
    PYINSTALLER="$REPO/.venv/bin/pyinstaller"
  elif command -v pyinstaller >/dev/null 2>&1; then
    PYINSTALLER="$(command -v pyinstaller)"
  elif [[ -x "$HOME/Library/Python/3.9/bin/pyinstaller" ]]; then
    PYINSTALLER="$HOME/Library/Python/3.9/bin/pyinstaller"
  else
    echo "ERROR: pyinstaller not found. Activate .venv or install requirements.txt" >&2
    exit 1
  fi
fi

echo "==> Building with: $PYINSTALLER"
"$PYINSTALLER" ActivityLoggerNative.spec --noconfirm

echo "==> Signing with stable Code Signing identity"
"$REPO/scripts/sign_app.sh"

echo "==> Verifying designated requirement is certificate-anchored"
if ! DR="$(require_certificate_leaf "$APP")"; then
  echo "$DR"
  echo "ERROR: app is not certificate-signed (cdhash-only). TCC will break on next rebuild." >&2
  echo "Fix: ensure 'ActivityLogger Code Signing' exists (sign_app.sh creates it) and re-run." >&2
  echo "Run: ./scripts/rebuild_and_restart.sh" >&2
  exit 1
fi
echo "$DR"

echo "==> Restarting Launch Agent"
launchctl kickstart -k "gui/$(id -u)/com.mk.activitylogger"

echo "OK: rebuilt, certificate-signed, kickstarted."
echo "TCC re-grant is NOT needed when the same Code Signing cert is reused."
echo "Smoke-check: type something; daily_log_*.md should update within ~30s."
