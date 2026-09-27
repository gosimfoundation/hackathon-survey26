import { assert, assertEquals, assertRejects, assertThrows } from "@std/assert";
import {
  capability,
  chatCompletion,
  decryptCredential,
  encryptCredential,
  MAX_TEAM_RESPONSE,
  ProxyError,
  teamChatCompletion,
  validateChat,
} from "./observer-model.ts";
import type { ProxyDependencies, TeamProxyDependencies } from "./observer-model.ts";

const run = "00000000-0000-4000-8000-000000000001";
const provider = "00000000-0000-4000-8000-000000000002";
const token = "a".repeat(43);
const master = btoa("k".repeat(32));
function request(
  body: unknown = { model: "qwen-test", messages: [{ role: "user", content: "hi" }], max_tokens: 32 },
  headers = {},
) {
  return new Request("https://platform.test/observer-model/v1/chat/completions", {
    method: "POST",
    headers: { authorization: "Bearer obs_" + run + "." + token, "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}
function fixture(overrides: Partial<ProxyDependencies> = {}) {
  const calls: { name: string; args: Record<string, unknown> }[] = [];
  const upstream: { url: string; init: RequestInit | undefined }[] = [];
  const deps: ProxyDependencies = {
    rpc: (name, args) => {
      calls.push({ name, args });
      return Promise.resolve(
        name === "observer_reserve_model"
          ? { reserved: true, base_url: "https://provider.test/v1", encrypted_key: "encrypted" }
          : null,
      );
    },
    fetch: (url, init) => {
      upstream.push({ url: String(url), init });
      return Promise.resolve(
        Response.json({ choices: [{ message: { role: "assistant", content: "OK" } }], usage: { total_tokens: 18 } }),
      );
    },
    decrypt: () => Promise.resolve("private-master-api-key"),
    allowedBases: new Set(["https://provider.test/v1"]),
    allowedHttpBases: new Set(),
    defaultProvider: provider,
    ...overrides,
  };
  return { deps, calls, upstream };
}

Deno.test("scoped credentials are parsed and account/GitHub tokens are rejected", () => {
  assertEquals(capability("Bearer obs_" + run + "." + token), { run, token });
  for (const value of [null, "Bearer supabase-jwt", "Bearer ghp-token", "Bearer obs_" + run + ".short"]) {
    assertThrows(() => capability(value), ProxyError);
  }
});

Deno.test("chat limits bound text, calls and completion size before charging", () => {
  const good = { model: "m", messages: [{ role: "user", content: "天文".repeat(10) }], max_tokens: 20 };
  const checked = validateChat(good);
  assert(checked.reservedTokens > new TextEncoder().encode(JSON.stringify(good)).length + 20);
  for (
    const bad of [
      { ...good, stream: true },
      { ...good, n: 2 },
      { ...good, max_tokens: 5000 },
      { ...good, max_tokens: -1 },
      { ...good, max_completion_tokens: 20 },
      { ...good, unknown: "option" },
      {
        ...good,
        messages: [{ role: "user", content: [{ type: "image_url", image_url: { url: "https://example.test" } }] }],
      },
      { ...good, messages: [{ role: "user", content: "a".repeat(65536) }] },
    ]
  ) assertThrows(() => validateChat(bad), ProxyError);
});

Deno.test("encryption is random, round-trips, and binds each key to its provider", async () => {
  const a = await encryptCredential("a real key", provider, master);
  const b = await encryptCredential("a real key", provider, master);
  assert(a !== b && !a.includes("a real key"));
  assertEquals(await decryptCredential(a, provider, master), "a real key");
  await assertRejects(() => decryptCredential(a, run, master), ProxyError);
  await assertRejects(() => decryptCredential(a, provider, btoa("z".repeat(32))), ProxyError);
});

Deno.test("proxy reserves before forwarding, strips scoped key, and settles actual usage", async () => {
  const f = fixture();
  const result = await chatCompletion(request(), f.deps);
  assertEquals(result.status, 200);
  assertEquals((await result.json()).choices[0].message.content, "OK");
  assertEquals(f.calls.map((c) => c.name), ["observer_reserve_model", "observer_settle_model"]);
  assertEquals(f.calls[0].args.p_run, run);
  assertEquals(f.calls[0].args.p_provider, provider);
  assertEquals(f.calls[0].args.p_token, token);
  assertEquals(f.calls[1].args.p_actual_tokens, 18);
  assertEquals(f.upstream.length, 1);
  assertEquals(f.upstream[0].init?.redirect, "error");
  assertEquals(new Headers(f.upstream[0].init?.headers).get("authorization"), "Bearer private-master-api-key");
  assert(!String(f.upstream[0].init?.body).includes(token));
});

Deno.test("BYO provider prefix is routed without changing the upstream model name", async () => {
  const f = fixture();
  await chatCompletion(request({ model: run + "::custom-model", messages: [{ role: "user", content: "OK" }] }), f.deps);
  assertEquals(f.calls[0].args.p_provider, run);
  assertEquals(JSON.parse(String(f.upstream[0].init?.body)).model, "custom-model");
});

Deno.test("duplicate idempotency key never resends to the provider", async () => {
  const f = fixture({ rpc: () => Promise.resolve({ reserved: false, status: "settled" }) });
  const error = await assertRejects(() => chatCompletion(request(), f.deps), ProxyError);
  assertEquals(error.code, "model_request_already_received");
  assertEquals(f.upstream.length, 0);
});

Deno.test("quota failure makes zero upstream calls", async () => {
  const f = fixture({ rpc: () => Promise.reject(new ProxyError(429, "run_model_quota")) });
  await assertRejects(() => chatCompletion(request(), f.deps), ProxyError);
  assertEquals(f.upstream.length, 0);
});

Deno.test("unapproved destinations are rejected before secrets are forwarded", async () => {
  const f = fixture({ allowedBases: new Set(["https://different.test/v1"]) });
  await assertRejects(() => chatCompletion(request(), f.deps), ProxyError);
  assertEquals(f.upstream.length, 0);
  assertEquals(f.calls.at(-1)?.args.p_actual_tokens, 0);
});

Deno.test("HTTP requires an explicit backend exception as well as a provider flag", async () => {
  const f = fixture({ allowedBases: new Set(["http://provider.test:40101/v1"]) });
  const baseRpc = f.deps.rpc;
  f.deps.rpc = async (name, args) => {
    const value = await baseRpc(name, args);
    return name === "observer_reserve_model"
      ? { ...value, base_url: "http://provider.test:40101/v1", allow_http: true }
      : value;
  };
  await assertRejects(() => chatCompletion(request(), f.deps), ProxyError);
  assertEquals(f.upstream.length, 0);
  f.deps.allowedHttpBases.add("http://provider.test:40101/v1");
  assertEquals((await chatCompletion(request(), f.deps)).status, 200);
  assertEquals(f.upstream.length, 1);
});

Deno.test("unknown network failure consumes reservation and hides internal errors", async () => {
  const f = fixture({ fetch: () => Promise.reject(new Error("private-master-api-key socket detail")) });
  const error = await assertRejects(() => chatCompletion(request(), f.deps), ProxyError);
  assertEquals(error.code, "model_provider_unavailable");
  assertEquals(f.calls.at(-1)?.args.p_actual_tokens, null);
});

Deno.test("provider errors never return credential-bearing diagnostics", async () => {
  const f = fixture({ fetch: () => Promise.resolve(new Response("private-master-api-key internal", { status: 500 })) });
  const error = await assertRejects(() => chatCompletion(request(), f.deps), ProxyError);
  assertEquals(error.code, "model_provider_error");
  assertEquals(error.detail, { provider_status: 500 });
  assertEquals(f.calls.at(-1)?.args.p_actual_tokens, null);
});

Deno.test("missing or invalid usage is charged conservatively", async () => {
  for (const usage of [undefined, { total_tokens: -1 }, { total_tokens: 99999999 }, { total_tokens: 0.5 }]) {
    const f = fixture({ fetch: () => Promise.resolve(Response.json({ choices: [], usage })) });
    await chatCompletion(request(), f.deps);
    assertEquals(f.calls.at(-1)?.args.p_actual_tokens, null);
  }
});

Deno.test("provider cannot accidentally echo its credential into participant logs", async () => {
  const f = fixture({
    fetch: () =>
      Promise.resolve(Response.json({
        choices: [{ message: { content: "private-master-api-key" } }],
        usage: { total_tokens: 10 },
      })),
  });
  const result = await chatCompletion(request(), f.deps);
  assertEquals((await result.json()).choices[0].message.content, "[REDACTED]");
});

Deno.test("accounting failure retains the reservation and never retries inference", async () => {
  const f = fixture();
  const base = f.deps.rpc;
  f.deps.rpc = (name, args) =>
    name === "observer_settle_model"
      ? Promise.reject(new ProxyError(503, "model_accounting_unavailable"))
      : base(name, args);
  await assertRejects(() => chatCompletion(request(), f.deps), ProxyError);
  assertEquals(f.upstream.length, 1);
});

// Formal runs: the team's saved key, stored encrypted and decrypted per request.
const teamProvider = "00000000-0000-4000-8000-000000000003";
const teamKey = "team-saved-key-fixture-0123456789";
function teamFixture(overrides: Partial<TeamProxyDependencies> = {}, reservation: Record<string, unknown> = {}) {
  const calls: { name: string; args: Record<string, unknown> }[] = [];
  const upstream: { url: string; init: RequestInit | undefined }[] = [];
  const decrypted: { ciphertext: string; provider: string }[] = [];
  const deps: TeamProxyDependencies = {
    rpc: (name, args) => {
      calls.push({ name, args });
      return Promise.resolve(
        name === "observer_reserve_team_model"
          ? {
            reserved: true,
            provider_id: teamProvider,
            base_url: "https://team-provider.test/v1",
            model: "saved-model",
            encrypted_key: "v1.stored.ciphertext",
            ...reservation,
          }
          : null,
      );
    },
    fetch: (url, init) => {
      upstream.push({ url: String(url), init });
      return Promise.resolve(
        Response.json({ choices: [{ message: { role: "assistant", content: "OK" } }], usage: { total_tokens: 21 } }),
      );
    },
    decrypt: (ciphertext, provider) => {
      decrypted.push({ ciphertext, provider });
      return Promise.resolve(teamKey);
    },
    trustedBases: new Set(["https://team-provider.test/v1", "http://organizer-test.test/v1"]),
    resolve: null,
    ...overrides,
  };
  return { deps, calls, upstream, decrypted };
}
const teamRequest = (headers = {}) =>
  request({ model: "project-chosen-model", messages: [{ role: "user", content: "hi" }], max_tokens: 32 }, headers);

Deno.test("formal run sends the saved key only to the saved HTTPS provider with the saved model", async () => {
  const f = teamFixture();
  const result = await teamChatCompletion(teamRequest({ "idempotency-key": provider }), f.deps);
  assertEquals(result.status, 200);
  assertEquals(result.headers.get("cache-control"), "no-store");
  assertEquals(result.headers.get("x-observer-request-id"), provider);
  assertEquals((await result.json()).choices[0].message.content, "OK");
  assertEquals(f.calls.map((c) => c.name), ["observer_reserve_team_model", "observer_settle_model"]);
  assertEquals(f.calls[0].args.p_run, run);
  assertEquals(f.calls[0].args.p_token, token);
  assertEquals(f.calls[0].args.p_call, provider);
  assertEquals(f.calls[1].args, { p_call: provider, p_actual_tokens: 21 });
  assertEquals(f.decrypted, [{ ciphertext: "v1.stored.ciphertext", provider: teamProvider }]);
  assertEquals(f.upstream.length, 1);
  assertEquals(f.upstream[0].url, "https://team-provider.test/v1/chat/completions");
  assertEquals(f.upstream[0].init?.redirect, "error");
  assertEquals(new Headers(f.upstream[0].init?.headers).get("authorization"), "Bearer " + teamKey);
  const sent = JSON.parse(String(f.upstream[0].init?.body));
  assertEquals(sent.model, "saved-model");
  assert(!String(f.upstream[0].init?.body).includes(token));
  // The database only ever receives digests and receipts, never the key.
  assert(!JSON.stringify(f.calls).includes(teamKey));
});

Deno.test("formal run without a saved key fails without any organizer fallback", async () => {
  const f = teamFixture({
    rpc: (name, args) => {
      f.calls.push({ name, args });
      return Promise.reject(new ProxyError(403, "team_model_not_configured"));
    },
  });
  const error = await assertRejects(() => teamChatCompletion(teamRequest(), f.deps), ProxyError);
  assertEquals(error.code, "team_model_not_configured");
  assertEquals(f.calls.map((c) => c.name), ["observer_reserve_team_model"]);
  assertEquals(f.decrypted.length, 0);
  assertEquals(f.upstream.length, 0);
});

Deno.test("a saved public HTTPS base outside the organizer list is used once its addresses are public", async () => {
  const base_url = "https://api.team-choice.com/v1";
  const f = teamFixture({ resolve: (_host, type) => Promise.resolve(type === "A" ? ["104.18.2.5"] : []) }, {
    base_url,
  });
  assertEquals((await teamChatCompletion(teamRequest(), f.deps)).status, 200);
  assertEquals(f.upstream[0].url, base_url + "/chat/completions");
  const inside = teamFixture({ resolve: (_host, type) => Promise.resolve(type === "A" ? ["10.0.0.7"] : []) }, {
    base_url,
  });
  const error = await assertRejects(() => teamChatCompletion(teamRequest(), inside.deps), ProxyError);
  assertEquals(error.code, "provider_not_authorized");
  assertEquals(inside.decrypted.length, 0);
  assertEquals(inside.upstream.length, 0);
});

Deno.test("HTTP, internal, reserved and credential-bearing saved bases are refused before decrypting", async () => {
  for (
    const base_url of [
      "http://organizer-test.test/v1",
      "https://unapproved.test/v1",
      "https://169.254.169.254/v1",
      "https://localhost/v1",
      "https://user:pass@team-provider.test/v1",
      "https://team-provider.test/v1?redirect=https://elsewhere.test",
    ]
  ) {
    const f = teamFixture({}, { base_url });
    const error = await assertRejects(() => teamChatCompletion(teamRequest(), f.deps), ProxyError);
    assertEquals(error.code, "provider_not_authorized");
    assertEquals(f.decrypted.length, 0);
    assertEquals(f.upstream.length, 0);
    assertEquals(f.calls.at(-1)?.args.p_actual_tokens, 0);
  }
});

Deno.test("provider redirects are never followed and failures disclose no key or body", async () => {
  const redirect = teamFixture({
    fetch: (_url, init) => {
      assertEquals(init?.redirect, "error");
      return Promise.reject(new TypeError("redirect to https://elsewhere.test with " + teamKey));
    },
  });
  const moved = await assertRejects(() => teamChatCompletion(teamRequest(), redirect.deps), ProxyError);
  assertEquals(moved.code, "model_provider_unavailable");
  assert(!moved.message.includes(teamKey));
  assertEquals(redirect.calls.at(-1)?.args.p_actual_tokens, null);
  const denied = teamFixture({
    fetch: () => Promise.resolve(new Response("invalid key " + teamKey, { status: 401 })),
  });
  const failed = await assertRejects(() => teamChatCompletion(teamRequest(), denied.deps), ProxyError);
  assertEquals(failed.code, "model_provider_error");
  assertEquals(failed.detail, { provider_status: 401 });
  assert(!failed.message.includes(teamKey));
  // A rejected call returned no completion, so the team is not charged for it.
  assertEquals(denied.calls.at(-1)?.args.p_actual_tokens, 0);
});

Deno.test("provider output echoing the saved key is redacted, and oversized output is refused", async () => {
  const echo = teamFixture({
    fetch: () => Promise.resolve(Response.json({ choices: [{ message: { content: "key " + teamKey } }] })),
  });
  const body = await (await teamChatCompletion(teamRequest(), echo.deps)).text();
  assert(!body.includes(teamKey) && body.includes("[REDACTED]"));
  assertEquals(echo.calls.at(-1)?.args.p_actual_tokens, null);
  const large = teamFixture({
    fetch: () => Promise.resolve(Response.json({ choices: [{ message: { content: "x".repeat(MAX_TEAM_RESPONSE) } }] })),
  });
  const error = await assertRejects(() => teamChatCompletion(teamRequest(), large.deps), ProxyError);
  assertEquals(error.code, "model_response_too_large");
});

Deno.test("duplicate formal call IDs and invalid IDs never reach the provider", async () => {
  const duplicate = teamFixture({ rpc: () => Promise.resolve({ reserved: false, status: "settled" }) });
  const error = await assertRejects(() => teamChatCompletion(teamRequest(), duplicate.deps), ProxyError);
  assertEquals(error.code, "model_request_already_received");
  assertEquals(duplicate.upstream.length + duplicate.decrypted.length, 0);
  const invalid = teamFixture();
  await assertRejects(() => teamChatCompletion(teamRequest({ "idempotency-key": "not-a-uuid" }), invalid.deps));
  assertEquals(invalid.calls.length + invalid.upstream.length, 0);
});

Deno.test("formal requests keep the 64 KiB request cap before any reservation", async () => {
  const f = teamFixture();
  const big = request({ model: "m", messages: [{ role: "user", content: "a".repeat(70000) }] });
  await assertRejects(() => teamChatCompletion(big, f.deps), ProxyError);
  assertEquals(f.calls.length + f.upstream.length, 0);
});
