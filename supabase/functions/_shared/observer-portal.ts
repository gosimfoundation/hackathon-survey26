import { fulfillPersonalModel } from "./observer-personal-model.ts";
import { sendModelBroadcast } from "./observer-model-broadcast.ts";
import { boundedJson, decryptCredential, encryptCredential, ProxyError } from "./observer-model.ts";
import { publicBase, type Resolver } from "./observer-public-base.ts";
import type { SupabaseClient } from "npm:@supabase/supabase-js@2";
import { sourceRepository } from "./observer-github.ts";
import { fetchArchive, resultWithAgentLog } from "./observer-agent-log.ts";

type Dependencies = {
  user: SupabaseClient;
  service: SupabaseClient;
  userId: string;
  masterKey: string;
  modelBases: string[];
  httpBases: string[];
  /** DNS lookups for participant bases; tests replace it. */
  resolve?: Resolver | null;
  artifactDownload?: (reference: string) => Promise<string>;
  /** Fetches signed result archives; tests replace it. */
  fetchArchive?: typeof fetch;
};
const known = new Set([
  "team_required",
  "model_request_already_received",
  "request_id_conflict",
  "invalid_team_model",
  "invalid_team_model_mode",
  "competition_project_required",
  "projects_not_enabled",
  "invalid_repository_url",
  "invalid_upload_path",
  "preparation_limit",
  "preparation_daily_limit",
  "revision_not_found",
  "revision_not_ready",
  "stale_approval",
  "phase_closed",
  "local_sessions_disabled",
  "revision_not_approved",
  "revision_already_evaluated",
  "revision_withdrawn",
  "revision_not_withdrawable",
  "daily_limit",
  "batch_already_active",
  "no_scenarios",
  "run_not_found",
  "csv_does_not_match_session",
  "session_not_finished",
  "provider_limit",
  "provider_not_found",
  "invalid_provider",
  "upload_limit",
  "account_banned",
  "diagnostics_not_found",
  "final_phase_invalid",
  "final_version_locked",
]);
function failure(error: { message: string } | null) {
  if (error) throw new ProxyError(400, known.has(error.message) ? error.message : "portal_request_failed");
}
function uuid(value: unknown): string {
  if (typeof value !== "string" || !/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(value)) {
    throw new ProxyError(400, "invalid_identifier");
  }
  return value;
}
function text(value: unknown, max: number, empty = false): string {
  if (typeof value !== "string" || value.length > max || (!empty && !value.trim())) {
    throw new ProxyError(400, "invalid_field");
  }
  return value.trim();
}
/** Recognition hint only: never more than the last four characters of a long key. */
export function keyHint(key: string): string {
  return key.length >= 16 ? key.slice(-4) : "";
}

export async function portalRequest(request: Request, d: Dependencies): Promise<unknown> {
  const body = await boundedJson(request, 98304);
  if (!body || typeof body !== "object" || Array.isArray(body)) throw new ProxyError(400, "invalid_request");
  const userRpc = async (name: string, args: Record<string, unknown> = {}) => {
    const { data, error } = await d.user.rpc(name, args);
    failure(error);
    return data;
  };
  const serviceRpc = async (name: string, args: Record<string, unknown>) => {
    const { data, error } = await d.service.rpc(name, args);
    failure(error);
    return data;
  };
  const staging = d.service.storage.from("observer-staging");
  switch (body.action) {
    // Relay mode only: the open page answers its team's model calls with a key
    // that exists only in that page. The routes are empty in stored mode.
    case "model_routes":
      return await userRpc("observer_personal_model_routes");
    case "personal_model":
      return await fulfillPersonalModel(body, d.userId, {
        rpc: serviceRpc,
        fetch,
        trustedBases: new Set(d.modelBases),
        resolve: d.resolve,
        send: (topic, event, payload) => sendModelBroadcast(d.service, topic, event, payload),
      });
    case "diagnostics":
      return await userRpc("observer_diagnostics", {
        p_revision: body.revision_id ? uuid(body.revision_id) : null,
        p_run: body.run_id ? uuid(body.run_id) : null,
      });
    case "local_access": {
      const run = uuid(body.run_id);
      const access = await serviceRpc("observer_local_access", { p_run: run, p_user: d.userId });
      if (!access) throw new ProxyError(409, "local_session_not_ready");
      const token = await decryptCredential(access.encrypted_credential, run + ":local", d.masterKey);
      if (!new RegExp("^obs_" + run + "\\.[A-Za-z0-9_-]{40,100}$").test(token)) {
        throw new ProxyError(503, "invalid_local_session");
      }
      return { run_id: run, credential: token, expires_at: access.expires_at };
    }
    case "list": {
      const queries = [
        d.user.from("observer_phase_settings").select("*,phases(id,slug,name_en,name_zh,starts_at,ends_at,is_active)"),
        d.user.from("observer_projects").select("*,observer_revisions(*,observer_evidence(*))").order("created_at", {
          ascending: false,
        }).limit(100),
        d.user.from("observer_batches").select("*,observer_runs(*)").eq("purpose", "formal").order("created_at", {
          ascending: false,
        }).limit(
          50,
        ),
      ];
      const results = await Promise.all(queries);
      results.forEach((r) => failure(r.error));
      // Remaining evaluations are informational; the database enforces the limit.
      const quota = await d.user.rpc("observer_evaluation_quota");
      const finals = await d.user.rpc("observer_final_versions");
      return {
        phases: results[0].data,
        projects: results[1].data,
        batches: results[2].data,
        quota: quota.error ? null : quota.data,
        providers: await userRpc("observer_list_providers"),
        team_model: await userRpc("observer_team_model"),
        model_bases: d.modelBases,
        // Informational like the quota; an older database without the RPC shows no choice.
        final_versions: finals.error ? null : finals.data,
      };
    }
    case "upload": {
      const id = crypto.randomUUID();
      const path = await serviceRpc("observer_reserve_upload", { p_user: d.userId, p_id: id, p_purpose: body.purpose });
      const { data, error } = await staging.createSignedUploadUrl(path, { upsert: false });
      failure(error);
      return { id, path, token: data!.token };
    }
    case "submit_repository": {
      let repository: string;
      try {
        repository = sourceRepository(text(body.url, 1024));
      } catch {
        throw new ProxyError(400, "invalid_repository_url");
      }
      return {
        revision_id: await userRpc("observer_create_project", {
          p_title: text(body.title, 100),
          p_source_kind: "repository",
          p_source_location: "https://github.com/" + repository,
        }),
      };
    }
    case "submit_zip": {
      const id = uuid(body.upload_id);
      const path = await serviceRpc("observer_upload_access", { p_user: d.userId, p_id: id, p_purpose: "source" });
      if (!path) throw new ProxyError(404, "upload_not_found");
      // Source validation is done by the preparation job. Check completion here
      // without exposing storage credentials or accepting a browser-supplied hash.
      const { data: objects, error } = await staging.list(path.slice(0, path.lastIndexOf("/")), {
        search: "source.zip",
        limit: 2,
      });
      failure(error);
      if (
        !objects?.some((o) =>
          o.name === "source.zip" && Number(o.metadata?.size) > 0 && Number(o.metadata?.size) <= 52428800
        )
      ) {
        throw new ProxyError(400, "upload_not_finished");
      }
      const revision = await userRpc("observer_submit_zip", { p_title: text(body.title, 100), p_upload: id });
      return { revision_id: revision };
    }
    case "approve":
      await userRpc("observer_approve_revision", {
        p_revision: uuid(body.revision_id),
        p_digest: text(body.digest, 64),
      });
      return { accepted: true };
    case "evaluate":
      return {
        batch_id: await userRpc("observer_create_batch", {
          p_phase: uuid(body.phase_id),
          p_revision: body.revision_id ? uuid(body.revision_id) : null,
          // Another evaluation of an already evaluated version is an explicit choice.
          ...(body.confirm_repeat === true ? { p_confirm_repeat: true } : {}),
        }),
      };
    // The team's final version for an open formal phase; revision_id null clears
    // the choice. The database checks membership, the version and the deadline.
    case "set_final_version":
      return {
        final_version: await userRpc("observer_set_final_version", {
          p_phase: uuid(body.phase_id),
          p_revision: body.revision_id == null ? null : uuid(body.revision_id),
        }),
      };
    case "withdraw":
      await userRpc("observer_withdraw_revision", { p_revision: uuid(body.revision_id) });
      return { accepted: true };
    case "evidence": {
      const url = text(body.code_url, 1000, true);
      if (url) {
        let parsed: URL;
        try {
          parsed = new URL(url);
        } catch {
          throw new ProxyError(400, "invalid_code_url");
        }
        if (parsed.protocol !== "https:" || parsed.username || parsed.password) {
          throw new ProxyError(400, "invalid_code_url");
        }
      }
      await userRpc("observer_save_evidence", {
        p_revision: uuid(body.revision_id),
        p_notes: text(body.notes, 8000, true),
        p_code_url: url,
      });
      return { accepted: true };
    }
    case "save_provider":
      // The former multi-provider settings stay retired; teams use save_team_model.
      throw new ProxyError(410, "ephemeral_credentials_required");
    case "save_team_model": {
      let key = typeof body.key === "string" ? body.key.trim() : "";
      body.key = "";
      // Any public HTTPS base (or an exact organizer-configured one); never HTTP, an IP or an internal name.
      const base = await publicBase(body.base_url, new Set(d.modelBases), d.resolve);
      if (!base) throw new ProxyError(400, "model_destination_not_enabled");
      const model = typeof body.model === "string" ? body.model.trim() : "";
      if (
        !model || model.length > 256 || /\p{Cc}/u.test(model) ||
        key.length < 8 || key.length > 8192 || /[\s\p{Cc}]/u.test(key)
      ) throw new ProxyError(400, "invalid_team_model");
      const id = crypto.randomUUID();
      // Encrypted here, bound to its provider ID; the database only receives ciphertext.
      const encrypted = await encryptCredential(key, id, d.masterKey);
      const hint = keyHint(key);
      key = "";
      await serviceRpc("observer_save_team_model", {
        p_user: d.userId,
        p_provider: id,
        p_base: base,
        p_model: model,
        p_encrypted_key: encrypted,
        p_key_hint: hint,
      });
      return { team_model: await userRpc("observer_team_model") };
    }
    case "delete_team_model":
      return { deleted: await userRpc("observer_delete_team_model") };
    case "set_team_model_mode":
      if (body.mode !== "stored" && body.mode !== "relay") throw new ProxyError(400, "invalid_team_model_mode");
      // Choosing "relay" deletes any saved key in the same database transaction.
      return { mode: await userRpc("observer_set_team_model_mode", { p_mode: body.mode }) };
    case "disable_provider":
      await userRpc("observer_disable_provider", { p_id: uuid(body.id) });
      return { accepted: true };
    case "download_project": {
      const reference = await serviceRpc("observer_materialized_project", {
        p_revision: uuid(body.revision_id),
        p_user: d.userId,
      });
      if (!reference) throw new ProxyError(404, "project_not_ready");
      if (!d.artifactDownload) throw new ProxyError(503, "artifact_service_unavailable");
      return { url: await d.artifactDownload(reference) };
    }
    case "download_result": {
      const run = uuid(body.run_id);
      // Read with the participant's token: RLS hides other teams' runs and runs of a
      // sealed (hidden final) phase until its results are published.
      const { data, error } = await d.user.from("observer_runs").select("result_path").eq("id", run)
        .maybeSingle();
      failure(error);
      if (!data?.result_path) throw new ProxyError(404, "result_not_ready");
      const path: string = data.result_path;
      let url: string;
      if (path.startsWith("github:")) {
        if (!d.artifactDownload) throw new ProxyError(503, "artifact_service_unavailable");
        url = await d.artifactDownload(path);
      } else {
        const signed = await staging.createSignedUrl(path, 120, { download: "observer-result.zip" });
        failure(signed.error);
        url = signed.data!.signedUrl;
      }
      try {
        const combined = await resultWithAgentLog(
          run,
          async () => {
            if (path.startsWith("github:")) return await fetchArchive(url, d.fetchArchive);
            const stored = await staging.download(path);
            if (stored.error || !stored.data) throw new Error("result_download_failed");
            return new Uint8Array(await stored.data.arrayBuffer());
          },
          {
            download: async (name) => {
              const { data, error } = await staging.download(name);
              return error || !data ? null : new Uint8Array(await data.arrayBuffer());
            },
            upload: async (name, bytes) => {
              const { error } = await staging.upload(name, bytes, { contentType: "application/zip", upsert: true });
              if (error) throw new Error("result_upload_failed");
            },
            sign: async (name) => {
              const { data, error } = await staging.createSignedUrl(name, 120, { download: "observer-result.zip" });
              if (error || !data) throw new Error("result_sign_failed");
              return data.signedUrl;
            },
          },
        );
        if (combined) return { url: combined };
      } catch {
        // The log is a convenience; the trusted result stays downloadable.
        console.warn("observer-portal: agent.log could not be added to the result download");
      }
      return { url };
    }
    case "accept_csv": {
      const run = uuid(body.run_id);
      const path = await serviceRpc("observer_upload_access", {
        p_user: d.userId,
        p_id: uuid(body.upload_id),
        p_purpose: "csv",
      });
      if (!path) throw new ProxyError(404, "upload_not_found");
      // Authorization before accessing the file; only the matching team's run.
      const visible = await d.user.from("observer_runs").select("id").eq("id", run).maybeSingle();
      failure(visible.error);
      if (!visible.data) throw new ProxyError(404, "run_not_found");
      const { data, error } = await staging.download(path);
      failure(error);
      if (!data || data.size > 20 * 1024 * 1024) throw new ProxyError(400, "csv_too_large");
      const bytes = new Uint8Array(await crypto.subtle.digest("SHA-256", await data.arrayBuffer()));
      const digest = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
      await serviceRpc("observer_accept_uploaded_csv", {
        p_run: run,
        p_user: d.userId,
        p_upload: uuid(body.upload_id),
        p_digest: digest,
      });
      return { accepted: true };
    }
    default:
      throw new ProxyError(400, "unknown_portal_action");
  }
}
