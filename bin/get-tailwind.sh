#!/usr/bin/env bash
# Fetch the pinned Tailwind standalone CLI, checksum-verified (T10.2).
# The binary is NOT committed (it is in .gitignore); the built CSS is.
set -euo pipefail

VERSION="v4.1.14"
DEST="bin/tailwindcss"

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64)  ASSET="tailwindcss-macos-arm64";  SHA256="e722b752f51def86d42e886b4c1171f2d09a4be1a7487a0a51e4aff8e7603ce3" ;;
  Darwin-x86_64) ASSET="tailwindcss-macos-x64";    SHA256="" ;;
  Linux-x86_64)  ASSET="tailwindcss-linux-x64";    SHA256="" ;;
  Linux-aarch64) ASSET="tailwindcss-linux-arm64";  SHA256="" ;;
  *) echo "Unsupported platform: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac

URL="https://github.com/tailwindlabs/tailwindcss/releases/download/${VERSION}/${ASSET}"
echo "Fetching ${ASSET} ${VERSION}…"
curl -sL --fail -o "${DEST}" "${URL}"
chmod +x "${DEST}"

if [ -n "${SHA256}" ]; then
  actual="$(shasum -a 256 "${DEST}" | awk '{print $1}')"
  if [ "${actual}" != "${SHA256}" ]; then
    echo "Checksum mismatch for ${ASSET}:" >&2
    echo "  expected ${SHA256}" >&2
    echo "  actual   ${actual}" >&2
    rm -f "${DEST}"
    exit 1
  fi
  echo "Checksum verified."
else
  echo "WARNING: no pinned checksum for ${ASSET}; pin it before using in CI." >&2
fi

echo "Installed ${DEST} (${VERSION})."
