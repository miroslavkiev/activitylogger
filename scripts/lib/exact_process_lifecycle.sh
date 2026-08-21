#!/bin/bash
# Exact executable process lifecycle helpers for ActivityLogger launchd wrappers.

list_exact_executable_pids() {
  local executable="$1"
  local snapshot pid command
  snapshot="$(/bin/ps -axo pid=,command=)" || return 1
  while read -r pid command; do
    [[ "$pid" =~ ^[0-9]+$ ]] || continue
    [[ "$command" == "$executable" ]] || continue
    printf '%s\n' "$pid"
  done <<< "$snapshot"
}

pid_has_exact_executable() {
  local pid="$1"
  local executable="$2"
  local command snapshot candidate
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  if ! command="$(/bin/ps -p "$pid" -o command= 2>/dev/null)"; then
    # Distinguish a vanished/reused PID from an inability to inspect processes.
    # A successful exact-path snapshot can safely resolve the ambiguity.
    snapshot="$(list_exact_executable_pids "$executable")" || return 2
    while IFS= read -r candidate; do
      [[ "$candidate" == "$pid" ]] && return 0
    done <<< "$snapshot"
    return 1
  fi
  command="${command#"${command%%[![:space:]]*}"}"
  command="${command%"${command##*[![:space:]]}"}"
  [[ "$command" == "$executable" ]]
}

pid_in_list() {
  local needle="$1"
  shift
  local candidate
  for candidate in "$@"; do
    [[ "$candidate" == "$needle" ]] && return 0
  done
  return 1
}

validate_launch_agent_plist() {
  local plist="$1"
  local expected_label="$2"
  local expected_wrapper="$3"
  local owner mode label program wrapper keep_alive launch_at_load service_umask

  if [[ ! -f "$plist" || -L "$plist" ]]; then
    printf 'FATAL: Launch Agent plist must be a regular, non-symlink file: %s\n' "$plist" >&2
    return 1
  fi
  if ! read -r owner mode < <(/usr/bin/stat -f '%u %Lp' "$plist") \
    || [[ "$owner" != "$(/usr/bin/id -u)" ]] \
    || [[ ! "$mode" =~ ^[0-7]{3,4}$ ]] \
    || (( (8#$mode & 077) != 0 )); then
    printf 'FATAL: Launch Agent plist must be current-user owned and private: %s\n' "$plist" >&2
    return 1
  fi
  /usr/bin/plutil -lint "$plist" >/dev/null || return 1
  keep_alive="$(/usr/bin/plutil -extract KeepAlive raw -expect bool "$plist" 2>/dev/null)" \
    || return 1
  launch_at_load="$(/usr/bin/plutil -extract RunAtLoad raw -expect bool "$plist" 2>/dev/null)" \
    || return 1
  service_umask="$(/usr/bin/plutil -extract Umask raw -expect integer "$plist" 2>/dev/null)" \
    || return 1
  label="$(/usr/libexec/PlistBuddy -c 'Print :Label' "$plist" 2>/dev/null)" || return 1
  program="$(/usr/libexec/PlistBuddy -c 'Print :ProgramArguments:0' "$plist" 2>/dev/null)" || return 1
  wrapper="$(/usr/libexec/PlistBuddy -c 'Print :ProgramArguments:1' "$plist" 2>/dev/null)" || return 1
  if [[ "$label" != "$expected_label" || "$program" != "/bin/bash" \
    || "$wrapper" != "$expected_wrapper" || "$keep_alive" != "true" \
    || "$launch_at_load" != "true" || "$service_umask" != "63" ]]; then
    printf 'FATAL: Launch Agent plist does not match the canonical runtime policy: %s\n' "$plist" >&2
    return 1
  fi
}

exact_targets_are_gone() {
  local executable="$1"
  shift
  local pid
  for pid in "$@"; do
    if pid_has_exact_executable "$pid" "$executable"; then
      return 1
    elif [[ $? -eq 2 ]]; then
      return 2
    fi
  done
  return 0
}

terminate_exact_pids() {
  local executable="$1"
  shift
  local -a targets=("$@")
  local pid attempt

  [[ ${#targets[@]} -gt 0 ]] || return 0
  for pid in "${targets[@]}"; do
    if pid_has_exact_executable "$pid" "$executable"; then
      /bin/kill -TERM "$pid" 2>/dev/null || true
    elif [[ $? -eq 2 ]]; then
      return 1
    fi
  done
  for attempt in {1..5}; do
    exact_targets_are_gone "$executable" "${targets[@]}" && return 0
    /bin/sleep 1
  done

  for pid in "${targets[@]}"; do
    if pid_has_exact_executable "$pid" "$executable"; then
      /bin/kill -KILL "$pid" 2>/dev/null || true
    elif [[ $? -eq 2 ]]; then
      return 1
    fi
  done
  for attempt in {1..5}; do
    exact_targets_are_gone "$executable" "${targets[@]}" && return 0
    /bin/sleep 1
  done
  exact_targets_are_gone "$executable" "${targets[@]}"
}

remember_quiesced_pid() {
  local pid="$1"
  if [[ ${#QUIESCED_PIDS[@]} -gt 0 ]] \
    && pid_in_list "$pid" "${QUIESCED_PIDS[@]}"; then
    return 0
  fi
  QUIESCED_PIDS+=("$pid")
}

quiesce_exact_app_via_launch_agent() {
  local executable="$1"
  local launch_label="$2"
  local snapshot pid attempt
  local -a final_pids=()
  QUIESCED_PIDS=()
  QUIESCE_MUTATED=0

  if ! snapshot="$(list_exact_executable_pids "$executable")"; then
    printf '%s\n' 'FATAL: could not capture the existing ActivityLogger process set.' >&2
    return 1
  fi
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    remember_quiesced_pid "$pid"
  done <<< "$snapshot"

  if /bin/launchctl print "$launch_label" >/dev/null 2>&1; then
    if ! /bin/launchctl bootout "$launch_label" >/dev/null 2>&1 \
      && /bin/launchctl print "$launch_label" >/dev/null 2>&1; then
      printf '%s\n' 'FATAL: could not boot out the ActivityLogger Launch Agent.' >&2
      return 1
    fi
    QUIESCE_MUTATED=1
    for attempt in {1..10}; do
      if ! /bin/launchctl print "$launch_label" >/dev/null 2>&1; then
        break
      fi
      /bin/sleep 1
    done
    if /bin/launchctl print "$launch_label" >/dev/null 2>&1; then
      printf '%s\n' 'FATAL: ActivityLogger Launch Agent did not quiesce in time.' >&2
      return 1
    fi
  fi

  if ! snapshot="$(list_exact_executable_pids "$executable")"; then
    printf '%s\n' 'FATAL: could not capture the post-bootout ActivityLogger process set.' >&2
    return 1
  fi
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    remember_quiesced_pid "$pid"
  done <<< "$snapshot"
  if [[ ${#QUIESCED_PIDS[@]} -gt 0 ]]; then
    QUIESCE_MUTATED=1
    if ! terminate_exact_pids "$executable" "${QUIESCED_PIDS[@]}"; then
      printf '%s\n' 'FATAL: exact ActivityLogger processes survived quiesce TERM and KILL.' >&2
      return 1
    fi
  fi

  if ! snapshot="$(list_exact_executable_pids "$executable")"; then
    printf '%s\n' 'FATAL: could not prove the quiesced ActivityLogger process set.' >&2
    return 1
  fi
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    final_pids+=("$pid")
    remember_quiesced_pid "$pid"
  done <<< "$snapshot"
  if [[ ${#final_pids[@]} -gt 0 ]]; then
    QUIESCE_MUTATED=1
    if ! terminate_exact_pids "$executable" "${final_pids[@]}"; then
      printf '%s\n' 'FATAL: a late exact ActivityLogger process survived quiesce.' >&2
      return 1
    fi
  fi
  snapshot="$(list_exact_executable_pids "$executable")" || return 1
  [[ -z "$snapshot" ]]
}

bootstrap_and_verify_launch_agent() {
  local executable="$1"
  local launch_label="$2"
  local launch_domain="$3"
  local launch_plist="$4"
  shift 4
  local -a excluded_pids=("$@")
  local output snapshot attempt pid candidate stable_pid=""
  /bin/launchctl bootstrap "$launch_domain" "$launch_plist" || return 1
  for attempt in {1..60}; do
    candidate=""
    if output="$(/bin/launchctl print "$launch_label" 2>/dev/null)" \
      && /usr/bin/grep -Fq 'state = running' <<< "$output"; then
      snapshot="$(list_exact_executable_pids "$executable")" || return 1
      while IFS= read -r pid; do
        [[ -n "$pid" ]] || continue
        if [[ ${#excluded_pids[@]} -gt 0 ]] \
          && pid_in_list "$pid" "${excluded_pids[@]}"; then
          continue
        fi
        candidate="$pid"
        break
      done <<< "$snapshot"
      if [[ -n "$candidate" ]]; then
        stable_pid="$candidate"
        break
      fi
    fi
    /bin/sleep 1
  done
  [[ -n "$stable_pid" ]] || return 1

  # The discovery deadline is intentionally separate from this stability
  # deadline. Slow signature verification must not consume the second sample.
  for attempt in {1..10}; do
    /bin/sleep 1
    candidate=""
    if output="$(/bin/launchctl print "$launch_label" 2>/dev/null)" \
      && /usr/bin/grep -Fq 'state = running' <<< "$output"; then
      snapshot="$(list_exact_executable_pids "$executable")" || return 1
      while IFS= read -r pid; do
        [[ -n "$pid" ]] || continue
        if [[ ${#excluded_pids[@]} -gt 0 ]] \
          && pid_in_list "$pid" "${excluded_pids[@]}"; then
          continue
        fi
        if [[ "$pid" == "$stable_pid" ]]; then
          return 0
        fi
        [[ -n "$candidate" ]] || candidate="$pid"
      done <<< "$snapshot"
    fi
    if [[ -n "$candidate" ]]; then
      stable_pid="$candidate"
    else
      stable_pid=""
    fi
  done
  return 1
}

restart_exact_app_via_launch_agent() {
  local executable="$1"
  local launch_label="$2"
  local launch_domain="$3"
  local launch_plist="$4"
  local pid restart_ok=0
  local -a excluded_pids=()

  if ! quiesce_exact_app_via_launch_agent "$executable" "$launch_label"; then
    if [[ ${QUIESCE_MUTATED:-0} -eq 1 ]]; then
      /bin/launchctl bootstrap "$launch_domain" "$launch_plist" >/dev/null 2>&1 || true
    fi
    return 1
  fi
  if [[ ${#QUIESCED_PIDS[@]} -gt 0 ]]; then
    excluded_pids=("${QUIESCED_PIDS[@]}")
  fi
  if [[ ${#excluded_pids[@]} -gt 0 ]]; then
    bootstrap_and_verify_launch_agent \
      "$executable" "$launch_label" "$launch_domain" "$launch_plist" \
      "${excluded_pids[@]}" && restart_ok=1
  else
    bootstrap_and_verify_launch_agent \
      "$executable" "$launch_label" "$launch_domain" "$launch_plist" \
      && restart_ok=1
  fi
  if [[ $restart_ok -eq 1 ]]; then
    return 0
  fi

  printf '%s\n' \
    'FATAL: initial ActivityLogger restart failed; attempting unchanged-service recovery.' >&2
  if ! quiesce_exact_app_via_launch_agent "$executable" "$launch_label"; then
    printf '%s\n' 'FATAL: could not quiesce the failed ActivityLogger generation.' >&2
    return 1
  fi
  if [[ ${#QUIESCED_PIDS[@]} -gt 0 ]]; then
    for pid in "${QUIESCED_PIDS[@]}"; do
      if [[ ${#excluded_pids[@]} -eq 0 ]] \
        || ! pid_in_list "$pid" "${excluded_pids[@]}"; then
        excluded_pids+=("$pid")
      fi
    done
  fi
  restart_ok=0
  if [[ ${#excluded_pids[@]} -gt 0 ]]; then
    bootstrap_and_verify_launch_agent \
      "$executable" "$launch_label" "$launch_domain" "$launch_plist" \
      "${excluded_pids[@]}" && restart_ok=1
  else
    bootstrap_and_verify_launch_agent \
      "$executable" "$launch_label" "$launch_domain" "$launch_plist" \
      && restart_ok=1
  fi
  if [[ $restart_ok -eq 1 ]]; then
    printf '%s\n' \
      'ERROR: initial restart failed; unchanged ActivityLogger service was recovered.' >&2
  else
    printf '%s\n' 'FATAL: unchanged ActivityLogger service recovery failed.' >&2
  fi
  return 1
}
