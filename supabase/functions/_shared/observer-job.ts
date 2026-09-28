import { boundedJson, decryptCredential, ProxyError } from "./observer-model.ts";
import type { Rpc } from "./observer-model.ts";
import { RUNNER_ORGANIZATION_PATTERN, verifyWorkflowIdentity } from "./observer-github.ts";
import type { WorkflowIdentity } from "./observer-github.ts";
import { AGENT_LOG_BYTES } from "./observer-agent-log.ts";

const PARTICIPANT_REPOSITORY = new RegExp("^" + RUNNER_ORGANIZATION_PATTERN + "\\/participant-[0-9a-f]{32}$");

export type JobDependencies = {
  rpc: Rpc;
  masterKey: string;
  verify?: typeof verifyWorkflowIdentity;
  repositoryCredentials?: (user: string, kind: "prepare" | "engine") => Promise<{ full_name: string; token: string }>;
  archiveDownload?: (reference: string, privateOnly: boolean) => Promise<string>;
  scenarioDownload?: (path: string) => Promise<string>;
  sourceDownload?: (path: string) => Promise<string>;
  /** Stores the scrubbed participant log beside the run's private result. */
  storeAgentLog?: (run: string, log: Uint8Array) => Promise<void>;
};

const RECEIPT_BODY_LIMIT = 1100000;
const AGENT_LOG_BODY_LIMIT = 3 * 1024 * 1024;

function validateArtifactUpload(value: unknown, id: string, filename: string) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new ProxyError(503, "invalid_job_payload");
  const upload = value as Record<string, unknown>;
  if (Object.keys(upload).join(",") === "kind" && upload.kind === "github") return;
  if (
    Object.keys(upload).sort().join(",") !== "path,url" || typeof upload.url !== "string" ||
    typeof upload.path !== "string" ||
    !new RegExp("^[0-9a-f-]{36}/" + id + "/" + filename + "\\.zip$").test(upload.path)
  ) {
    throw new ProxyError(503, "invalid_job_payload");
  }
  let url: URL;
  try {
    url = new URL(upload.url);
  } catch {
    throw new ProxyError(503, "invalid_job_payload");
  }
  if (url.protocol !== "https:" || url.username || url.password || url.hash || url.port) {
    throw new ProxyError(503, "invalid_job_payload");
  }
}

// Payload classes are deliberately separate. An executor can never receive the
// engine's scenario bundle, a service key, or repository installation credentials.
export function validateJobPayload(payload: unknown, expected: WorkflowIdentity, job: string) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new ProxyError(503, "invalid_job_payload");
  }
  const value = payload as Record<string, unknown>;
  const kind = expected.workflow.slice("observer-".length, -".yml".length);
  const fields: Record<string, string[]> = {
    execute: [
      "kind",
      "job_id",
      "run_id",
      "archive_url",
      "source_digest",
      "manifest",
      "session_url",
      "run_credential",
      "model_base_url",
    ],
    engine: [
      "kind",
      "job_id",
      "run_id",
      "scenario_url",
      "scenario_digest",
      "session_url",
      "run_credential",
      "runtime_seconds",
      "artifact_upload",
      "instance",
      "archive_url",
      "colocated",
    ],
    prepare: [
      "kind",
      "job_id",
      "revision_id",
      "archive_url",
      "source_digest",
      "repository",
      "artifact_upload",
      "model_base_url",
      "run_credential",
      "model",
      "gameplay",
    ],
  };
  if (
    !fields[kind] || value.kind !== kind || value.job_id !== job ||
    Object.keys(value).some((key) => !fields[kind].includes(key))
  ) throw new ProxyError(503, "invalid_job_payload");
  const uuid = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/;
  const hash = /^[0-9a-f]{64}$/;
  const string = (name: string, pattern?: RegExp) => {
    const field = value[name];
    if (typeof field !== "string" || !field || (pattern && !pattern.test(field))) {
      throw new ProxyError(503, "invalid_job_payload");
    }
    return field;
  };
  const url = (name: string) => {
    let parsed: URL;
    try {
      parsed = new URL(string(name));
    } catch {
      throw new ProxyError(503, "invalid_job_payload");
    }
    if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.hash || parsed.port) {
      throw new ProxyError(503, "invalid_job_payload");
    }
  };
  if (kind === "execute" || kind === "engine") {
    const run = string("run_id", uuid);
    string("run_credential", new RegExp("^obs_" + run + "\\.[A-Za-z0-9_-]{40,100}$"));
    url("session_url");
  }
  const projectManifest = (manifest: Record<string, unknown> | null) => {
    if (
      !manifest || typeof manifest !== "object" || Array.isArray(manifest) ||
      manifest.schema_version !== "observer-project-v1" ||
      typeof manifest.image !== "string" ||
      !/^[a-zA-Z0-9][a-zA-Z0-9._/:-]*@sha256:[0-9a-f]{64}$/.test(manifest.image) ||
      !Array.isArray(manifest.run) || !manifest.run.length ||
      !manifest.run.every((arg) => typeof arg === "string" && arg.length > 0 && !arg.includes("\0"))
    ) {
      throw new ProxyError(503, "invalid_job_payload");
    }
  };
  if (kind === "execute") {
    url("archive_url");
    url("model_base_url");
    string("source_digest", hash);
    projectManifest(value.manifest as Record<string, unknown> | null);
  }
  if (kind === "engine" && value.colocated !== undefined) {
    // A public-scenario run whose participant container starts inside the
    // engine job; it carries the execute job's fields under "colocated".
    const run = string("run_id", uuid);
    url("archive_url");
    const colocated = value.colocated as Record<string, unknown> | null;
    if (
      !colocated || typeof colocated !== "object" || Array.isArray(colocated) || value.instance !== undefined ||
      Object.keys(colocated).sort().join(",") !== "manifest,model_base_url,run_credential,source_digest" ||
      typeof colocated.run_credential !== "string" ||
      !new RegExp("^obs_" + run + "\\.[A-Za-z0-9_-]{40,100}$").test(colocated.run_credential) ||
      colocated.run_credential === value.run_credential ||
      typeof colocated.source_digest !== "string" || !hash.test(colocated.source_digest) ||
      typeof colocated.model_base_url !== "string" || !colocated.model_base_url.startsWith("https://")
    ) {
      throw new ProxyError(503, "invalid_job_payload");
    }
    projectManifest(colocated.manifest as Record<string, unknown> | null);
  } else if (kind === "engine" && value.archive_url !== undefined) {
    throw new ProxyError(503, "invalid_job_payload");
  }
  if (kind === "engine") {
    url("scenario_url");
    string("scenario_digest", hash);
    if (
      !Number.isInteger(value.runtime_seconds) || Number(value.runtime_seconds) < 10 ||
      Number(value.runtime_seconds) > 18000
    ) {
      throw new ProxyError(503, "invalid_job_payload");
    }
    validateArtifactUpload(value.artifact_upload, string("run_id", uuid), "result");
    if (value.instance !== undefined) {
      const instance = value.instance as Record<string, unknown>;
      if (
        !instance || typeof instance !== "object" || Array.isArray(instance) ||
        Object.keys(instance).sort().join(",") !== "bundle_digest,max_candidates,profile,profile_id,seed" ||
        typeof instance.seed !== "string" || !hash.test(instance.seed) ||
        typeof instance.profile_id !== "string" || !uuid.test(instance.profile_id) ||
        instance.bundle_digest !== value.scenario_digest || instance.max_candidates !== 32 ||
        !instance.profile || typeof instance.profile !== "object" || Array.isArray(instance.profile) ||
        JSON.stringify(instance.profile).length > 65536
      ) {
        throw new ProxyError(503, "invalid_job_payload");
      }
    }
  }
  if (kind === "prepare") {
    const revision = string("revision_id", uuid);
    url("archive_url");
    // A repository upload has an immutable Git commit; a ZIP additionally has
    // its uploaded archive digest. The preparation worker calculates source hash.
    if (value.source_digest !== null && value.source_digest !== undefined) string("source_digest", hash);
    const repository = value.repository as Record<string, unknown> | null;
    if (
      !repository || typeof repository !== "object" || Object.keys(repository).sort().join(",") !== "full_name,token" ||
      typeof repository.full_name !== "string" ||
      !PARTICIPANT_REPOSITORY.test(repository.full_name) ||
      !repository.full_name.startsWith(expected.organization + "/") ||
      typeof repository.token !== "string" || !repository.token || /[\r\n\0]/.test(repository.token)
    ) {
      throw new ProxyError(503, "invalid_job_payload");
    }
    validateArtifactUpload(value.artifact_upload, revision, "preview");
    if (value.gameplay !== undefined && value.gameplay !== "v4") throw new ProxyError(503, "invalid_job_payload");
    if (value.model !== undefined || value.model_base_url !== undefined || value.run_credential !== undefined) {
      string("model");
      url("model_base_url");
      string("run_credential", /^obs_[0-9a-f-]{36}\.[A-Za-z0-9_-]{40,100}$/);
    }
  }
  return value;
}

export async function jobRequest(request: Request, deps: JobDependencies) {
  const bearer = /^Bearer ([A-Za-z0-9_.-]+)$/.exec(request.headers.get("authorization") ?? "");
  if (!bearer) throw new ProxyError(401, "workflow_identity_required");
  const body = await boundedJson(request, AGENT_LOG_BODY_LIMIT);
  if (
    !body || typeof body !== "object" || Array.isArray(body) ||
    typeof body.job_id !== "string" || !/^[0-9a-f-]{36}$/.test(body.job_id) ||
    !["claim", "complete", "artifact_repository", "agent_log"].includes(body.action)
  ) throw new ProxyError(400, "invalid_job_request");
  // Only the participant log may use the larger request size.
  if (body.action !== "agent_log" && JSON.stringify(body).length > RECEIPT_BODY_LIMIT) {
    throw new ProxyError(413, "body_too_large");
  }
  const identity = await deps.rpc("observer_job_identity", { p_job: body.job_id });
  if (!identity) throw new ProxyError(404, "job_unavailable");
  const expected: WorkflowIdentity = {
    ...identity,
    runId: identity.runId ?? undefined,
    runAttempt: identity.runAttempt ?? undefined,
  };
  const verified = await (deps.verify ?? verifyWorkflowIdentity)(bearer[1], expected);
  const repository = async () => {
    if (expected.workflow === "observer-execute.yml" || !deps.repositoryCredentials) {
      throw new ProxyError(403, "artifact_access_denied");
    }
    const target = await deps.rpc("observer_job_artifact_target", {
      p_job: body.job_id,
      p_github_run: verified.runId,
      p_attempt: verified.runAttempt,
    });
    if (!target?.user_id || !target?.artifact_id || !["prepare", "engine"].includes(target.kind)) {
      throw new ProxyError(403, "artifact_access_denied");
    }
    return {
      ...await deps.repositoryCredentials(target.user_id, target.kind),
      artifact_id: target.artifact_id,
      kind: target.kind,
    };
  };
  const claimedInput = async () => {
    if (typeof body.nonce !== "string" || !/^[A-Za-z0-9_-]{40,100}$/.test(body.nonce)) {
      throw new ProxyError(400, "invalid_job_nonce");
    }
    // Idempotent for the GitHub run that already claimed the job; any other
    // run, nonce, workflow or finished job is refused by the database.
    const ciphertext = await deps.rpc("observer_claim_job", {
      p_job: body.job_id,
      p_nonce: body.nonce,
      p_github_run: verified.runId,
      p_attempt: verified.runAttempt,
      p_repository: expected.repositoryId,
      p_owner: expected.organizationId,
      p_sha: expected.approvedSha,
    });
    return await decryptCredential(ciphertext, body.job_id, deps.masterKey);
  };
  if (body.action === "artifact_repository") return await repository();
  if (body.action === "agent_log") {
    // Only the executor has participant output. The run is taken from the
    // claimed job's own encrypted input, never from the request.
    if (expected.workflow !== "observer-execute.yml" || !deps.storeAgentLog) {
      throw new ProxyError(403, "agent_log_denied");
    }
    if (typeof body.log !== "string" || body.log.length > Math.ceil(AGENT_LOG_BYTES / 3) * 4) {
      throw new ProxyError(400, "invalid_agent_log");
    }
    let input;
    try {
      input = JSON.parse(await claimedInput());
    } catch (error) {
      if (error instanceof ProxyError) throw error;
      throw new ProxyError(503, "invalid_job_payload");
    }
    const run = input?.run_id;
    if (
      input?.kind !== "execute" || input?.job_id !== body.job_id || typeof run !== "string" ||
      !/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(run)
    ) throw new ProxyError(403, "agent_log_denied");
    let raw: Uint8Array;
    try {
      raw = Uint8Array.from(atob(body.log), (c) => c.charCodeAt(0));
    } catch {
      throw new ProxyError(400, "invalid_agent_log");
    }
    if (raw.length > AGENT_LOG_BYTES) throw new ProxyError(400, "invalid_agent_log");
    // Defense in depth: the runner already scrubbed its own capability.
    let text = new TextDecoder().decode(raw);
    if (typeof input.run_credential === "string" && input.run_credential) {
      text = text.replaceAll(input.run_credential, "[REDACTED]");
    }
    await deps.storeAgentLog(run, new TextEncoder().encode(text));
    return { accepted: true };
  }
  if (body.action === "claim") {
    const cleartext = await claimedInput();
    let parsed;
    try {
      parsed = JSON.parse(cleartext);
    } catch {
      throw new ProxyError(503, "invalid_job_payload");
    }
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      if (parsed.archive_storage_ref !== undefined) {
        const ref = parsed.archive_storage_ref;
        if (
          parsed.kind !== "prepare" || parsed.archive_url !== undefined || parsed.archive_ref !== undefined ||
          !deps.sourceDownload || !ref || typeof ref !== "object" || Array.isArray(ref) ||
          Object.keys(ref).sort().join(",") !== "bucket,path" || ref.bucket !== "observer-staging" ||
          typeof ref.path !== "string" || !/^[0-9a-f-]{36}\/[0-9a-f-]{36}\/source[.]zip$/.test(ref.path)
        ) {
          throw new ProxyError(503, "invalid_job_payload");
        }
        parsed.archive_url = await deps.sourceDownload(ref.path);
        delete parsed.archive_storage_ref;
      }
      if (parsed.scenario_ref !== undefined) {
        const ref = parsed.scenario_ref;
        if (
          parsed.kind !== "engine" || parsed.scenario_url !== undefined || !deps.scenarioDownload ||
          !ref || typeof ref !== "object" || Array.isArray(ref) ||
          Object.keys(ref).sort().join(",") !== "bucket,path" || ref.bucket !== "observer-scenarios" ||
          typeof ref.path !== "string" || !/^[A-Za-z0-9_/-]+[.]zip$/.test(ref.path)
        ) {
          throw new ProxyError(503, "invalid_job_payload");
        }
        parsed.scenario_url = await deps.scenarioDownload(ref.path);
        delete parsed.scenario_ref;
      }
      if (parsed.archive_ref !== undefined) {
        if (parsed.archive_url !== undefined || !deps.archiveDownload || typeof parsed.archive_ref !== "string") {
          throw new ProxyError(503, "invalid_job_payload");
        }
        parsed.archive_url = await deps.archiveDownload(parsed.archive_ref, parsed.kind !== "prepare");
        delete parsed.archive_ref;
      }
      if (parsed.kind === "prepare" && parsed.repository && !parsed.repository.token) {
        const fresh = await repository();
        if (fresh.full_name !== parsed.repository.full_name || fresh.artifact_id !== parsed.revision_id) {
          throw new ProxyError(503, "invalid_job_payload");
        }
        parsed.repository = { full_name: fresh.full_name, token: fresh.token };
      }
    }
    return validateJobPayload(parsed, expected, body.job_id);
  }
  await deps.rpc("observer_finish_job", {
    p_job: body.job_id,
    p_github_run: verified.runId,
    p_attempt: verified.runAttempt,
    p_result: body.result,
    p_error: typeof body.error === "string" ? body.error : "",
  });
  return { accepted: true };
}
