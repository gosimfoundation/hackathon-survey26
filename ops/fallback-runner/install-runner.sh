#!/bin/bash
# Registers the self-hosted fallback runner inside the observer-fallback VM.
# Run from the Mac (the token is a one-hour, register-only token of the single
# observer-control repository; no personal credential enters the VM):
#
#   limactl shell observer-fallback sudo env RUNNER_TOKEN=<token> \
#     RUNNER_URL=https://github.com/AGENTIC-OBSERVER26-runner-13/observer-control \
#     bash -s < ops/fallback-runner/install-runner.sh
#
# A repository-level runner serves only observer-control, so participant
# repositories in the same organization can never schedule work on it.
set -euo pipefail
: "${RUNNER_TOKEN:?registration token of the observer-control repository}"
: "${RUNNER_URL:?https://github.com/<runner organization>/observer-control}"
[[ "$RUNNER_URL" =~ ^https://github\.com/AGENTIC-OBSERVER26-runner-[0-9]+/observer-control$ ]] ||
  { echo "RUNNER_URL must be a runner organization's observer-control repository" >&2; exit 2; }
RUNNER_NAME="${RUNNER_NAME:-observer-fallback-1}"
home=/home/runner/actions-runner

port="$(cat /opt/observer/host-proxy-port 2>/dev/null || true)"
proxy_env=()
if [ -n "$port" ]; then
  proxy="http://192.168.5.2:$port"
  export https_proxy="$proxy" http_proxy="$proxy"
  proxy_env=("https_proxy=$proxy" "http_proxy=$proxy" "no_proxy=localhost,127.0.0.1")
fi

case "$(uname -m)" in aarch64) arch=arm64 ;; x86_64) arch=x64 ;; *) echo "unsupported architecture" >&2; exit 2 ;; esac
release="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest)"
version="$(jq -r .tag_name <<<"$release" | sed 's/^v//')"
# The release notes carry the official checksum of every package.
sha="$(jq -r .body <<<"$release" | sed -n "s/.*<!-- BEGIN SHA linux-$arch -->\([0-9a-f]\{64\}\)<!-- END SHA linux-$arch -->.*/\1/p")"
[ -n "$sha" ] || { echo "runner checksum not found in release $version" >&2; exit 1; }
package="actions-runner-linux-$arch-$version.tar.gz"
install -d -o runner -g runner "$home"
curl -fsSL -o "/tmp/$package" "https://github.com/actions/runner/releases/download/v$version/$package"
echo "$sha  /tmp/$package" | sha256sum -c -
tar -xzf "/tmp/$package" -C "$home" && rm -f "/tmp/$package"
chown -R runner:runner "$home"
"$home/bin/installdependencies.sh" >/dev/null

if [ -f "$home/.runner" ]; then "$home/svc.sh" stop || true; "$home/svc.sh" uninstall || true; fi
sudo -u runner env "${proxy_env[@]}" "$home/config.sh" --unattended --replace --url "$RUNNER_URL" \
  --token "$RUNNER_TOKEN" --name "$RUNNER_NAME" --labels observer-fallback --work _work
{
  printf '%s\n' "${proxy_env[@]}"
  echo "ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/observer/job-cleanup.sh"
  echo "ACTIONS_RUNNER_HOOK_JOB_COMPLETED=/opt/observer/job-cleanup.sh"
} >> "$home/.env"
cd "$home" && ./svc.sh install runner && ./svc.sh start
echo "Runner $RUNNER_NAME registered with labels self-hosted, Linux, $arch, observer-fallback."
