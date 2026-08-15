#!/bin/bash
# Create (if needed) a self-signed Code Signing identity and sign
# dist/ActivityLoggerNative.app so TCC grants survive rebuilds.
#
# Stable TCC uses certificate leaf in the designated requirement, not cdhash.
# You cannot keep a stable cdhash across rebuilds; this is the durable alternative.
set -euo pipefail

_HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/resolve_repo_root.sh
source "${_HERE}/lib/resolve_repo_root.sh"
# shellcheck source=lib/require_certificate_leaf.sh
source "${_HERE}/lib/require_certificate_leaf.sh"

resolve_repo_root "${_HERE}/.."
APP="${REPO}/dist/ActivityLoggerNative.app"
CERT_NAME="${ACTIVITYLOGGER_CERT_NAME:-ActivityLogger Code Signing}"
KEYCHAIN="${ACTIVITYLOGGER_KEYCHAIN:-$HOME/Library/Keychains/login.keychain-db}"
IDENTITY_FILE="${REPO}/.codesign/identity.p12"
IDENTITY_DIR="$(dirname "$IDENTITY_FILE")"
# Local-only P12 password (not used for Apple trust; just PKCS#12 wrapping)
P12_PASS="${ACTIVITYLOGGER_P12_PASS:-activitylogger-local-codesign}"

have_identity() {
  security find-identity -p codesigning "$KEYCHAIN" 2>/dev/null | grep -F "$CERT_NAME" >/dev/null
}

create_identity() {
  echo "Creating self-signed Code Signing identity: $CERT_NAME"
  mkdir -p "$IDENTITY_DIR"
  chmod 700 "$IDENTITY_DIR"

  local tmp
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/al-codesign.XXXXXX")"
  trap 'rm -rf "$tmp"' RETURN

  cat >"$tmp/openssl.cnf" <<EOF
[req]
distinguished_name = dn
x509_extensions = codesign
prompt = no

[dn]
CN = ${CERT_NAME}

[codesign]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
EOF

  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -keyout "$tmp/key.pem" -out "$tmp/cert.pem" \
    -config "$tmp/openssl.cnf"

  openssl pkcs12 -export \
    -inkey "$tmp/key.pem" -in "$tmp/cert.pem" \
    -out "$IDENTITY_FILE" -passout "pass:${P12_PASS}" \
    -name "$CERT_NAME"

  chmod 600 "$IDENTITY_FILE"

  # Allow codesign to use the key without interactive ACL prompts where possible
  security unlock-keychain "$KEYCHAIN" 2>/dev/null || true
  security import "$IDENTITY_FILE" -k "$KEYCHAIN" -P "$P12_PASS" \
    -T /usr/bin/codesign -T /usr/bin/security \
    -f pkcs12 2>/dev/null \
    || security import "$IDENTITY_FILE" -k "$KEYCHAIN" -P "$P12_PASS" \
         -T /usr/bin/codesign -T /usr/bin/security

  # Best-effort: mark key partition for codesign (may fail if login keychain has a password)
  security set-key-partition-list -S apple-tool:,apple:,codesign: -s -t private \
    -k "" "$KEYCHAIN" 2>/dev/null || true

  if ! have_identity; then
    echo "ERROR: identity imported but not visible to codesign." >&2
    echo "Open Keychain Access, find '$CERT_NAME', and allow codesign access." >&2
    exit 1
  fi
  echo "Identity ready in keychain: $CERT_NAME"
  echo "PKCS#12 backup (gitignored): $IDENTITY_FILE"
}

sign_app() {
  if [[ ! -d "$APP" ]]; then
    echo "Missing $APP — run: ./scripts/rebuild_and_restart.sh" >&2
    exit 1
  fi

  echo "Signing $APP with: $CERT_NAME"
  codesign --force --deep \
    --sign "$CERT_NAME" \
    --identifier com.mk.activitylogger.native \
    "$APP"

  echo "Designated requirement:"
  if ! DR="$(require_certificate_leaf "$APP")"; then
    echo "$DR" | tail -5
    echo "ERROR: DR lacks certificate leaf (ad-hoc/cdhash-only). Signing failed." >&2
    echo "Fix: ensure '$CERT_NAME' is usable, then run: ./scripts/rebuild_and_restart.sh" >&2
    exit 1
  fi
  echo "$DR" | tail -5
  echo "OK: DR is certificate-anchored (TCC should survive rebuilds)."
}

if ! have_identity; then
  create_identity
fi
sign_app
