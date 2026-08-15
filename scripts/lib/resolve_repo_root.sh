# Resolve the ActivityLogger checkout root into REPO.
#
# Usage:
#   # From a repo-root script (e.g. start_logger.sh):
#   _HERE="$(cd "$(dirname "$0")" && pwd)"
#   # shellcheck source=scripts/lib/resolve_repo_root.sh
#   source "${_HERE}/scripts/lib/resolve_repo_root.sh"
#   resolve_repo_root "${_HERE}"
#
#   # From a script under scripts/ (e.g. rebuild_and_restart.sh):
#   _HERE="$(cd "$(dirname "$0")" && pwd)"
#   # shellcheck source=lib/resolve_repo_root.sh
#   source "${_HERE}/lib/resolve_repo_root.sh"
#   resolve_repo_root "${_HERE}/.."
#
# Prefer ACTIVITYLOGGER_REPO when set (non-empty).
# Otherwise set REPO to the absolute path of the first argument
# (pass the expected checkout directory, usually via dirname of "$0").

resolve_repo_root() {
  if [[ -n "${ACTIVITYLOGGER_REPO:-}" ]]; then
    REPO="$ACTIVITYLOGGER_REPO"
  else
    REPO="$(cd "${1:?resolve_repo_root: pass repo path or set ACTIVITYLOGGER_REPO}" && pwd)"
  fi
}
