import { encryptCredential, ProxyError } from "./observer-model.ts";
import type { Rpc } from "./observer-model.ts";
import { databaseLocator, GitHubError, placement } from "./observer-github.ts";

export interface RunScheduler {
  rpc: Rpc;
  masterKey: string;
  apiBase: string;
  ensureRepository: (user: string) => Promise<unknown>;
}

export function randomCapability() {
  return btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))
    .replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

export async function scheduleRuns(deps: RunScheduler) {
  const base = new URL(deps.apiBase);
  if (base.protocol !== "https:" || base.username || base.password || base.search || base.hash || base.port) {
    throw new ProxyError(503, "invalid_platform_url");
  }
  const api = base.href.replace(/\/$/, "") + "/functions/v1/";
  // A partially configured deployment does not consume participant retry limits.
  const installations = await deps.rpc("observer_runner_configuration", {});
  if (!installations.length) return [];
  const enabled = new Set(installations.map((i: { organization: string }) => i.organization));
  const runs = await deps.rpc("observer_pending_runs", { p_limit: 5 });
  const outcomes = [];
  for (const run of runs) {
    try {
      const { organization } = await placement(run.user_id, databaseLocator(deps.rpc));
      if (!enabled.has(organization)) throw new GitHubError("runner_not_configured");
      // Local sessions need a private result repository too. Provision it before
      // opening a capability; a GitHub failure cannot leave a half-started run.
      await deps.ensureRepository(run.user_id);
      const instance = await deps.rpc("observer_instance_input", { p_run: run.id });
      // Public scenarios run the participant container inside the engine job:
      // the same step-by-step protocol, without a database round trip per step.
      const colocated = run.mode === "project" && !instance &&
        await deps.rpc("observer_run_colocated", { p_run: run.id }) === true;
      const participant = randomCapability(), engine = randomCapability();
      const jobs = [];
      const encodeJob = async (kind: string, input: Record<string, unknown>) => {
        const id = crypto.randomUUID(), nonce = randomCapability();
        return {
          id,
          kind,
          nonce,
          encrypted_nonce: await encryptCredential(nonce, id + ":nonce", deps.masterKey),
          encrypted_input: await encryptCredential(JSON.stringify({ ...input, kind, job_id: id }), id, deps.masterKey),
        };
      };
      jobs.push(
        await encodeJob("engine", {
          run_id: run.id,
          run_credential: "obs_" + run.id + "." + engine,
          session_url: api + "observer-session",
          scenario_ref: { bucket: "observer-scenarios", path: run.storage_path },
          scenario_digest: run.scenario_digest,
          runtime_seconds: run.runtime_seconds,
          artifact_upload: { kind: "github" },
          ...(instance ? { instance } : {}),
          ...(colocated
            ? {
              archive_ref: run.archive_ref,
              colocated: {
                run_credential: "obs_" + run.id + "." + participant,
                model_base_url: api + "observer-model/v1",
                source_digest: run.materialized_digest,
                manifest: run.manifest,
              },
            }
            : {}),
        }),
      );
      if (run.mode === "project" && !colocated) {
        jobs.push(
          await encodeJob("execute", {
            run_id: run.id,
            run_credential: "obs_" + run.id + "." + participant,
            session_url: api + "observer-session",
            model_base_url: api + "observer-model/v1",
            archive_ref: run.archive_ref,
            source_digest: run.materialized_digest,
            manifest: run.manifest,
          }),
        );
      }
      const local = run.mode === "local"
        ? await encryptCredential("obs_" + run.id + "." + participant, run.id + ":local", deps.masterKey)
        : null;
      // Session, encrypted local handoff and all jobs commit together. A lost
      // response is retried with the same lease and cannot start a second run.
      await deps.rpc("observer_schedule_run", {
        p_run: run.id,
        p_lease: run.lease,
        p_organization: organization,
        p_participant_token: participant,
        p_engine_token: engine,
        p_local_credential: local,
        p_jobs: jobs,
      });
      outcomes.push({ id: run.id, scheduled: true });
    } catch (error) {
      const code = error instanceof GitHubError ? error.code : "schedule_unavailable";
      await deps.rpc("observer_run_schedule_error", { p_run: run.id, p_lease: run.lease, p_error: code });
      outcomes.push({ id: run.id, scheduled: false, error: code });
    }
  }
  return outcomes;
}
