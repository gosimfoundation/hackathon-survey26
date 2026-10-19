#!/usr/bin/env bash
# Read-only page fetch for the patrol agent: GET only, no request body, no custom method.
# The agent is allowed to run this script and nothing that can write.
set -euo pipefail
url="${1:?usage: get.sh <https-url>}"
case "$url" in https://*) ;; *) echo "only https URLs" >&2; exit 2 ;; esac
exec curl -sS -L --max-time 30 --max-filesize 5000000 -w '\n[HTTP %{http_code}, %{size_download} bytes]\n' "$url"
