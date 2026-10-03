import { assert, assertEquals, assertRejects } from "@std/assert";
import { fulfillPersonalModel, personalChat, personalMessages } from "./observer-personal-model.ts";
const run = "10000000-0000-4000-8000-000000000001", call = "10000000-0000-4000-8000-000000000002";
const key = "private-key-fixture-never-store";
const input = () => ({
  run_id: run,
  call_id: call,
  api_key: key,
  base_url: "https://personal.example/v1",
  model: "own-model",
  body: { model: "project-model", messages: [{ role: "user", content: "Choose a tile" }], max_tokens: 40 },
});
Deno.test("personal API key only reaches the selected HTTPS provider and is redacted from outputs", async () => {
  const receipts: any[] = [], messages: any[] = [];
  const data = input();
  let calls = 0;
  const result = await fulfillPersonalModel(data, "team-user", {
    trustedBases: new Set(["https://personal.example/v1"]),
    rpc: async (name, args) => {
      receipts.push({ name, args });
      return "private-topic";
    },
    fetch: ((url, opts) => {
      calls++;
      assertEquals(String(url), "https://personal.example/v1/chat/completions");
      assertEquals((opts!.headers as any).authorization, "Bearer " + key);
      assertEquals(opts!.redirect, "error");
      assertEquals(JSON.parse(String(opts!.body)).model, "own-model");
      return Promise.resolve(Response.json({ choices: [{ message: { content: key } }] }));
    }) as typeof fetch,
    send: async (topic, event, payload) => {
      messages.push({ topic, event, payload });
    },
  });
  assertEquals(result, { completed: true });
  assertEquals(calls, 1);
  assertEquals(data.api_key, "");
  assert(!JSON.stringify(receipts).includes(key));
  assert(!JSON.stringify(messages).includes(key));
  assert(JSON.stringify(messages).includes("[REDACTED]"));
});
Deno.test("wrong owner, duplicate claims and unapproved addresses never call a provider", async () => {
  let calls = 0;
  const deps = {
    trustedBases: new Set(["https://personal.example/v1"]),
    rpc: async () => {
      throw new Error("denied");
    },
    fetch: (() => {
      calls++;
      return Promise.resolve(Response.json({}));
    }) as typeof fetch,
    send: async () => {},
  };
  await assertRejects(() => fulfillPersonalModel(input(), "outsider", deps));
  await assertRejects(() =>
    fulfillPersonalModel({ ...input(), base_url: "http://personal.example/v1" }, "owner", deps)
  );
  await assertRejects(() => fulfillPersonalModel({ ...input(), base_url: "https://127.0.0.1/" }, "owner", deps));
  // A public-looking name that resolves inside is refused like an internal address.
  const inside = { ...deps, resolve: () => Promise.resolve(["192.168.0.10"]) };
  await assertRejects(() => fulfillPersonalModel({ ...input(), base_url: "https://api.team.com/v1" }, "owner", inside));
  assertEquals(calls, 0);
});
Deno.test("provider failure does not disclose its body, key or exception", async () => {
  const output: any[] = [];
  const data = input();
  assertEquals(
    await fulfillPersonalModel(data, "owner", {
      trustedBases: new Set([data.base_url]),
      rpc: async () => "topic",
      fetch: (() => {
        throw new Error(key);
      }) as typeof fetch,
      send: async (_t, _e, p) => {
        output.push(p);
      },
    }),
    { completed: false },
  );
  assertEquals(data.api_key, "");
  assert(!JSON.stringify(output).includes(key));
});
Deno.test("project proxy relays no credentials, and browser loss ends without organizer fallback", async () => {
  const receipts: any[] = [];
  let exchanged = false;
  const request = new Request("https://platform.test/v1/chat/completions", {
    method: "POST",
    headers: { authorization: "Bearer obs_" + run + "." + "a".repeat(43), "idempotency-key": call },
    body: JSON.stringify(input().body),
  });
  await assertRejects(() =>
    personalChat(request, "topic", {
      rpc: async (name, args) => {
        receipts.push({ name, args });
        return true;
      },
      exchange: async (_t, _c, p) => {
        exchanged = true;
        assert(!JSON.stringify(p).includes(key));
        throw new Error("browser closed");
      },
    })
  );
  assert(exchanged);
  assertEquals(receipts.map((x) => x.name), ["observer_request_personal_model", "observer_finish_personal_model"]);
  assertEquals(receipts[1].args.p_status, "timeout");
});
Deno.test("a relayed provider that exceeds the deadline is reported as a timeout only", async () => {
  const output: any[] = [];
  const data = input();
  assertEquals(
    await fulfillPersonalModel(data, "owner", {
      trustedBases: new Set([data.base_url]),
      rpc: async () => "topic",
      fetch: (() => Promise.reject(new DOMException("Signal timed out.", "TimeoutError"))) as typeof fetch,
      send: async (_t, _e, p) => {
        output.push(p);
      },
    }),
    { completed: false },
  );
  assertEquals(output, [{ call_id: call, error: "personal_model_timeout" }]);
});

// Anthropic Messages relay: the open page still answers with its own key, but
// speaks x-api-key and the Messages shape instead of chat/completions.
const anthropicInput = () => ({
  run_id: run,
  call_id: call,
  api_key: key,
  base_url: "https://personal.example/v1",
  model: "own-claude-model",
  protocol: "anthropic",
  anthropic_version: "2023-06-01",
  body: { model: "project-model", messages: [{ role: "user", content: "Choose a tile" }], max_tokens: 40 },
});
Deno.test("relayed Anthropic calls use x-api-key and the Messages shape, redacted from outputs", async () => {
  const receipts: any[] = [], messages: any[] = [];
  const data = anthropicInput();
  let calls = 0;
  const result = await fulfillPersonalModel(data, "team-user", {
    trustedBases: new Set(["https://personal.example/v1"]),
    rpc: async (name, args) => {
      receipts.push({ name, args });
      return "private-topic";
    },
    fetch: ((url, opts) => {
      calls++;
      assertEquals(String(url), "https://personal.example/v1/messages");
      const headers = opts!.headers as any;
      assertEquals(headers["x-api-key"], key);
      assertEquals(headers.authorization, undefined);
      assertEquals(headers["anthropic-version"], "2023-06-01");
      assertEquals(opts!.redirect, "error");
      assertEquals(JSON.parse(String(opts!.body)).model, "own-claude-model");
      return Promise.resolve(Response.json({ type: "message", content: [{ type: "text", text: key }] }));
    }) as typeof fetch,
    send: async (topic, event, payload) => {
      messages.push({ topic, event, payload });
    },
  });
  assertEquals(result, { completed: true });
  assertEquals(calls, 1);
  assertEquals(data.api_key, "");
  assert(!JSON.stringify(receipts).includes(key));
  assert(!JSON.stringify(messages).includes(key));
  assert(JSON.stringify(messages).includes("[REDACTED]"));
});
Deno.test("the open page's protocol choice never reaches the database, only the broadcast call", async () => {
  const request = new Request("https://platform.test/v1/messages", {
    method: "POST",
    headers: { "x-api-key": "obs_" + run + "." + "a".repeat(43), "idempotency-key": call },
    body: JSON.stringify(anthropicInput().body),
  });
  let payload: any;
  await assertRejects(() =>
    personalMessages(request, "topic", {
      rpc: async () => true,
      exchange: async (_t, _c, p) => {
        payload = p;
        throw new Error("browser closed");
      },
    })
  );
  assertEquals(payload.protocol, "anthropic");
  assertEquals(payload.anthropic_version, "2023-06-01");
});
Deno.test("a mismatched Anthropic content shape from the provider is refused like the chat path", async () => {
  const data = anthropicInput();
  assertEquals(
    await fulfillPersonalModel(data, "owner", {
      trustedBases: new Set([data.base_url]),
      rpc: async () => "topic",
      fetch: (() => Promise.resolve(Response.json({ type: "message" }))) as typeof fetch,
      send: async () => {},
    }),
    { completed: false },
  );
});
