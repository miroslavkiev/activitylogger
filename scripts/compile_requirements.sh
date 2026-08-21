#!/bin/bash
# Regenerate the hash-locked Python 3.11 dependency set for Apple silicon macOS.
set -euo pipefail

_HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "${_HERE}/.." && pwd)"
UV="${UV:-$(command -v uv || true)}"
if [[ -z "$UV" ]]; then
  echo "FATAL: uv is required to regenerate requirements.txt" >&2
  exit 1
fi

cd "$REPO"
"$UV" pip compile requirements.in \
  --python-version 3.11 \
  --python-platform aarch64-apple-darwin \
  --generate-hashes \
  --custom-compile-command './scripts/compile_requirements.sh' \
  --output-file requirements.txt
