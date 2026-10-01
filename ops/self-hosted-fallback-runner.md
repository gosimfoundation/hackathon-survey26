# Self-hosted evaluation fallback runner

Evaluation normally runs on GitHub-hosted runners in the runner organizations
(`AGENTIC-OBSERVER26-runner-N`). The fallback runner is an organizer-owned,
isolated Linux virtual machine that takes jobs **only when GitHub-hosted
evaluation is unavailable everywhere**. It is off unless an installation row
has `fallback_capacity > 0`.

## When a job goes to the fallback

`observer-dispatch` (`supabase/functions/_shared/observer-dispatch.ts`) and
`observer_pending_jobs` (`supabase/migrations/20261001000500_self_hosted_fallback.sql`)
route a job to the fallback only while a fallback slot is free, and only in
these cases:

| Case | Condition |
|---|---|
| Every organization fails | An organization-level dispatch failure (`ORGANIZATION_FAILURES`) on the job's organization, and the failover to the next best organization is impossible or fails the same way. |
| Runs never start | GitHub accepted three dispatches of the job, but no run claimed it ten minutes after the last one (hosted runners unavailable, Actions locked by billing or a spending limit). |
| Every organization over quota | Every enabled organization is over its `monthly_minute_limit`. If no slot is free the job still runs GitHub-hosted in its own organization. |

Transient GitHub errors (`github_unavailable`, timeouts) never move a job.
`observer_fallback_job` moves the job (and, like `observer_failover_job`, the
owner's placement when the organization changes) to the fallback
organization's approved runtime and marks it `runner='self-hosted'`. The
dispatcher then sends the extra workflow input `runner=self-hosted`, which
makes the control workflow use `runs-on: [self-hosted, linux, observer-fallback]`.
A self-hosted job already accepted by GitHub is not re-dispatched; it holds its
slot until it finishes or its lease expires.

The fallback depends on GitHub's API and Actions service just like the hosted
runners; it does not help during a GitHub-wide outage.

## Security boundary

Participant code must never reach the organizer's Mac. Four layers, from the
inside out:

1. **Job sandbox** — as on GitHub-hosted runners, participant code runs only in
   the trusted job runner's Docker container (`--cap-drop=ALL`,
   `no-new-privileges`, read-only root, non-root user, resource limits).
2. **gVisor** — in the VM, Docker's default runtime is `runsc`: a container
   talks to gVisor's user-space kernel, so a kernel exploit does not reach the
   VM kernel. (amd64-only images are not supported on the fallback.)
3. **The VM** (`ops/fallback-runner/observer-fallback.yaml`) — Lima `plain`
   mode: no host directory mounts, no port forwarding, no guest agent, no SSH
   agent forwarding. Nothing from the Mac (browser profile, GitHub login,
   keychain, `~/.ssh`) exists inside; the only secret is the runner's own
   registration, created from a one-hour register-only token. The runner is
   registered at **repository level** on `observer-control`, so only the
   reviewed control workflows run there. Every job starts and ends with
   `/opt/observer/job-cleanup.sh` (all containers, images, volumes and
   temporary files removed), so one VM hosts exactly one runner. An in-VM
   egress guard (iptables `OUTPUT`, `DOCKER-USER`, `INPUT`) keeps containers
   and non-root code away from the Mac (`192.168.5.2`), private, fake-IP and
   link-local networks and from the VM itself; the runner service requires it.
4. **Host boundary (required before enabling)** — Lima's user-mode network
   maps `192.168.5.2` to the Mac's loopback, and a local HTTP proxy happily
   forwards to `127.0.0.1` too. Code that becomes root inside the VM can undo
   the in-VM guard, so the Mac must enforce the boundary itself:
   - the VM runs under a dedicated macOS account (`observerfb`), and pf
     (`ops/fallback-runner/pf.anchor`) lets that account reach only the public
     internet, the VM's own SSH port and the egress proxy — never the Mac's
     other loopback services (e.g. the browser's debugging port) or the LAN;
   - `ops/fallback-runner/egress-proxy.py`, run by the organizer's account,
     accepts only `CONNECT <allowlisted host>:443` (GitHub, container
     registries, PyPI, gVisor, Supabase) and chains to the local proxy.
     IP literals, loopback names and other ports are refused.

## One-time setup (organizer's Mac, needs an administrator once)

Prerequisites: Lima (`brew install lima`). No Docker on the Mac.

1. Host boundary (administrator):

   ```sh
   # A standard account that only runs the VM (no login use).
   sudo sysadminctl -addUser observerfb -fullName "Observer fallback VM" -password -
   # Egress proxy, run by the organizer's own account.
   sudo mkdir -p /Users/Shared/observer-fallback
   sudo cp ops/fallback-runner/egress-proxy.py /Users/Shared/observer-fallback/
   cp ops/fallback-runner/org.agentic-observer.egress-proxy.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/org.agentic-observer.egress-proxy.plist
   # pf anchor, loaded at boot.
   sudo cp ops/fallback-runner/pf.anchor /etc/pf.anchors/observer-fallback
   printf 'anchor "observer-fallback"\nload anchor "observer-fallback" from "/etc/pf.anchors/observer-fallback"\n' \
     | sudo tee -a /etc/pf.conf
   sudo cp ops/fallback-runner/org.agentic-observer.pf.plist /Library/LaunchDaemons/
   sudo launchctl load /Library/LaunchDaemons/org.agentic-observer.pf.plist
   sudo pfctl -a observer-fallback -s rules   # the four rules are listed
   ```

2. Create and boot the VM as `observerfb`. `HostProxyPort` is the egress
   proxy. `Resolvers` is needed when the Mac's resolver returns a local
   proxy's fake IPs (`198.18.0.0/15`), which the VM refuses; `AptMirror` is
   optional:

   ```sh
   sudo cp ops/fallback-runner/observer-fallback.yaml /Users/Shared/observer-fallback/
   sudo -u observerfb -H limactl create --name observer-fallback \
     --set '.param.HostProxyPort="18080" | .param.Resolvers="223.5.5.5 119.29.29.29" | .param.AptMirror="https://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports"' \
     /Users/Shared/observer-fallback/observer-fallback.yaml
   sudo -u observerfb -H limactl start observer-fallback
   sudo -u observerfb -H limactl shell observer-fallback -- sudo cloud-init status --wait
   ```

   If the Ubuntu image download is slow, fetch the same image from a mirror,
   compare its SHA-256 with `https://cloud-images.ubuntu.com/noble/current/SHA256SUMS`
   and add `| .images=[{"location":"/path/to.img","arch":"aarch64","digest":"sha256:<sum>"}]`
   to the `--set` expression.

3. Check every layer (each command must print `blocked`):

   ```sh
   vm() { sudo -u observerfb -H limactl shell observer-fallback -- "$@"; }
   vm ls /Users 2>/dev/null || echo blocked                          # no host files
   vm sudo docker info | grep -q 'Default Runtime: runsc' && echo gvisor
   vm sudo -u runner docker run --rm alpine:3.20 sh -c \
     'nc -z -w 3 192.168.5.2 18800 || echo blocked'                   # containers
   # Even VM root, with the in-VM guard bypassed, must not reach the browser:
   vm sudo sh -c 'iptables -I OUTPUT 1 -j ACCEPT; curl -s -m 5 http://192.168.5.2:18800/json/version || echo blocked;
     curl -s -m 5 -x http://192.168.5.2:18080 http://127.0.0.1:18800/json/version || echo blocked;
     iptables -D OUTPUT 1'
   ```

4. Register the runner on the fallback organization's `observer-control`
   (runner-13 by default). The VM is disposable: to re-register, recreate it.

   ```sh
   token=$(gh api -X POST repos/AGENTIC-OBSERVER26-runner-13/observer-control/actions/runners/registration-token -q .token)
   sudo -u observerfb -H limactl shell observer-fallback sudo env RUNNER_TOKEN="$token" \
     RUNNER_URL=https://github.com/AGENTIC-OBSERVER26-runner-13/observer-control \
     bash -s < ops/fallback-runner/install-runner.sh
   ```

## Rollout checklist (production)

1. Merge this change; apply migration `20261001000500_self_hosted_fallback.sql`.
   It adds columns with safe defaults (`fallback_capacity=0`,
   `runner='github-hosted'`), so nothing changes yet.
2. Deploy the `observer-dispatch` edge function.
3. Republish the fallback organization's `observer-control` from this main
   commit (`scripts/build-observer-control.py`), tag
   `observer-runtime-<sha>`, and approve that sha in its installation row. The
   new workflows accept the optional `runner` input; other organizations may
   keep their current runtime because the input is only sent to the fallback.
4. Set up the host boundary and the VM and register the runner (above);
   confirm it is "Idle" under the repository's Actions → Runners.
5. Enable: `update private.observer_installations set fallback_capacity=1
   where organization='AGENTIC-OBSERVER26-runner-13';`
   `fallback_capacity` is the number of fallback VMs registered there; each
   VM hosts exactly one runner because its job cleanup removes every
   container. A split (execute + engine) run needs two free slots, so phases
   that are not colocated need two VMs to use the fallback.

Disable at any time with `fallback_capacity=0` (pending self-hosted jobs keep
their slot until they finish or expire), then `limactl stop observer-fallback`.
