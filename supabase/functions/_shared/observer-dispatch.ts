import { decryptCredential } from "./observer-model.ts";
import type { Rpc } from "./observer-model.ts";
import { GitHubApp, GitHubError } from "./observer-github.ts";

type LoadRow = {
  organization: string;
  approved_sha: string;
  over_limit: boolean;
};

type PendingJob = {
  id: string;
  kind: string;
  organization: string;
  workflow_sha: string;
  encrypted_nonce: string;
  runner?: "github-hosted" | "self-hosted";
  // Set by observer_pending_jobs while a self-hosted fallback slot is free.
  fallback?: "stalled" | "over_limit" | null;
};

type Outcome = { id: string; dispatched: boolean; error?: string; failover?: string; fallback?: string };

// Organization-level failures (missing/suspended installation, rejected or
// quota-exhausted API calls, unapproved control repository) cannot fix
// themselves within the job lease: the job moves to the next best
// organization instead of retrying the broken one until expiry.
const ORGANIZATION_FAILURES = new Set([
  "organization_not_installed",
  "installation_identity_mismatch",
  "control_repository_must_be_private",
  "control_revision_not_approved",
  "github_not_found",
  "github_request_failed",
]);

async function tryDispatch(
  rpc: Rpc,
  app: Pick<GitHubApp, "dispatch">,
  job: { id: string; kind: string },
  organization: string,
  nonce: string,
  approvedSha: string,
  selfHosted = false,
): Promise<{ ok: boolean; error?: string }> {
  try {
    const workflow = "observer-" + job.kind + ".yml" as Parameters<GitHubApp["dispatch"]>[1];
    if (selfHosted) await app.dispatch(organization, workflow, job.id, nonce, approvedSha, "self-hosted");
    else await app.dispatch(organization, workflow, job.id, nonce, approvedSha);
    await rpc("observer_mark_dispatched", { p_job: job.id });
    return { ok: true };
  } catch (error) {
    const code = error instanceof GitHubError ? error.code : "dispatch_unavailable";
    await rpc("observer_dispatch_error", { p_job: job.id, p_error: code });
    return { ok: false, error: code };
  }
}

// Last resort: the organizer's self-hosted fallback runner. Returns null when no
// fallback slot is free, so the caller keeps its GitHub-hosted outcome.
async function tryFallback(
  rpc: Rpc,
  app: Pick<GitHubApp, "dispatch">,
  job: PendingJob,
  nonce: string,
): Promise<Outcome | null> {
  let target: { organization: string; approved_sha: string };
  try {
    target = await rpc("observer_fallback_job", { p_job: job.id });
  } catch {
    return null;
  }
  if (!target?.organization) return null;
  const result = await tryDispatch(rpc, app, job, target.organization, nonce, target.approved_sha, true);
  return result.ok
    ? { id: job.id, dispatched: true, fallback: target.organization }
    : { id: job.id, dispatched: false, error: result.error };
}

export async function dispatchPending(rpc: Rpc, app: Pick<GitHubApp, "dispatch">, masterKey: string) {
  await rpc("observer_reconcile_jobs", {});
  await rpc("observer_reconcile_sessions", {});
  const jobs: PendingJob[] = await rpc("observer_pending_jobs", { p_limit: 10 });
  const outcomes: Outcome[] = [];
  for (const job of jobs) {
    try {
      const nonce = await decryptCredential(job.encrypted_nonce, job.id + ":nonce", masterKey);
      if (job.fallback) {
        const moved = await tryFallback(rpc, app, job, nonce);
        if (moved) {
          outcomes.push(moved);
          continue;
        }
        // A stalled job was already dispatched three times to its organization.
        if (job.fallback === "stalled") {
          outcomes.push({ id: job.id, dispatched: false, error: "github_run_not_started" });
          continue;
        }
      }
      const selfHosted = job.runner === "self-hosted";
      const first = await tryDispatch(rpc, app, job, job.organization, nonce, job.workflow_sha, selfHosted);
      if (first.ok) {
        outcomes.push({ id: job.id, dispatched: true });
        continue;
      }
      if (selfHosted || !ORGANIZATION_FAILURES.has(first.error ?? "")) {
        outcomes.push({ id: job.id, dispatched: false, error: first.error });
        continue;
      }
      const candidates: LoadRow[] = await rpc("observer_organizations_by_load", {});
      const next = candidates.find((c) => c.organization !== job.organization && !c.over_limit);
      let error = first.error;
      if (next) {
        // Moves the job and the owner's recorded placement atomically.
        await rpc("observer_failover_job", { p_job: job.id, p_organization: next.organization });
        const retried = await tryDispatch(rpc, app, job, next.organization, nonce, next.approved_sha);
        if (retried.ok) {
          outcomes.push({ id: job.id, dispatched: true, failover: next.organization });
          continue;
        }
        error = retried.error;
      }
      // No GitHub-hosted organization can take the job right now.
      const moved = ORGANIZATION_FAILURES.has(error ?? "") ? await tryFallback(rpc, app, job, nonce) : null;
      outcomes.push(moved ?? { id: job.id, dispatched: false, error });
    } catch (error) {
      const code = error instanceof GitHubError ? error.code : "dispatch_unavailable";
      await rpc("observer_dispatch_error", { p_job: job.id, p_error: code });
      outcomes.push({ id: job.id, dispatched: false, error: code });
    }
  }
  return outcomes;
}
