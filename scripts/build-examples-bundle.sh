#!/usr/bin/env bash
# Rebuild the combined examples+local-cards bundle and upload it to the GitHub Release that
# backs the Resources page's "download all examples" button.
#
#   scripts/build-examples-bundle.sh                 # rebuild + upload to examples-2026-10-02
#   scripts/build-examples-bundle.sh <release-tag>    # upload to a different tag
#
# Requires `gh` authenticated against gosimfoundation/hackathon-survey26.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG="${1:-examples-2026-10-02}"

cd "$ROOT/web"
node scripts/build-examples-bundle.mjs

ZIP="$ROOT/web/dist-bundle/gosim-observer-examples.zip"
echo "[build-examples-bundle] uploading $ZIP to release $TAG"
gh release upload "$TAG" "$ZIP" --clobber --repo gosimfoundation/hackathon-survey26
