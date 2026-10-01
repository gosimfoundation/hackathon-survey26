import { decryptCredential } from "./observer-model.ts";
import type { Rpc } from "./observer-model.ts";
import { GitHubApp, GitHubError } from "./observer-github.ts";

type LoadRow = {
  organization: string;
  approved_sha: string;
  over_limit: boolean;
};

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
): Promise<{ ok: boolean; error?: string }> {
  try {
    await app.dispatch(
      organization,
      "observer-" + job.kind + ".yml" as Parameters<GitHubApp["dispatch"]>[1],
      job.id,
      nonce,
      approvedSha,
    );
    await rpc("observer_mark_dispatched", { p_job: job.id });
    return { ok: true };
  } catch (error) {
    const code = error instanceof GitHubError ? error.code : "dispatch_unavailable";
    await rpc("observer_dispatch_error", { p_job: job.id, p_error: code });
    return { ok: false, error: code };
  }
}

export async function dispatchPending(rpc: Rpc, app: Pick<GitHubApp, "dispatch">, masterKey: string) {
  await rpc("observer_reconcile_jobs", {});
  await rpc("observer_reconcile_sessions", {});
  const jobs = await rpc("observer_pending_jobs", { p_limit: 10 });
  const outcomes = [];
  for (const job of jobs) {
    try {
      const nonce = await decryptCredential(job.encrypted_nonce, job.id + ":nonce", masterKey);
      const first = await tryDispatch(rpc, app, job, job.organization, nonce, job.workflow_sha);
      if (first.ok) {
        outcomes.push({ id: job.id, dispatched: true });
        continue;
      }
      if (!ORGANIZATION_FAILURES.has(first.error ?? "")) {
        outcomes.push({ id: job.id, dispatched: false, error: first.error });
        continue;
      }
      const candidates: LoadRow[] = await rpc("observer_organizations_by_load", {});
      const next = candidates.find((c) => c.organization !== job.organization && !c.over_limit);
      if (!next) {
        outcomes.push({ id: job.id, dispatched: false, error: first.error });
        continue;
      }
      // Moves the job and the owner's recorded placement atomically.
      await rpc("observer_failover_job", { p_job: job.id, p_organization: next.organization });
      const retried = await tryDispatch(rpc, app, job, next.organization, nonce, next.approved_sha);
      outcomes.push(
        retried.ok
          ? { id: job.id, dispatched: true, failover: next.organization }
          : { id: job.id, dispatched: false, error: retried.error },
      );
    } catch (error) {
      const code = error instanceof GitHubError ? error.code : "dispatch_unavailable";
      await rpc("observer_dispatch_error", { p_job: job.id, p_error: code });
      outcomes.push({ id: job.id, dispatched: false, error: code });
    }
  }
  return outcomes;
}
