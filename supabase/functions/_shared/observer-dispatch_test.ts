import { assertEquals } from "@std/assert";
import { encryptCredential } from "./observer-model.ts";
import { dispatchPending } from "./observer-dispatch.ts";
import { GitHubError } from "./observer-github.ts";

Deno.test("dispatcher decrypts only the nonce and acknowledges the fixed workflow", async () => {
  const id = "00000000-0000-4000-8000-000000000001", key = btoa("k".repeat(32)), nonce = "n".repeat(43);
  const encrypted = await encryptCredential(nonce, id + ":nonce", key);
  const calls: string[] = [];
  const result = await dispatchPending((name) => {
    calls.push(name);
    return Promise.resolve(
      name === "observer_pending_jobs"
        ? [{
          id,
          kind: "engine",
          organization: "AGENTIC-OBSERVER26-runner-1",
          workflow_sha: "a".repeat(40),
          encrypted_nonce: encrypted,
        }]
        : null,
    );
  }, {
    dispatch: (org, workflow, job, token, sha) => {
      assertEquals([org, workflow, job, token, sha], [
        "AGENTIC-OBSERVER26-runner-1",
        "observer-engine.yml",
        id,
        nonce,
        "a".repeat(40),
      ]);
      calls.push("github");
      return Promise.resolve();
    },
  }, key);
  assertEquals(result, [{ id, dispatched: true }]);
  assertEquals(calls, [
    "observer_reconcile_jobs",
    "observer_reconcile_sessions",
    "observer_pending_jobs",
    "github",
    "observer_mark_dispatched",
  ]);
});

Deno.test("ambiguous dispatch errors retain a recoverable receipt without exposing credentials", async () => {
  const id = "00000000-0000-4000-8000-000000000001", key = btoa("k".repeat(32));
  const encrypted = await encryptCredential("n".repeat(43), id + ":nonce", key);
  const calls: { name: string; args: Record<string, unknown> }[] = [];
  const result = await dispatchPending(
    (name, args) => {
      calls.push({ name, args });
      return Promise.resolve(
        name === "observer_pending_jobs"
          ? [{
            id,
            kind: "execute",
            organization: "AGENTIC-OBSERVER26-runner-1",
            workflow_sha: "a".repeat(40),
            encrypted_nonce: encrypted,
          }]
          : null,
      );
    },
    { dispatch: () => Promise.reject(new GitHubError("github_unavailable")) },
    key,
  );
  assertEquals(result, [{ id, dispatched: false, error: "github_unavailable" }]);
  assertEquals(calls.at(-1), { name: "observer_dispatch_error", args: { p_job: id, p_error: "github_unavailable" } });
});

Deno.test("an organization-level dispatch failure fails the job over to the next best organization", async () => {
  const id = "00000000-0000-4000-8000-000000000001", key = btoa("k".repeat(32)), nonce = "n".repeat(43);
  const encrypted = await encryptCredential(nonce, id + ":nonce", key);
  const calls: { name: string; args: unknown }[] = [];
  const dispatches: string[] = [];
  const result = await dispatchPending(
    (name, args) => {
      calls.push({ name, args });
      if (name === "observer_pending_jobs") {
        return Promise.resolve([{
          id,
          kind: "engine",
          organization: "AGENTIC-OBSERVER26-runner-1",
          workflow_sha: "a".repeat(40),
          encrypted_nonce: encrypted,
        }]);
      }
      if (name === "observer_organizations_by_load") {
        return Promise.resolve([
          { organization: "AGENTIC-OBSERVER26-runner-1", approved_sha: "a".repeat(40), over_limit: false },
          { organization: "AGENTIC-OBSERVER26-runner-2", approved_sha: "b".repeat(40), over_limit: false },
          { organization: "AGENTIC-OBSERVER26-runner-3", approved_sha: "c".repeat(40), over_limit: true },
        ]);
      }
      return Promise.resolve(null);
    },
    {
      dispatch: (org, _workflow, _job, _nonce, sha) => {
        dispatches.push(org + "@" + sha);
        return org === "AGENTIC-OBSERVER26-runner-1"
          ? Promise.reject(new GitHubError("github_request_failed", 403))
          : Promise.resolve();
      },
    },
    key,
  );
  assertEquals(result, [{ id, dispatched: true, failover: "AGENTIC-OBSERVER26-runner-2" }]);
  assertEquals(dispatches, [
    "AGENTIC-OBSERVER26-runner-1@" + "a".repeat(40),
    "AGENTIC-OBSERVER26-runner-2@" + "b".repeat(40),
  ]);
  // runner-1 is excluded as the failed origin and runner-3 as over its minute cap.
  assertEquals(calls.find((c) => c.name === "observer_failover_job")?.args, {
    p_job: id,
    p_organization: "AGENTIC-OBSERVER26-runner-2",
  });
});

Deno.test("without a healthy organization the failed job stays queued for its original organization", async () => {
  const id = "00000000-0000-4000-8000-000000000001", key = btoa("k".repeat(32));
  const encrypted = await encryptCredential("n".repeat(43), id + ":nonce", key);
  const calls: string[] = [];
  const result = await dispatchPending(
    (name) => {
      calls.push(name);
      if (name === "observer_pending_jobs") {
        return Promise.resolve([{
          id,
          kind: "prepare",
          organization: "AGENTIC-OBSERVER26-runner-1",
          workflow_sha: "a".repeat(40),
          encrypted_nonce: encrypted,
        }]);
      }
      if (name === "observer_organizations_by_load") {
        return Promise.resolve([
          { organization: "AGENTIC-OBSERVER26-runner-1", approved_sha: "a".repeat(40), over_limit: false },
          { organization: "AGENTIC-OBSERVER26-runner-2", approved_sha: "b".repeat(40), over_limit: true },
        ]);
      }
      return Promise.resolve(null);
    },
    { dispatch: () => Promise.reject(new GitHubError("organization_not_installed")) },
    key,
  );
  assertEquals(result, [{ id, dispatched: false, error: "organization_not_installed" }]);
  assertEquals(calls.filter((c) => c === "observer_failover_job"), []);
});
