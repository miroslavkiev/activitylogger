#!/bin/bash
# One-time provisioning for the dedicated ActivityLogger signing keychain.
# Production import mode preserves the deployed identity and uses SecurityAgent
# prompts so passwords never appear in argv or environment variables.
set -euo pipefail
umask 077

usage() {
  printf '%s\n' \
    "Usage: $0 --import-p12 PATH [--rotate-identity]" \
    "   or: CI=true ACTIVITYLOGGER_CI_EPHEMERAL=1 $0 --create-ephemeral-ci" >&2
  exit 2
}

certificate_fingerprint() {
  local certificate="$1"
  /usr/bin/openssl x509 -in "$certificate" -noout -fingerprint -sha1 \
    | /usr/bin/sed 's/^.*=//' \
    | /usr/bin/tr -d ':' \
    | /usr/bin/tr '[:upper:]' '[:lower:]'
}

deployed_app_fingerprint() {
  local app="$1"
  local requirement fingerprint
  requirement="$(/usr/bin/codesign -d -r- "$app" 2>&1)" || return 1
  fingerprint="$(
    printf '%s\n' "$requirement" \
      | /usr/bin/sed -nE 's/^designated => .*certificate leaf = H"([0-9A-Fa-f]{40})".*$/\1/p'
  )"
  [[ "$fingerprint" =~ ^[0-9A-Fa-f]{40}$ ]] || return 1
  printf '%s\n' "$fingerprint" | /usr/bin/tr '[:upper:]' '[:lower:]'
}

require_identity_continuity() {
  local deployed="$1"
  local supplied="$2"
  local rotate="${3:-0}"
  if [[ -z "$deployed" || "$deployed" == "$supplied" ]]; then
    return 0
  fi
  if [[ "$rotate" == "1" ]]; then
    printf 'WARNING: --rotate-identity permits leaf change from %s to %s. Existing TCC grants will not follow.\n' \
      "$deployed" "$supplied" >&2
    return 0
  fi
  printf 'FATAL: supplied PKCS#12 leaf %s does not match deployed app leaf %s.\n' \
    "$supplied" "$deployed" >&2
  printf '%s\n' 'Refusing identity rotation. Re-run with --rotate-identity only for an intentional TCC-breaking rotation.' >&2
  return 1
}

cleanup_created_pin() {
  local status="$1"
  local created="$2"
  local pin_file="$3"
  if [[ "$status" -ne 0 && "$created" -eq 1 ]]; then
    /bin/rm -f -- "$pin_file"
  fi
}

imported_identity_fingerprint() {
  local keychain="$1"
  local output fingerprints count fingerprint
  output="$(/usr/bin/security find-identity -p codesigning "$keychain")" || return 1
  fingerprints="$(
    printf '%s\n' "$output" \
      | /usr/bin/sed -nE 's/^[[:space:]]*[0-9]+\) ([0-9A-Fa-f]{40}) .*/\1/p' \
      | /usr/bin/tr '[:upper:]' '[:lower:]'
  )"
  count="$(printf '%s\n' "$fingerprints" | /usr/bin/awk 'NF { count++ } END { print count + 0 }')"
  [[ "$count" == "1" ]] || {
    printf 'FATAL: expected exactly one valid code-signing identity in %s, found %s.\n' \
      "$keychain" "$count" >&2
    return 1
  }
  fingerprint="$(printf '%s\n' "$fingerprints" | /usr/bin/awk 'NF { print; exit }')"
  [[ "$fingerprint" =~ ^[0-9a-f]{40}$ ]] || return 1
  printf '%s\n' "$fingerprint"
}

export_imported_leaf() {
  local keychain="$1"
  local expected="$2"
  local destination="$3"
  local temporary_dir="$4"
  local bundle="$temporary_dir/imported-certificates.pem"
  local line current="" fingerprint index=0

  /usr/bin/security find-certificate -a -p "$keychain" > "$bundle"
  while IFS= read -r line; do
    if [[ "$line" == "-----BEGIN CERTIFICATE-----" ]]; then
      index=$((index + 1))
      current="$temporary_dir/imported-certificate-$index.pem"
      : > "$current"
    fi
    if [[ -n "$current" ]]; then
      printf '%s\n' "$line" >> "$current"
    fi
    if [[ "$line" == "-----END CERTIFICATE-----" && -n "$current" ]]; then
      fingerprint="$(certificate_fingerprint "$current")"
      if [[ "$fingerprint" == "$expected" ]]; then
        /bin/cp "$current" "$destination"
        return 0
      fi
      current=""
    fi
  done < "$bundle"
  printf 'FATAL: could not export imported leaf certificate %s.\n' "$expected" >&2
  return 1
}

main() {
  [[ $# -ge 1 ]] || usage
  local mode="$1"
  shift
  local rotate=0 source_p12=""
  case "$mode" in
    --import-p12)
      [[ $# -ge 1 ]] || usage
      source_p12="$1"
      shift
      if [[ $# -eq 1 && "$1" == "--rotate-identity" ]]; then
        rotate=1
        shift
      fi
      [[ $# -eq 0 ]] || usage
      ;;
    --create-ephemeral-ci)
      [[ $# -eq 0 ]] || usage
      [[ "${CI:-}" == "true" && "${ACTIVITYLOGGER_CI_EPHEMERAL:-0}" == "1" ]] || {
        printf '%s\n' 'FATAL: --create-ephemeral-ci is restricted to an explicitly marked CI job.' >&2
        exit 2
      }
      ;;
    *) usage ;;
  esac

  local here repo cert_name identity_dir keychain pin_file deployed_app
  here="$(cd "$(dirname "$0")" && pwd)"
  # shellcheck source=lib/resolve_repo_root.sh
  source "${here}/lib/resolve_repo_root.sh"
  # shellcheck source=lib/ensure_log_dir.sh
  source "${here}/lib/ensure_log_dir.sh"
  resolve_repo_root "${here}/.."
  repo="$REPO"
  cert_name="${ACTIVITYLOGGER_CERT_NAME:-ActivityLogger Code Signing}"
  identity_dir="${repo}/.codesign"
  keychain="${ACTIVITYLOGGER_KEYCHAIN:-${identity_dir}/activitylogger-signing.keychain-db}"
  pin_file="${ACTIVITYLOGGER_CERT_FINGERPRINT_FILE:-${identity_dir}/leaf.sha1}"
  deployed_app="${ACTIVITYLOGGER_DEPLOYED_APP:-${repo}/dist/ActivityLoggerNative.app}"

  if [[ -n "${ACTIVITYLOGGER_KEYCHAIN_PASSWORD:-}" || -n "${ACTIVITYLOGGER_P12_PASS:-}" ]]; then
    unset ACTIVITYLOGGER_KEYCHAIN_PASSWORD ACTIVITYLOGGER_P12_PASS
    printf '%s\n' 'FATAL: password environment variables are not accepted. Use native interactive prompts.' >&2
    exit 2
  fi
  unset ACTIVITYLOGGER_KEYCHAIN_PASSWORD ACTIVITYLOGGER_P12_PASS

  if [[ -L "$keychain" || -L "$pin_file" || -e "$keychain" || -e "$pin_file" ]]; then
    printf '%s\n' 'FATAL: signing keychain or fingerprint already exists. Archive it explicitly before provisioning.' >&2
    exit 1
  fi
  ensure_log_dir "$identity_dir"

  local deployed_fingerprint=""
  if [[ "$mode" == "--import-p12" && -e "$deployed_app" ]]; then
    if ! deployed_fingerprint="$(deployed_app_fingerprint "$deployed_app")"; then
      if [[ "$rotate" != "1" ]]; then
        printf 'FATAL: cannot derive a certificate leaf from deployed app: %s\n' "$deployed_app" >&2
        exit 1
      fi
      printf 'WARNING: --rotate-identity permits replacing an unverifiable deployed identity: %s\n' \
        "$deployed_app" >&2
    fi
  fi

  local temporary created_keychain=0 search_list_updated=0 trust_added=0 pin_created=0
  local p12 certificate fingerprint keychain_password="" p12_password=""
  local existing_keychain pin_temporary=""
  local -a original_keychains=()
  temporary="$(mktemp -d "${TMPDIR:-/tmp}/activitylogger-signing.XXXXXX")"
  p12="$temporary/identity.p12"
  certificate="$temporary/certificate.pem"
  while IFS= read -r existing_keychain; do
    existing_keychain="${existing_keychain#\"}"
    existing_keychain="${existing_keychain%\"}"
    [[ -z "$existing_keychain" ]] || original_keychains+=("$existing_keychain")
  done < <(/usr/bin/security list-keychains -d user | /usr/bin/sed 's/^[[:space:]]*//; s/[[:space:]]*$//')

  cleanup() {
    local status=$?
    cleanup_created_pin "$status" "$pin_created" "$pin_file"
    if [[ $status -ne 0 && $created_keychain -eq 1 ]]; then
      if [[ $trust_added -eq 1 && -f "$certificate" ]]; then
        /usr/bin/security remove-trusted-cert "$certificate" 2>/dev/null || true
      fi
      if [[ $search_list_updated -eq 1 ]]; then
        /usr/bin/security list-keychains -d user -s "${original_keychains[@]}" 2>/dev/null || true
      fi
      /usr/bin/security delete-keychain "$keychain" 2>/dev/null || true
    fi
    keychain_password=""
    p12_password=""
    unset keychain_password p12_password ACTIVITYLOGGER_KEYCHAIN_PASSWORD ACTIVITYLOGGER_P12_PASS
    if [[ -n "$pin_temporary" ]]; then
      /bin/rm -f -- "$pin_temporary"
    fi
    /bin/rm -rf "$temporary"
    exit "$status"
  }
  trap cleanup EXIT

  if [[ "$mode" == "--import-p12" ]]; then
    [[ -f "$source_p12" && ! -L "$source_p12" ]] || {
      printf 'FATAL: missing or unsafe PKCS#12 file: %s\n' "$source_p12" >&2
      exit 1
    }
    /bin/cp "$source_p12" "$p12"
    /usr/bin/security create-keychain -P "$keychain"
    created_keychain=1
    /usr/bin/security set-keychain-settings -lut 21600 "$keychain"
    /usr/bin/security unlock-keychain -u "$keychain"
    /usr/bin/security list-keychains -d user -s "${original_keychains[@]}" "$keychain"
    search_list_updated=1
    /usr/bin/security import "$p12" -k "$keychain" -f pkcs12 -x -T /usr/bin/codesign
    fingerprint="$(imported_identity_fingerprint "$keychain")"
    require_identity_continuity "$deployed_fingerprint" "$fingerprint" "$rotate"
    export_imported_leaf "$keychain" "$fingerprint" "$certificate" "$temporary"
  else
    keychain_password="$(/usr/bin/openssl rand -hex 32)"
    p12_password="$(/usr/bin/openssl rand -hex 32)"
    /usr/bin/openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 2 \
      -subj "/CN=${cert_name}" \
      -addext "basicConstraints=critical,CA:FALSE" \
      -addext "keyUsage=critical,digitalSignature" \
      -addext "extendedKeyUsage=critical,codeSigning" \
      -keyout "$temporary/private-key.pem" -out "$certificate"
    /usr/bin/openssl pkcs12 -export -inkey "$temporary/private-key.pem" -in "$certificate" \
      -out "$p12" -passout "pass:${p12_password}" -name "$cert_name"
    fingerprint="$(certificate_fingerprint "$certificate")"
    /usr/bin/security create-keychain -p "$keychain_password" "$keychain"
    created_keychain=1
    /usr/bin/security set-keychain-settings -lut 21600 "$keychain"
    /usr/bin/security unlock-keychain -p "$keychain_password" "$keychain"
    /usr/bin/security list-keychains -d user -s "${original_keychains[@]}" "$keychain"
    search_list_updated=1
    /usr/bin/security import "$p12" -k "$keychain" -P "$p12_password" -f pkcs12 -x \
      -T /usr/bin/codesign
    keychain_password=""
    p12_password=""
    unset keychain_password p12_password
  fi

  /usr/bin/security add-trusted-cert -r trustRoot -p codeSign -k "$keychain" "$certificate"
  trust_added=1
  if ! /usr/bin/security find-identity -v -p codesigning "$keychain" \
    | /usr/bin/tr '[:upper:]' '[:lower:]' \
    | /usr/bin/grep -F "$fingerprint" >/dev/null; then
    printf '%s\n' 'FATAL: imported certificate is not a valid code-signing identity.' >&2
    exit 1
  fi

  pin_temporary="$(mktemp "${pin_file}.new.XXXXXX")"
  printf '%s\n' "$fingerprint" > "$pin_temporary"
  /bin/chmod 600 "$pin_temporary"
  if ! /bin/ln "$pin_temporary" "$pin_file"; then
    printf 'FATAL: refusing to replace existing signing fingerprint: %s\n' "$pin_file" >&2
    exit 1
  fi
  pin_created=1
  /bin/rm -f -- "$pin_temporary"
  pin_temporary=""
  /bin/chmod 600 "$keychain"
  printf 'Provisioned dedicated signing keychain: %s\n' "$keychain"
  printf 'Pinned certificate leaf SHA-1: %s\n' "$fingerprint"
  printf '%s\n' 'The imported private key is nonextractable. Normal rebuilds cannot create or rotate it.'
  created_keychain=0
  pin_created=0
  # EXIT runs after main's local variables leave scope, so clean successful
  # provisioning while those values are still defined.
  trap - EXIT
  keychain_password=""
  p12_password=""
  unset keychain_password p12_password ACTIVITYLOGGER_KEYCHAIN_PASSWORD ACTIVITYLOGGER_P12_PASS
  /bin/rm -f -- "$pin_temporary"
  /bin/rm -rf "$temporary"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
