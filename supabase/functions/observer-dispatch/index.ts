import { createClient } from "npm:@supabase/supabase-js@2";
import { dispatchPending } from "../_shared/observer-dispatch.ts";
import { databaseLocator, GitHubApp } from "../_shared/observer-github.ts";
import { ProxyError } from "../_shared/observer-model.ts";
import { scheduleRuns, scheduleScores } from "../_shared/observer-orchestrate.ts";
import { schedulePreparations } from "../_shared/observer-prepare.ts";
import { cleanupSealed, cleanupUploads } from "../_shared/observer-cleanup.ts";

const service = createClient(Deno.env.get("SUPABASE_URL") ?? "", Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "", {
  auth: { persistSession: false },
});
const rpc = async (name: string, args: Record<string, unknown>) => {
  const { data, error } = await service.rpc(name, args);
  if (error) throw new ProxyError(503, "dispatch_database_unavailable");
  return data;
};

Deno.serve({ port: Number(Deno.env.get("OBSERVER_LISTEN_PORT") ?? 8000) }, async (request) => {
  try {
    const expected = Deno.env.get("OBSERVER_DISPATCH_SECRET");
    if (!expected || expected.length < 40 || request.headers.get("authorization") !== "Bearer " + expected) {
      throw new ProxyError(401, "dispatcher_only");
    }
    if (request.method !== "POST") throw new ProxyError(405, "method_not_allowed");
    const configs = await rpc("observer_runner_configuration", {});
    const installations = Object.fromEntries(
      configs.map((c: { organization: string; installation_id: number }) => [c.organization, c.installation_id]),
    );
    const app = new GitHubApp(
      Deno.env.get("OBSERVER_GITHUB_APP_ID") ?? "",
      Deno.env.get("OBSERVER_GITHUB_APP_PEM") ?? "",
      installations,
      databaseLocator(rpc),
    );
    const masterKey = Deno.env.get("OBSERVER_KEY_ENCRYPTION_KEY") ?? "";
    await rpc("observer_reconcile_jobs", {});
    await rpc("observer_reconcile_sessions", {});
    await rpc("observer_reconcile_preparations", {});
    const prepared = await schedulePreparations({ rpc, app, masterKey, apiBase: Deno.env.get("SUPABASE_URL") ?? "" });
    const scheduled = await scheduleRuns({
      rpc,
      masterKey,
      apiBase: Deno.env.get("SUPABASE_URL") ?? "",
      ensureRepository: (user) => app.privateParticipantRepository(user),
    });
    // The rescore never holds up dispatching evaluations.
    const rescoring = await scheduleScores({ rpc, masterKey }).catch(() => [{ error: "rescore_unavailable" }]);
    const dispatched = await dispatchPending(rpc, app, masterKey);
    const cleaned = await cleanupUploads(rpc, async (path) => {
      const { error } = await service.storage.from("observer-staging").remove([path]);
      if (error) throw new ProxyError(503, "temporary_cleanup_failed");
    });
    const sealed = await cleanupSealed(rpc, async (paths) => {
      const { error } = await service.storage.from("observer-staging").remove(paths);
      if (error) throw new ProxyError(503, "temporary_cleanup_failed");
    }).catch(() => 0);
    const data = { prepared, scheduled, rescoring, dispatched, cleaned, sealed };
    return Response.json({ data }, { headers: { "cache-control": "no-store" } });
  } catch (error) {
    return Response.json({ error: error instanceof ProxyError ? error.code : "dispatch_unavailable" }, {
      status: error instanceof ProxyError ? error.status : 503,
    });
  }
});
