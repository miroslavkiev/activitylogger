# Shared designated-requirement gate for ActivityLoggerNative.app.
#
# Usage (from a script that already sourced this file):
#   if ! DR="$(require_certificate_leaf "$APP")"; then
#     echo "FATAL: ... Run: ./scripts/rebuild_and_restart.sh" >&2
#     exit 1
#   fi
#
# Prints the codesign designated requirement to stdout.
# Returns 0 when DR contains "certificate leaf", else 1.

require_certificate_leaf() {
  local app="$1"
  local dr
  dr="$(codesign -d -r- "$app" 2>&1 || true)"
  printf '%s\n' "$dr"
  echo "$dr" | grep -q 'certificate leaf'
}
