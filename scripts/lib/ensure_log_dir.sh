# Create a log directory with mode 0700.
#
# Usage:
#   ensure_log_dir "$LOG_DIR"
#
# mkdir -p always runs. chmod 700 failure is ignored (same as prior scripts).

ensure_log_dir() {
  local dir="$1"
  mkdir -p "$dir"
  chmod 700 "$dir" 2>/dev/null || true
}
