#!/bin/bash
# Sign an existing app with the pre-provisioned, pinned local identity.
# Identity creation and migration are deliberately separate from normal builds.
set -euo pipefail

_HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/resolve_repo_root.sh
source "${_HERE}/lib/resolve_repo_root.sh"
# shellcheck source=lib/require_certificate_leaf.sh
source "${_HERE}/lib/require_certificate_leaf.sh"

resolve_repo_root "${_HERE}/.."
APP="${ACTIVITYLOGGER_APP:-${REPO}/dist/ActivityLoggerNative.app}"
KEYCHAIN="${ACTIVITYLOGGER_KEYCHAIN:-${REPO}/.codesign/activitylogger-signing.keychain-db}"
PIN_FILE="${ACTIVITYLOGGER_CERT_FINGERPRINT_FILE:-${REPO}/.codesign/leaf.sha1}"
ENTITLEMENTS="${REPO}/ActivityLoggerNative.entitlements"
BUNDLE_ID="com.mk.activitylogger.native"
SCAN_DIR=""

cleanup() {
  if [[ -n "$SCAN_DIR" ]]; then
    /bin/rm -rf -- "$SCAN_DIR"
  fi
}
trap cleanup EXIT

if [[ ! -d "$APP" ]]; then
  echo "FATAL: missing app bundle: $APP" >&2
  exit 1
fi
if [[ ! -f "$KEYCHAIN" ]]; then
  echo "FATAL: missing dedicated signing keychain: $KEYCHAIN" >&2
  echo "Run scripts/setup_signing_identity.sh first." >&2
  exit 1
fi
if [[ ! -f "$PIN_FILE" ]]; then
  echo "FATAL: missing pinned certificate fingerprint: $PIN_FILE" >&2
  exit 1
fi

FINGERPRINT="$(tr -d '[:space:]' < "$PIN_FILE" | tr '[:upper:]' '[:lower:]')"
if [[ ! "$FINGERPRINT" =~ ^[0-9a-f]{40}$ ]]; then
  echo "FATAL: invalid certificate fingerprint in $PIN_FILE" >&2
  exit 1
fi

if [[ "${ACTIVITYLOGGER_CI_EPHEMERAL:-0}" == "1" ]]; then
  if [[ "${CI:-}" != "true" ]]; then
    echo "FATAL: ACTIVITYLOGGER_CI_EPHEMERAL is restricted to CI." >&2
    exit 2
  fi
  unset ACTIVITYLOGGER_KEYCHAIN_PASSWORD ACTIVITYLOGGER_P12_PASS
else
  if [[ -n "${ACTIVITYLOGGER_KEYCHAIN_PASSWORD:-}" || -n "${ACTIVITYLOGGER_P12_PASS:-}" ]]; then
    unset ACTIVITYLOGGER_KEYCHAIN_PASSWORD ACTIVITYLOGGER_P12_PASS
    echo "FATAL: password environment variables are not accepted. Use the native keychain prompt." >&2
    exit 2
  fi
  unset ACTIVITYLOGGER_KEYCHAIN_PASSWORD ACTIVITYLOGGER_P12_PASS
  /usr/bin/security unlock-keychain -u "$KEYCHAIN"
fi
IDENTITY_OUTPUT="$(/usr/bin/security find-identity -v -p codesigning "$KEYCHAIN")" || {
  echo "FATAL: cannot enumerate code-signing identities in $KEYCHAIN" >&2
  exit 1
}
IDENTITY_FINGERPRINTS="$(
  printf '%s\n' "$IDENTITY_OUTPUT" \
    | /usr/bin/sed -nE 's/^[[:space:]]*[0-9]+\) ([0-9A-Fa-f]{40}) .*/\1/p' \
    | /usr/bin/tr '[:upper:]' '[:lower:]'
)"
IDENTITY_COUNT="$(
  printf '%s\n' "$IDENTITY_FINGERPRINTS" \
    | /usr/bin/awk 'NF { count++ } END { print count + 0 }'
)"
IDENTITY_FINGERPRINT="$(
  printf '%s\n' "$IDENTITY_FINGERPRINTS" | /usr/bin/awk 'NF { print; exit }'
)"
if [[ "$IDENTITY_COUNT" != "1" || "$IDENTITY_FINGERPRINT" != "$FINGERPRINT" ]]; then
  echo "FATAL: dedicated keychain must contain exactly one valid identity equal to the pinned leaf." >&2
  exit 1
fi

echo "Signing nested Mach-O code with pinned identity $FINGERPRINT"
if [[ ! -d "$APP/Contents/Frameworks" ]]; then
  echo "FATAL: expected onedir Frameworks directory is missing." >&2
  exit 1
fi
MAIN_EXECUTABLE="$APP/Contents/MacOS/ActivityLoggerNative"
if [[ ! -f "$MAIN_EXECUTABLE" || -L "$MAIN_EXECUTABLE" ]]; then
  echo "FATAL: expected a regular, non-symlink main executable: $MAIN_EXECUTABLE" >&2
  exit 1
fi
SCAN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/activitylogger-sign-scan.XXXXXX")"
if ! /usr/bin/find "$APP/Contents" -type f -print0 > "$SCAN_DIR/files"; then
  echo "FATAL: cannot enumerate bundled files for signing." >&2
  exit 1
fi
while IFS= read -r -d '' candidate; do
  [[ "$candidate" != "$MAIN_EXECUTABLE" ]] || continue
  if ! description="$(/usr/bin/file -b "$candidate")"; then
    echo "FATAL: cannot classify bundled file before signing: $candidate" >&2
    exit 1
  fi
  if [[ "$description" == *Mach-O* ]]; then
    /usr/bin/codesign --force --timestamp=none \
      --keychain "$KEYCHAIN" --sign "$FINGERPRINT" "$candidate"
  fi
done < "$SCAN_DIR/files"

echo "Signing app bundle"
/usr/bin/codesign --force --timestamp=none \
  --entitlements "$ENTITLEMENTS" \
  --identifier "$BUNDLE_ID" \
  --keychain "$KEYCHAIN" \
  --sign "$FINGERPRINT" \
  "$APP"

ACTIVITYLOGGER_CERT_SHA1="$FINGERPRINT" verify_activitylogger_app "$APP"
