import { assert, assertEquals, assertRejects } from "@std/assert";
import type { SupabaseClient } from "npm:@supabase/supabase-js@2";
import { decryptCredential, ProxyError } from "./observer-model.ts";
import { keyHint, portalRequest } from "./observer-portal.ts";

const master = btoa("m".repeat(32));
const user = "20000000-0000-4000-8000-000000000001";
const key = "sk-team-fixture-abcdefghijklmnop-9Zq4";
type Call = { client: string; name: string; args: Record<string, unknown> };

function clients(status: unknown = { base_url: "https://api.example.test/v1", model: "glm-4.6", key_hint: "9Zq4" }) {
  const calls: Call[] = [];
  const client = (label: string) =>
    ({
      rpc: (name: string, args: Record<string, unknown> = {}) => {
        calls.push({ client: label, name, args });
        const data = name === "observer_delete_team_model"
          ? true
          : name === "observer_set_team_model_mode"
          ? args.p_mode
          : status;
        return Promise.resolve({ data, error: null });
      },
      storage: { from: () => ({}) },
    }) as unknown as SupabaseClient;
  return { calls, user: client("user"), service: client("service") };
}
function portal(body: Record<string, unknown>, c = clients()) {
  return portalRequest(new Request("https://portal.test", { method: "POST", body: JSON.stringify(body) }), {
    user: c.user,
    service: c.service,
    userId: user,
    masterKey: master,
    modelBases: ["https://api.example.test/v1", "http://organizer-test.example.test/v1"],
    httpBases: ["http://organizer-test.example.test/v1"],
  });
}

Deno.test("a saved key is encrypted before storage and never returned or sent to the database in plaintext", async () => {
  const c = clients();
  const result = await portal({
    action: "save_team_model",
    base_url: "https://api.example.test/v1/",
    model: " glm-4.6 ",
    key: "  " + key + "\n",
  }, c);
  assertEquals(c.calls.map((x) => [x.client, x.name]), [
    ["service", "observer_save_team_model"],
    ["user", "observer_team_model"],
  ]);
  const saved = c.calls[0].args;
  assertEquals(saved.p_user, user);
  assertEquals(saved.p_base, "https://api.example.test/v1");
  assertEquals(saved.p_model, "glm-4.6");
  assertEquals(saved.p_key_hint, "9Zq4");
  // Bound to the provider ID it was stored under; another ID cannot decrypt it.
  assertEquals(await decryptCredential(String(saved.p_encrypted_key), String(saved.p_provider), master), key);
  await assertRejects(() => decryptCredential(String(saved.p_encrypted_key), user, master), ProxyError);
  assert(!JSON.stringify(c.calls).includes(key));
  assert(!JSON.stringify(result).includes(key));
  assert(!JSON.stringify(result).includes(String(saved.p_encrypted_key)));
});

Deno.test("HTTP, unapproved and malformed model settings are refused before encryption or storage", async () => {
  const cases: [Record<string, unknown>, string][] = [
    [{ base_url: "http://organizer-test.example.test/v1", model: "m", key }, "model_destination_not_enabled"],
    [{ base_url: "https://unapproved.example.test/v1", model: "m", key }, "model_destination_not_enabled"],
    [{ base_url: "https://user:pw@api.example.test/v1", model: "m", key }, "model_destination_not_enabled"],
    [{ base_url: "https://api.example.test/v1", model: "", key }, "invalid_team_model"],
    [{ base_url: "https://api.example.test/v1", model: "m\nx", key }, "invalid_team_model"],
    [{ base_url: "https://api.example.test/v1", model: "m", key: "short" }, "invalid_team_model"],
    [{ base_url: "https://api.example.test/v1", model: "m", key: "has space inside-key" }, "invalid_team_model"],
    [{ base_url: "https://api.example.test/v1", model: "m", key: "x".repeat(8193) }, "invalid_team_model"],
  ];
  for (const [fields, code] of cases) {
    const c = clients();
    const error = await assertRejects(() => portal({ action: "save_team_model", ...fields }, c), ProxyError);
    assertEquals(error.code, code);
    assertEquals(c.calls.length, 0);
    assert(!error.message.includes(key));
  }
});

Deno.test("key hints reveal at most four characters and nothing for short keys", () => {
  assertEquals(keyHint("0123456789abcdef"), "cdef");
  assertEquals(keyHint("short-key-12345"), "");
});

Deno.test("deleting and choosing the mode use the caller's own team RPCs", async () => {
  const c = clients();
  assertEquals(await portal({ action: "delete_team_model", team_id: "someone-else" }, c), { deleted: true });
  assertEquals(await portal({ action: "set_team_model_mode", mode: "relay", team_id: "someone-else" }, c), {
    mode: "relay",
  });
  assertEquals(c.calls, [
    { client: "user", name: "observer_delete_team_model", args: {} },
    { client: "user", name: "observer_set_team_model_mode", args: { p_mode: "relay" } },
  ]);
  for (const mode of ["", "organizer", null]) {
    const rejected = clients();
    const error = await assertRejects(() => portal({ action: "set_team_model_mode", mode }, rejected), ProxyError);
    assertEquals(error.code, "invalid_team_model_mode");
    assertEquals(rejected.calls.length, 0);
  }
});

Deno.test("a repeat evaluation is only requested with an explicit confirmation", async () => {
  const phase = "30000000-0000-4000-8000-000000000001", revision = "30000000-0000-4000-8000-000000000002";
  const c = clients("batch");
  await portal({ action: "evaluate", phase_id: phase, revision_id: revision, confirm_repeat: "yes" }, c);
  await portal({ action: "evaluate", phase_id: phase, revision_id: revision, confirm_repeat: true }, c);
  assertEquals(c.calls.map((x) => x.args), [
    { p_phase: phase, p_revision: revision },
    { p_phase: phase, p_revision: revision, p_confirm_repeat: true },
  ]);
});

Deno.test("withdrawal uses the caller's team RPC and database refusals keep their codes", async () => {
  const revision = "30000000-0000-4000-8000-000000000002";
  const c = clients();
  assertEquals(await portal({ action: "withdraw", revision_id: revision }, c), { accepted: true });
  assertEquals(c.calls, [{ client: "user", name: "observer_withdraw_revision", args: { p_revision: revision } }]);
  await assertRejects(() => portal({ action: "withdraw", revision_id: "not-a-uuid" }, clients()), ProxyError);
  for (const code of ["revision_not_withdrawable", "revision_already_evaluated", "revision_withdrawn", "other"]) {
    const refused = {
      user: { rpc: () => Promise.resolve({ data: null, error: { message: code } }) } as unknown as SupabaseClient,
      service: clients().service,
    };
    const error = await assertRejects(
      () => portal({ action: "withdraw", revision_id: revision }, { ...refused, calls: [] }),
      ProxyError,
    );
    assertEquals(error.code, code === "other" ? "portal_request_failed" : code);
  }
});

Deno.test("result download adds the team's stored agent.log, or falls back to the original result", async () => {
  const { singleFileZip, readZipEntry } = await import("./observer-zip.ts");
  const run = "30000000-0000-4000-8000-000000000001";
  const encode = (s: string) => new TextEncoder().encode(s);
  const objects = new Map<string, Uint8Array>();
  const signed: string[] = [];
  const result = await singleFileZip("decisions.csv", encode("night,action\n"));
  const client = (visible: boolean) =>
    ({
      from: (table: string) => {
        assertEquals(table, "observer_runs");
        const query = {
          select: () => query,
          eq: (_column: string, value: string) => {
            assertEquals(value, run);
            return query;
          },
          maybeSingle: () =>
            Promise.resolve({
              data: visible ? { result_path: "github:ORG/participant-x@" + "a".repeat(40) } : null,
              error: null,
            }),
        };
        return query;
      },
      storage: {
        from: (bucket: string) => {
          assertEquals(bucket, "observer-staging");
          return {
            download: (path: string) =>
              Promise.resolve(
                objects.has(path)
                  ? { data: new Blob([objects.get(path)! as Uint8Array<ArrayBuffer>]), error: null }
                  : { data: null, error: { message: "Object not found" } },
              ),
            upload: (path: string, data: Uint8Array, options: Record<string, unknown>) => {
              assertEquals(options, { contentType: "application/zip", upsert: true });
              objects.set(path, data);
              return Promise.resolve({ data: { path }, error: null });
            },
            createSignedUrl: (path: string, seconds: number) => {
              assert(seconds <= 120);
              signed.push(path);
              return Promise.resolve({ data: { signedUrl: "https://storage.test/" + path }, error: null });
            },
          };
        },
      },
    }) as unknown as SupabaseClient;
  const download = (visible = true) =>
    portalRequest(
      new Request("https://portal.test", {
        method: "POST",
        body: JSON.stringify({ action: "download_result", run_id: run }),
      }),
      {
        user: client(visible),
        service: client(visible),
        userId: user,
        masterKey: master,
        modelBases: [],
        httpBases: [],
        artifactDownload: (reference) => {
          assert(reference.startsWith("github:"));
          return Promise.resolve("https://codeload.github.com/result.zip");
        },
        fetchArchive: (url) => {
          assertEquals(String(url), "https://codeload.github.com/result.zip");
          return Promise.resolve(new Response(result as Uint8Array<ArrayBuffer>));
        },
      },
    );
  // Another team's run is invisible before any service storage read.
  await assertRejects(() => download(false), ProxyError, "result_not_ready");
  assertEquals(signed, []);
  // No stored log (local session, older run): the original result is unchanged.
  assertEquals(await download(), { url: "https://codeload.github.com/result.zip" });
  objects.set(
    "agent-logs/" + run + "/agent-log.zip",
    await singleFileZip("agent.log", encode("[platform] project stderr\nhello\n")),
  );
  assertEquals(await download(), { url: "https://storage.test/agent-logs/" + run + "/observer-result.zip" });
  const combined = objects.get("agent-logs/" + run + "/observer-result.zip")!;
  assertEquals(new TextDecoder().decode((await readZipEntry(combined, "agent.log", 1000))!).endsWith("hello\n"), true);
  assertEquals(new TextDecoder().decode((await readZipEntry(combined, "decisions.csv", 1000))!), "night,action\n");
  // A damaged stored log never blocks the trusted result.
  objects.set("agent-logs/" + run + "/agent-log.zip", encode("damaged"));
  assertEquals(await download(), { url: "https://codeload.github.com/result.zip" });
});

Deno.test("the final version is set or cleared through the caller's team RPC", async () => {
  const phase = "30000000-0000-4000-8000-000000000001", revision = "30000000-0000-4000-8000-000000000002";
  const c = clients({ revision_id: revision, source: "chosen" });
  assertEquals(await portal({ action: "set_final_version", phase_id: phase, revision_id: revision }, c), {
    final_version: { revision_id: revision, source: "chosen" },
  });
  await portal({ action: "set_final_version", phase_id: phase, revision_id: null }, c);
  await portal({ action: "set_final_version", phase_id: phase }, c);
  assertEquals(c.calls, [
    { client: "user", name: "observer_set_final_version", args: { p_phase: phase, p_revision: revision } },
    { client: "user", name: "observer_set_final_version", args: { p_phase: phase, p_revision: null } },
    { client: "user", name: "observer_set_final_version", args: { p_phase: phase, p_revision: null } },
  ]);
  for (const fields of [{ phase_id: "x", revision_id: revision }, { phase_id: phase, revision_id: "x" }]) {
    const refused = clients();
    await assertRejects(() => portal({ action: "set_final_version", ...fields }, refused), ProxyError);
    assertEquals(refused.calls.length, 0);
  }
  for (const code of ["final_version_locked", "final_phase_invalid", "revision_not_approved", "other"]) {
    const refused = {
      user: { rpc: () => Promise.resolve({ data: null, error: { message: code } }) } as unknown as SupabaseClient,
      service: clients().service,
    };
    const error = await assertRejects(
      () => portal({ action: "set_final_version", phase_id: phase, revision_id: revision }, { ...refused, calls: [] }),
      ProxyError,
    );
    assertEquals(error.code, code === "other" ? "portal_request_failed" : code);
  }
});

Deno.test("a result the participant cannot read (another team, or a sealed hidden run) is never signed", async () => {
  const run = "30000000-0000-4000-8000-000000000003";
  const signed: string[] = [];
  const invisible = {
    from: () => ({
      select: () => ({ eq: () => ({ maybeSingle: () => Promise.resolve({ data: null, error: null }) }) }),
    }),
  } as unknown as SupabaseClient;
  const service = {
    storage: { from: () => ({ createSignedUrl: (path: string) => (signed.push(path), Promise.resolve({})) }) },
  } as unknown as SupabaseClient;
  const error = await assertRejects(
    () =>
      portalRequest(
        new Request("https://portal.test", {
          method: "POST",
          body: JSON.stringify({ action: "download_result", run_id: run }),
        }),
        {
          user: invisible,
          service,
          userId: user,
          masterKey: master,
          modelBases: [],
          httpBases: [],
          artifactDownload: (reference) => (signed.push(reference), Promise.resolve("https://x.test")),
        },
      ),
    ProxyError,
  );
  assertEquals(error.code, "result_not_ready");
  assertEquals(signed, []);
});
