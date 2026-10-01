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

Participant code must never run on the organizer's Mac. The boundary is the VM:

- Lima `plain` mode (`ops/fallback-runner/observer-fallback.yaml`): no host
  directory mounts, no port forwarding, no guest agent, no SSH agent
  forwarding, `~/.ssh/*.pub` not loaded. Nothing from the Mac (browser profile,
  GitHub login, keychain) exists inside.
- Egress guard (iptables `OUTPUT` and `DOCKER-USER`): the VM and every
  container reach only the public internet. The Mac (`192.168.5.2` is its
  loopback, e.g. the browser's debugging port), private and link-local
  networks are rejected. If a host proxy is configured, only root (apt,
  dockerd) and the `runner` account may reach that one port; container traffic
  is forwarded and never matches.
- Inside the VM participant code runs exactly as on GitHub-hosted runners: in
  the trusted job runner's Docker sandbox (`--cap-drop=ALL`, read-only root,
  resource limits).
- The runner is registered at **repository level** on `observer-control`
  only, so participant repositories in the same organization can never
  schedule work on it, and only the reviewed control workflows run there.
- The only secret in the VM is the runner's own registration. It is created
  from a one-hour, register-only token.
- Every job starts and ends with `/opt/observer/job-cleanup.sh`: all
  containers, images, volumes and the runner account's temporary files are
  removed.

## One-time setup (organizer's Mac)

Prerequisites: Lima (`brew install lima`) and Rosetta on Apple silicon
(`softwareupdate --install-rosetta`). No Docker on the Mac is needed.

1. Create and boot the VM (add the `--set` only where GitHub/Docker Hub need
   the Mac's local HTTP proxy, and the Ubuntu origin is slow):

   ```sh
   limactl create --name observer-fallback \
     --set '.param.HostProxyPort="1082" | .param.AptMirror="https://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports"' \
     ops/fallback-runner/observer-fallback.yaml
   limactl start observer-fallback
   ```

2. Check the boundary from inside the VM:

   ```sh
   limactl shell observer-fallback -- ls /Users          # must fail: no host mounts
   limactl shell observer-fallback -- sudo iptables -S OBSERVER-OUTPUT
   limactl shell observer-fallback -- curl -m 5 http://192.168.5.2:18800/json/version  # must fail
   ```

3. Register the runner on the fallback organization's `observer-control`
   (runner-13 by default):

   ```sh
   token=$(gh api -X POST repos/AGENTIC-OBSERVER26-runner-13/observer-control/actions/runners/registration-token -q .token)
   limactl shell observer-fallback sudo env RUNNER_TOKEN="$token" \
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
4. Set up the VM and register the runner (above); confirm it is "Idle" under
   the repository's Actions → Runners.
5. Enable: `update private.observer_installations set fallback_capacity=1
   where organization='AGENTIC-OBSERVER26-runner-13';`
   `fallback_capacity` is the number of fallback VMs registered there; each
   VM hosts exactly one runner because its job cleanup removes every
   container.

Disable at any time with `fallback_capacity=0` (pending self-hosted jobs keep
their slot until they finish or expire), then `limactl stop observer-fallback`.
