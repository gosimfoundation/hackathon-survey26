import { createClient } from "npm:@supabase/supabase-js@2";
import { jobRequest } from "../_shared/observer-job.ts";
import { ProxyError } from "../_shared/observer-model.ts";
import { GitHubError } from "../_shared/observer-github.ts";
import { artifactDownload, configuredApp } from "../_shared/observer-app.ts";
import { agentLogPath } from "../_shared/observer-agent-log.ts";
import { singleFileZip } from "../_shared/observer-zip.ts";

const service = createClient(Deno.env.get("SUPABASE_URL") ?? "", Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "", {
  auth: { persistSession: false },
});
const known = new Set([
  "job_unavailable",
  "job_identity_mismatch",
  "job_already_claimed",
  "invalid_job_result",
  "job_result_conflict",
  "job_not_claimed",
  "artifact_access_denied",
]);

Deno.serve({ port: Number(Deno.env.get("OBSERVER_LISTEN_PORT") ?? 8000) }, async (request) => {
  try {
    if (request.method !== "POST") throw new ProxyError(405, "method_not_allowed");
    const data = await jobRequest(request, {
      masterKey: Deno.env.get("OBSERVER_KEY_ENCRYPTION_KEY") ?? "",
      repositoryCredentials: async (user, kind) => {
        const app = await configuredApp(service);
        const repo = await app.privateParticipantRepository(user);
        return { full_name: repo.full_name, token: await app.snapshotWriteToken(user, kind === "prepare") };
      },
      archiveDownload: async (reference, privateOnly) =>
        artifactDownload(await configuredApp(service), reference, privateOnly),
      scenarioDownload: async (path) => {
        const { data, error } = await service.storage.from("observer-scenarios").createSignedUrl(path, 600);
        if (error || !data?.signedUrl) throw new ProxyError(503, "scenario_download_unavailable");
        return data.signedUrl;
      },
      sourceDownload: async (path) => {
        const { data, error } = await service.storage.from("observer-staging").createSignedUrl(path, 600);
        if (error || !data?.signedUrl) throw new ProxyError(503, "source_download_unavailable");
        return data.signedUrl;
      },
      storeAgentLog: async (run, log) => {
        // The staging bucket only accepts ZIP and CSV objects.
        const { error } = await service.storage.from("observer-staging").upload(
          agentLogPath(run),
          await singleFileZip("agent.log", log),
          { contentType: "application/zip", upsert: true },
        );
        if (error) throw new ProxyError(503, "agent_log_unavailable");
      },
      rpc: async (name, args) => {
        const { data, error } = await service.rpc(name, args);
        if (error) {
          throw new ProxyError(
            known.has(error.message) ? 409 : 503,
            known.has(error.message) ? error.message : "job_service_unavailable",
          );
        }
        return data;
      },
    });
    return Response.json({ data }, { headers: { "cache-control": "no-store" } });
  } catch (error) {
    const code = error instanceof ProxyError || error instanceof GitHubError ? error.code : "job_service_unavailable";
    const status = error instanceof ProxyError || error instanceof GitHubError ? error.status || 503 : 503;
    return Response.json({ error: code }, { status, headers: { "cache-control": "no-store" } });
  }
});
