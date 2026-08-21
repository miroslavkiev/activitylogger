#!/bin/bash
# Shared signature verifier for ActivityLoggerNative.app.
#
# The expected SHA-1 leaf fingerprint is stored locally because the signing
# identity is intentionally not committed. Every caller uses this verifier so
# a valid signature from the wrong identity is rejected too.

verify_entitlement_allowlist() {
  local app="$1"
  local entitlements dump key_count forbidden
  local -a forbidden_entitlements=(
    "com.apple.security.cs.allow-dyld-environment-variables"
    "com.apple.security.cs.allow-jit"
    "com.apple.security.cs.allow-unsigned-executable-memory"
    "com.apple.security.cs.debugger"
    "com.apple.security.cs.disable-library-validation"
    "com.apple.security.get-task-allow"
  )

  if ! entitlements="$(/usr/bin/codesign -d --entitlements :- "$app" 2>/dev/null)" \
    || [[ -z "$entitlements" ]]; then
    echo "FATAL: cannot export signed app entitlements." >&2
    return 1
  fi
  if ! dump="$(printf '%s\n' "$entitlements" | /usr/bin/plutil -p - 2>/dev/null)"; then
    echo "FATAL: signed app entitlements are not a valid property list." >&2
    return 1
  fi
  for forbidden in "${forbidden_entitlements[@]}"; do
    if /usr/bin/grep -Fq "\"$forbidden\"" <<< "$dump"; then
      printf 'FATAL: forbidden code-signing entitlement is present: %s\n' "$forbidden" >&2
      return 1
    fi
  done
  if ! /usr/bin/grep -Eq \
    '^[[:space:]]*"com\.apple\.security\.automation\.apple-events"[[:space:]]*=>[[:space:]]*true[[:space:]]*$' \
      <<< "$dump"; then
    echo "FATAL: signed app is missing the exact required entitlement values." >&2
    return 1
  fi
  key_count="$(
    /usr/bin/grep -Ec '^[[:space:]]*"[^"]+"[[:space:]]*=>' <<< "$dump" || true
  )"
  if [[ "$key_count" != "1" ]]; then
    echo "FATAL: signed app entitlement allowlist must contain exactly one key." >&2
    return 1
  fi
}

normalize_absolute_path_lexically() {
  local path="$1"
  local component result="" index
  local -a components=() normalized=()
  [[ "$path" == /* ]] || return 1
  IFS='/' read -r -a components <<< "$path"
  for component in "${components[@]}"; do
    case "$component" in
      ""|.) ;;
      ..)
        if [[ ${#normalized[@]} -gt 0 ]]; then
          index=$((${#normalized[@]} - 1))
          unset "normalized[$index]"
        fi
        ;;
      *) normalized+=("$component") ;;
    esac
  done
  if [[ ${#normalized[@]} -eq 0 ]]; then
    printf '/\n'
    return 0
  fi
  for component in "${normalized[@]}"; do
    result="$result/$component"
  done
  printf '%s\n' "$result"
}

normalized_path_is_allowed() {
  local path="$1"
  local app_real="$2"
  local normalized
  if ! normalized="$(/bin/realpath -q "$path" 2>/dev/null)"; then
    normalized="$(normalize_absolute_path_lexically "$path")" || return 1
  fi
  case "$normalized" in
    "$app_real"|"$app_real"/*|/System/Library|/System/Library/*|/usr/lib|/usr/lib/*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

expand_macho_reference() {
  local reference="$1"
  local candidate="$2"
  local main_executable="$3"
  local base
  case "$reference" in
    /*)
      printf '%s\n' "$reference"
      ;;
    @loader_path)
      /bin/realpath "$(/usr/bin/dirname "$candidate")"
      ;;
    @loader_path/*)
      base="$(/bin/realpath "$(/usr/bin/dirname "$candidate")")" || return 1
      printf '%s/%s\n' "$base" "${reference#@loader_path/}"
      ;;
    @executable_path)
      /bin/realpath "$(/usr/bin/dirname "$main_executable")"
      ;;
    @executable_path/*)
      base="$(/bin/realpath "$(/usr/bin/dirname "$main_executable")")" || return 1
      printf '%s/%s\n' "$base" "${reference#@executable_path/}"
      ;;
    *)
      return 1
      ;;
  esac
}

verify_bundle_reference() {
  local reference="$1"
  local candidate="$2"
  local app_real="$3"
  local main_executable="$4"
  local expanded
  expanded="$(expand_macho_reference "$reference" "$candidate" "$main_executable")" \
    || return 1
  normalized_path_is_allowed "$expanded" "$app_real"
}

verify_macho_load_paths() {
  local candidate="$1"
  local app_real="$2"
  local main_executable="$3"
  local dependencies load_commands install_name dependency rpath expanded suffix
  local resolved_count rpath_count=0
  local -a allowed_rpaths=()

  dependencies="$(/usr/bin/otool -L "$candidate")" || {
    printf 'FATAL: cannot inspect Mach-O dependencies: %s\n' "$candidate" >&2
    return 1
  }
  load_commands="$(/usr/bin/otool -l "$candidate")" || {
    printf 'FATAL: cannot inspect Mach-O load commands: %s\n' "$candidate" >&2
    return 1
  }
  install_name="$(
    /usr/bin/otool -D "$candidate" 2>/dev/null \
      | /usr/bin/sed -nE '2 s/^[[:space:]]*(.*)[[:space:]]*$/\1/p'
  )" || install_name=""

  while IFS= read -r rpath; do
    [[ -n "$rpath" ]] || continue
    rpath_count=$((rpath_count + 1))
    if ! verify_bundle_reference "$rpath" "$candidate" "$app_real" "$main_executable"; then
      printf 'FATAL: Mach-O has a non-system, non-bundle LC_RPATH %s: %s\n' \
        "$rpath" "$candidate" >&2
      return 1
    fi
    allowed_rpaths+=("$rpath")
  done < <(
    printf '%s\n' "$load_commands" \
      | /usr/bin/awk '
          $1 == "cmd" && $2 == "LC_RPATH" { in_rpath = 1; next }
          in_rpath && $1 == "path" {
            sub(/^[[:space:]]*path[[:space:]]+/, "")
            sub(/[[:space:]]+\(offset[[:space:]]+[0-9]+\)$/, "")
            print
            in_rpath = 0
          }
        '
  )

  while IFS= read -r dependency; do
    [[ -n "$dependency" ]] || continue
    if [[ -n "$install_name" && "$dependency" == "$install_name" ]]; then
      continue
    fi
    if [[ "$dependency" == @rpath/* ]]; then
      if [[ $rpath_count -eq 0 ]]; then
        printf 'FATAL: Mach-O uses @rpath without an allowed LC_RPATH: %s\n' "$candidate" >&2
        return 1
      fi
      suffix="${dependency#@rpath/}"
      if [[ -z "$suffix" || "/$suffix/" == *"//"* \
        || "/$suffix/" == *"/../"* || "/$suffix/" == *"/./"* ]]; then
        printf 'FATAL: @rpath dependency contains prohibited traversal components or empty components %s: %s\n' \
          "$dependency" "$candidate" >&2
        return 1
      fi
      resolved_count=0
      for rpath in "${allowed_rpaths[@]}"; do
        expanded="$(expand_macho_reference "$rpath" "$candidate" "$main_executable")" \
          || return 1
        if ! normalized_path_is_allowed "$expanded/$suffix" "$app_real"; then
          printf 'FATAL: @rpath dependency has an unsafe resolved target %s: %s\n' \
            "$dependency" "$candidate" >&2
          return 1
        fi
        resolved_count=$((resolved_count + 1))
      done
      if [[ $resolved_count -ne $rpath_count ]]; then
        printf 'FATAL: @rpath dependency has no allowed resolved target %s: %s\n' \
          "$dependency" "$candidate" >&2
        return 1
      fi
      continue
    fi
    if ! verify_bundle_reference "$dependency" "$candidate" "$app_real" "$main_executable"; then
      printf 'FATAL: Mach-O has a non-system, non-bundle dependency %s: %s\n' \
        "$dependency" "$candidate" >&2
      return 1
    fi
  done < <(
    printf '%s\n' "$dependencies" \
      | /usr/bin/sed -nE '2,$ s/^[[:space:]]*(.*)[[:space:]]+\(compatibility version .*$/\1/p'
  )
}

verify_nested_macho_signature() {
  local candidate="$1"
  local expected="$2"
  local output requirement

  if ! output="$(
    /usr/bin/codesign --verify --strict --verbose=4 \
      -R="certificate leaf = H\"$expected\"" "$candidate" 2>&1
  )"; then
    printf '%s\n' "$output" >&2
    printf 'FATAL: nested Mach-O strict signature verification failed: %s\n' "$candidate" >&2
    return 1
  fi
  if ! requirement="$(/usr/bin/codesign -d -r- "$candidate" 2>&1)" \
    || ! /usr/bin/grep -Fq "certificate leaf = H\"$expected\"" <<< "$requirement"; then
    printf '%s\n' "$requirement" >&2
    printf 'FATAL: nested Mach-O does not use the pinned certificate leaf: %s\n' "$candidate" >&2
    return 1
  fi
}

verify_bundle_contents() {
  local app="$1"
  local expected="$2"
  local app_real main_executable candidate description resolved temporary

  app_real="$(/bin/realpath "$app")" || {
    echo "FATAL: cannot resolve app bundle path: $app" >&2
    return 1
  }
  main_executable="$app/Contents/MacOS/ActivityLoggerNative"
  if [[ ! -f "$main_executable" || -L "$main_executable" ]]; then
    echo "FATAL: main executable is missing, non-regular, or a symlink." >&2
    return 1
  fi
  temporary="$(mktemp -d "${TMPDIR:-/tmp}/activitylogger-verify-scan.XXXXXX")" || {
    echo "FATAL: cannot create a private verification workspace." >&2
    return 1
  }
  if ! /usr/bin/find "$app/Contents" -type l -print0 > "$temporary/symlinks" \
    || ! /usr/bin/find "$app/Contents" -type f -print0 > "$temporary/files"; then
    /bin/rm -rf -- "$temporary"
    echo "FATAL: cannot enumerate app bundle contents." >&2
    return 1
  fi

  while IFS= read -r -d '' candidate; do
    resolved="$(/bin/realpath "$candidate" 2>/dev/null)" || {
      /bin/rm -rf -- "$temporary"
      printf 'FATAL: app bundle contains a dangling symlink: %s\n' "$candidate" >&2
      return 1
    }
    if [[ "$resolved" != "$app_real" && "$resolved" != "$app_real/"* ]]; then
      /bin/rm -rf -- "$temporary"
      printf 'FATAL: app bundle contains an escaping symlink: %s\n' "$candidate" >&2
      return 1
    fi
  done < "$temporary/symlinks"

  description="$(/usr/bin/file -b "$main_executable")" || {
    /bin/rm -rf -- "$temporary"
    echo "FATAL: cannot classify the main executable." >&2
    return 1
  }
  if [[ "$description" != *Mach-O* ]]; then
    /bin/rm -rf -- "$temporary"
    echo "FATAL: main executable is not Mach-O." >&2
    return 1
  fi
  if ! verify_macho_load_paths "$main_executable" "$app_real" "$main_executable"; then
    /bin/rm -rf -- "$temporary"
    return 1
  fi

  while IFS= read -r -d '' candidate; do
    [[ "$candidate" != "$main_executable" ]] || continue
    description="$(/usr/bin/file -b "$candidate")" || {
      /bin/rm -rf -- "$temporary"
      printf 'FATAL: cannot classify bundled file: %s\n' "$candidate" >&2
      return 1
    }
    [[ "$description" == *Mach-O* ]] || continue
    if ! verify_nested_macho_signature "$candidate" "$expected" \
      || ! verify_macho_load_paths "$candidate" "$app_real" "$main_executable"; then
      /bin/rm -rf -- "$temporary"
      return 1
    fi
  done < "$temporary/files"

  /bin/rm -rf -- "$temporary"
}

verify_activitylogger_app_with_policy() {
  local app="$1"
  local require_current_entitlements="$2"
  local bundle_id="com.mk.activitylogger.native"
  local pin_file="${ACTIVITYLOGGER_CERT_FINGERPRINT_FILE:-${REPO:?REPO is not set}/.codesign/leaf.sha1}"
  local expected="${ACTIVITYLOGGER_CERT_SHA1:-}"
  local verify_output details dr actual

  if [[ ! -d "$app" || -L "$app" ]]; then
    echo "FATAL: missing app bundle: $app" >&2
    return 1
  fi
  if [[ -z "$expected" ]]; then
    if [[ ! -f "$pin_file" ]]; then
      echo "FATAL: missing signing fingerprint: $pin_file" >&2
      echo "Run scripts/setup_signing_identity.sh before building." >&2
      return 1
    fi
    expected="$(tr -d '[:space:]' < "$pin_file")"
  fi
  expected="$(printf '%s' "$expected" | tr '[:upper:]' '[:lower:]')"
  if [[ ! "$expected" =~ ^[0-9a-f]{40}$ ]]; then
    echo "FATAL: signing fingerprint must be exactly 40 hexadecimal characters." >&2
    return 1
  fi

  if ! verify_output="$(
    /usr/bin/codesign --verify --deep --strict --verbose=4 \
      -R="certificate leaf = H\"$expected\"" "$app" 2>&1
  )"; then
    printf '%s\n' "$verify_output" >&2
    echo "FATAL: strict code-signature or pinned identity verification failed: $app" >&2
    return 1
  fi

  if ! details="$(/usr/bin/codesign -d --verbose=4 "$app" 2>&1)"; then
    printf '%s\n' "$details" >&2
    echo "FATAL: cannot read app signature metadata." >&2
    return 1
  fi
  if ! /usr/bin/grep -Fxq "Identifier=$bundle_id" <<< "$details"; then
    printf '%s\n' "$details" >&2
    echo "FATAL: bundle identifier is not exactly $bundle_id." >&2
    return 1
  fi
  if ! dr="$(/usr/bin/codesign -d -r- "$app" 2>&1)"; then
    printf '%s\n' "$dr" >&2
    echo "FATAL: cannot read the app designated requirement." >&2
    return 1
  fi
  if ! /usr/bin/grep -Fxq \
    "designated => identifier \"$bundle_id\" and certificate leaf = H\"$expected\"" \
    <<< "$dr"; then
    printf '%s\n' "$dr" >&2
    echo "FATAL: designated requirement does not exactly match the pinned identity." >&2
    return 1
  fi
  actual="$expected"

  verify_bundle_contents "$app" "$expected" || return 1
  if [[ "$require_current_entitlements" == "1" ]]; then
    verify_entitlement_allowlist "$app" || return 1
  fi

  printf 'Verified identifier=%s certificate_leaf_sha1=%s\n' "$bundle_id" "$actual"
}

verify_activitylogger_app() {
  verify_activitylogger_app_with_policy "$1" 1
}

# This gate is only for the exact app captured before a promotion. It preserves
# identity and integrity checks while accepting its historical entitlement profile.
verify_activitylogger_rollback_app() {
  verify_activitylogger_app_with_policy "$1" 0
}

# Backward-compatible name used by the launch and install scripts.
require_certificate_leaf() {
  verify_activitylogger_app "$1"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -euo pipefail
  _HERE="$(cd "$(dirname "$0")" && pwd)"
  # shellcheck source=resolve_repo_root.sh
  source "${_HERE}/resolve_repo_root.sh"
  resolve_repo_root "${_HERE}/../.."
  verify_activitylogger_app "${1:-${REPO}/dist/ActivityLoggerNative.app}"
fi
