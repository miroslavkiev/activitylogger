#!/bin/bash
# Canonical staged build, certificate signing, promotion, and restart path.
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
cd "$REPO"

PYTHON="$REPO/.venv/bin/python"
PYINSTALLER="$REPO/.venv/bin/pyinstaller"
APP="$REPO/dist/ActivityLoggerNative.app"
APP_EXECUTABLE="$APP/Contents/MacOS/ActivityLoggerNative"
STAGE="$(mktemp -d "$REPO/.build-stage.XXXXXX")"
STAGED_APP="$STAGE/dist/ActivityLoggerNative.app"
BACKUP="$REPO/dist/.ActivityLoggerNative.app.previous.$$"
LAUNCH_DOMAIN="gui/$(/usr/bin/id -u)"
LAUNCH_LABEL="$LAUNCH_DOMAIN/com.mk.activitylogger"
LAUNCH_PLIST="${ACTIVITYLOGGER_LAUNCH_PLIST:-${HOME}/Library/LaunchAgents/com.mk.activitylogger.plist}"
PROMOTED=0
HAD_APP=0
QUIESCE_STARTED=0
PRE_RESTART_PIDS=()

remember_pre_restart_pid() {
  local pid="$1"
  if [[ ${#PRE_RESTART_PIDS[@]} -gt 0 ]] \
    && pid_in_list "$pid" "${PRE_RESTART_PIDS[@]}"; then
    return 0
  fi
  PRE_RESTART_PIDS+=("$pid")
}

restore_previous_app() {
  [[ $PROMOTED -eq 1 ]] || return 0
  /bin/rm -rf "$APP"
  if [[ $HAD_APP -eq 1 ]]; then
    [[ -d "$BACKUP" ]] || return 1
    /bin/mv "$BACKUP" "$APP"
  fi
  PROMOTED=0
}

rollback_and_restart_previous() {
  local pid

  if ! quiesce_exact_app_via_launch_agent "$APP_EXECUTABLE" "$LAUNCH_LABEL"; then
    echo "FATAL: could not quiesce ActivityLogger for recovery." >&2
    return 1
  fi
  if [[ ${#QUIESCED_PIDS[@]} -gt 0 ]]; then
    for pid in "${QUIESCED_PIDS[@]}"; do
      remember_pre_restart_pid "$pid"
    done
  fi

  if ! restore_previous_app; then
    echo "FATAL: could not restore the previous app bundle." >&2
    return 1
  fi
  if [[ $HAD_APP -ne 1 ]]; then
    echo "FATAL: no previous app was available to restart." >&2
    return 1
  fi
  if ! verify_activitylogger_rollback_app "$APP"; then
    echo "FATAL: restored previous app failed identity or integrity verification." >&2
    return 1
  fi

  echo "Bootstrapping restored previous app"
  if [[ ${#PRE_RESTART_PIDS[@]} -gt 0 ]]; then
    bootstrap_and_verify_launch_agent \
      "$APP_EXECUTABLE" "$LAUNCH_LABEL" "$LAUNCH_DOMAIN" "$LAUNCH_PLIST" \
      "${PRE_RESTART_PIDS[@]}" || return 1
  else
    bootstrap_and_verify_launch_agent \
      "$APP_EXECUTABLE" "$LAUNCH_LABEL" "$LAUNCH_DOMAIN" "$LAUNCH_PLIST" \
      || return 1
  fi
  QUIESCE_STARTED=0
  echo "Previous app restored with a fresh verified process after failed promotion." >&2
}

cleanup() {
  status=$?
  trap - EXIT
  if [[ $status -ne 0 ]]; then
    if [[ $QUIESCE_STARTED -eq 1 \
      && ( $PROMOTED -eq 1 || ${QUIESCE_MUTATED:-0} -eq 1 ) ]]; then
      rollback_and_restart_previous || \
        echo "FATAL: automatic recovery did not reach a fresh previous process." >&2
    elif [[ $PROMOTED -eq 1 ]]; then
      if restore_previous_app; then
        if [[ $HAD_APP -eq 1 ]] && ! verify_activitylogger_rollback_app "$APP"; then
          echo "FATAL: restored previous app failed identity or integrity verification." >&2
        fi
      else
        echo "FATAL: could not restore the previous app bundle." >&2
      fi
    fi
  fi
  /bin/rm -rf "$STAGE"
  if [[ $status -eq 0 && -d "$BACKUP" ]]; then
    /bin/rm -rf "$BACKUP"
  fi
  exit "$status"
}
trap cleanup EXIT

if [[ ! -x "$PYTHON" || ! -x "$PYINSTALLER" ]]; then
  echo "FATAL: canonical .venv is missing. Create it with the .python-version interpreter and install requirements.txt." >&2
  exit 1
fi
EXPECTED_PYTHON="$(<"$REPO/.python-version")"
ACTUAL_PYTHON="$("$PYTHON" -c 'import platform; print(platform.python_version())')"
if [[ "$ACTUAL_PYTHON" != "$EXPECTED_PYTHON" ]]; then
  echo "FATAL: .venv Python is $ACTUAL_PYTHON, expected $EXPECTED_PYTHON from .python-version." >&2
  exit 1
fi

echo "Building staged app with $PYINSTALLER"
PYINSTALLER_CONFIG_DIR="$STAGE/pyinstaller" "$PYINSTALLER" \
  ActivityLoggerNative.spec --noconfirm --clean \
  --distpath "$STAGE/dist" --workpath "$STAGE/build"

echo "Signing and verifying staged app"
ACTIVITYLOGGER_APP="$STAGED_APP" "$REPO/scripts/sign_app.sh"
verify_activitylogger_app "$STAGED_APP"

if [[ -d "$APP" ]]; then
  HAD_APP=1
  echo "Prevalidating existing app for exact rollback"
  verify_activitylogger_rollback_app "$APP"
fi

if [[ "${ACTIVITYLOGGER_SKIP_RESTART:-0}" != "1" ]]; then
  validate_launch_agent_plist \
    "$LAUNCH_PLIST" "com.mk.activitylogger" "$REPO/start_logger.sh"
  QUIESCE_STARTED=1
  quiesce_exact_app_via_launch_agent "$APP_EXECUTABLE" "$LAUNCH_LABEL"
  if [[ ${#QUIESCED_PIDS[@]} -gt 0 ]]; then
    for pid in "${QUIESCED_PIDS[@]}"; do
      remember_pre_restart_pid "$pid"
    done
  fi
fi

mkdir -p "$REPO/dist"
if [[ -d "$APP" ]]; then
  mv "$APP" "$BACKUP"
fi
if ! mv "$STAGED_APP" "$APP"; then
  [[ ! -d "$BACKUP" ]] || mv "$BACKUP" "$APP"
  exit 1
fi
PROMOTED=1
verify_activitylogger_app "$APP"

if [[ "${ACTIVITYLOGGER_SKIP_RESTART:-0}" != "1" ]]; then
  echo "Bootstrapping Launch Agent"
  restart_ok=0
  if [[ ${#PRE_RESTART_PIDS[@]} -gt 0 ]]; then
    bootstrap_and_verify_launch_agent \
      "$APP_EXECUTABLE" "$LAUNCH_LABEL" "$LAUNCH_DOMAIN" "$LAUNCH_PLIST" \
      "${PRE_RESTART_PIDS[@]}" && restart_ok=1
  else
    bootstrap_and_verify_launch_agent \
      "$APP_EXECUTABLE" "$LAUNCH_LABEL" "$LAUNCH_DOMAIN" "$LAUNCH_PLIST" \
      && restart_ok=1
  fi
  if [[ $restart_ok -ne 1 ]]; then
    echo "FATAL: promoted app did not reach a stable fresh process state; rolling back." >&2
    exit 1
  fi
  QUIESCE_STARTED=0
fi

echo "OK: staged build signed, verified, promoted, and ready."
echo "TCC re-grant is not needed because the pinned identity is unchanged."
echo "Smoke-check: type something; daily_log_*.md should update within about 30 seconds."
