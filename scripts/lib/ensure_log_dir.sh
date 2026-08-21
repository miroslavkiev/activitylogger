# Create a private owned directory without changing an existing shared path.

ensure_log_dir() {
  local dir="$1"
  local parent owner mode created=0

  if [[ -L "$dir" ]]; then
    printf 'FATAL: private directory must not be a symlink: %s\n' "$dir" >&2
    return 1
  fi
  if [[ ! -e "$dir" ]]; then
    parent="$(dirname "$dir")"
    /bin/mkdir -m 700 -p "$parent"
    if /bin/mkdir -m 700 "$dir" 2>/dev/null; then
      created=1
    elif [[ -L "$dir" || ! -e "$dir" ]]; then
      printf 'FATAL: could not safely create private directory: %s\n' "$dir" >&2
      return 1
    fi
  fi
  if [[ -L "$dir" || ! -d "$dir" ]]; then
    printf 'FATAL: private directory path is not a real directory: %s\n' "$dir" >&2
    return 1
  fi

  owner="$(/usr/bin/stat -f '%u' "$dir")"
  if [[ "$owner" != "$(/usr/bin/id -u)" ]]; then
    printf 'FATAL: private directory is not owned by the current user: %s\n' "$dir" >&2
    return 1
  fi
  mode="$(/usr/bin/stat -f '%Lp' "$dir")"
  if [[ $created -eq 1 ]]; then
    /bin/chmod 700 "$dir"
  elif [[ "$mode" != "700" ]]; then
    printf 'FATAL: refusing to chmod existing non-private directory %s (mode %s).\n' \
      "$dir" "$mode" >&2
    return 1
  fi
}
