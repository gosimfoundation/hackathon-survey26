import { assert, assertEquals, assertRejects, assertThrows } from "@std/assert";
import { createLocalJWKSet, exportJWK, exportPKCS8, generateKeyPair, SignJWT } from "npm:jose@6.1.0";
import {
  CONTROL_REPOSITORY,
  GitHubApp,
  GitHubError,
  isRunnerOrganization,
  placement,
  sourceRepository,
  verifyWorkflowIdentity,
} from "./observer-github.ts";
import type { WorkflowIdentity } from "./observer-github.ts";

const user = "00000000-0000-4000-8000-000000000001";
const locate = () => Promise.resolve("AGENTIC-OBSERVER26-runner-12");
const assigned = await placement(user, locate);
const organization = assigned.organization;
const pair = await generateKeyPair("RS256", { extractable: true });
const pem = await exportPKCS8(pair.privateKey);
const publicJwk = { ...await exportJWK(pair.publicKey), kid: "test-key", alg: "RS256" };
const keys = createLocalJWKSet({ keys: [publicJwk] });
const sha = "a".repeat(40);

function backend() {
  const calls: { method: string; path: string; body: any; authorization: string }[] = [];
  const repos = new Map<string, any>();
  const permissions = new Map<string, boolean>();
  let suspended = false;
  let installAccount = organization;
  let branchSha = sha;
  let tagSha: string | null = null;
  const app = new GitHubApp("42", pem, { [organization]: 100 }, locate, async (input, init) => {
    const url = new URL(String(input));
    assertEquals(url.origin, "https://api.github.com");
    const path = url.pathname;
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    const authorization = new Headers(init?.headers).get("authorization") ?? "";
    calls.push({ method, path, body, authorization });
    if (path === "/app/installations/100") {
      return Response.json({
        account: { login: installAccount },
        app_id: 42,
        suspended_at: suspended ? "2026-01-01" : null,
      });
    }
    if (path === "/app/installations/100/access_tokens") {
      return Response.json({
        token: "installation-secret",
        expires_at: new Date(Date.now() + 3600000).toISOString(),
      });
    }
    assertEquals(authorization, "Bearer installation-secret");
    if (path === "/orgs/" + organization + "/repos" && method === "POST") {
      const repo = {
        id: 1000,
        full_name: organization + "/" + body.name,
        private: body.private,
        fork: false,
        default_branch: "main",
      };
      repos.set(repo.full_name, repo);
      return Response.json(repo, { status: 201 });
    }
    const full = path.split("/").slice(2, 4).join("/");
    if (path.endsWith("/actions/permissions")) {
      if (method === "PUT") {
        permissions.set(full, body.enabled);
        return new Response(null, { status: 204 });
      }
      return Response.json({ enabled: permissions.get(full) ?? true });
    }
    if (path.endsWith("/commits/main")) return Response.json({ sha: branchSha });
    if (path.includes("/commits/observer-runtime-")) return tagSha
      ? Response.json({sha:tagSha}) : Response.json({message:"not found"},{status:404});
    if (path.endsWith("/forks") && method === "POST") {
      const original = repos.get(full);
      const repo = {
        id: 1001,
        full_name: body.organization + "/" + body.name,
        private: false,
        fork: true,
        parent: { id: original.id },
        default_branch: "main",
      };
      repos.set(repo.full_name, repo);
      return Response.json(repo, { status: 202 });
    }
    if (path.includes("/zipball/")) {
      return new Response(null, {
        status: 302,
        headers: { location: "https://codeload.github.com/" + full + "/legacy.zip/" + sha },
      });
    }
    if (path.endsWith("/dispatches")) return new Response(null, { status: 204 });
    return repos.has(full) ? Response.json(repos.get(full)) : Response.json({ message: "not found" }, { status: 404 });
  });
  return {
    app,
    calls,
    repos,
    permissions,
    suspend: () => suspended = true,
    wrongAccount: () => installAccount = "outsider",
    wrongBranch: () => branchSha = "b".repeat(40),
    tag: (value: string) => tagSha=value,
  };
}

Deno.test("placement uses the recorded organization and accepts only runner organizations 1-99", async () => {
  assertEquals(await placement(user, locate), assigned);
  assertEquals(assigned.organization, "AGENTIC-OBSERVER26-runner-12");
  assertEquals(assigned.privateRepository, "participant-" + user.replaceAll("-", ""));
  await assertRejects(() => placement("../../secret", locate), GitHubError);
  const asked: string[] = [];
  await placement(user.toUpperCase(), (id) => {
    asked.push(id);
    return Promise.resolve("AGENTIC-OBSERVER26-runner-1");
  });
  assertEquals(asked, [user]);
  for (const answer of ["AGENTIC-OBSERVER26-runner-100", "AGENTIC-OBSERVER26-runner-0", "outsider", null, 7]) {
    await assertRejects(() => placement(user, () => Promise.resolve(answer)), GitHubError, "invalid_placement");
  }
  await assertRejects(
    () => placement(user, () => Promise.reject(new Error("database detail"))),
    GitHubError,
    "placement_unavailable",
  );
  for (const i of [1, 7, 12, 13, 36, 99]) assert(isRunnerOrganization("AGENTIC-OBSERVER26-runner-" + i));
  for (
    const name of [
      "AGENTIC-OBSERVER26-runner-100",
      "AGENTIC-OBSERVER26-runner-0",
      "AGENTIC-OBSERVER26-runner-01",
      "AGENTIC-OBSERVER26-runner-1x",
    ]
  ) {
    assert(!isRunnerOrganization(name));
  }
});

Deno.test("only canonical GitHub repository links enter the ingestion queue", () => {
  assertEquals(sourceRepository("https://github.com/example/project.git/"), "example/project");
  for (
    const url of [
      "http://github.com/a/b",
      "https://github.com.evil.test/a/b",
      "https://x:y@github.com/a/b",
      "https://github.com/a/b/tree/main",
      "https://github.com/a/b?download=1",
      "https://github.com/a/%2e%2e",
    ]
  ) {
    assertThrows(() => sourceRepository(url), GitHubError);
  }
});

Deno.test("installation identity is verified before using its token", async () => {
  for (const change of ["wrongAccount", "suspend"] as const) {
    const f = backend();
    f[change]();
    await assertRejects(() => f.app.privateParticipantRepository(user), GitHubError);
    assert(!f.calls.some((c) => c.path.endsWith("/access_tokens")));
  }
});

Deno.test("private repository provisioning is idempotent and disables source workflows", async () => {
  const f = backend();
  const first = await f.app.privateParticipantRepository(user);
  const again = await f.app.privateParticipantRepository(user);
  assertEquals(first, again);
  assertEquals(first.private, true);
  assertEquals(f.permissions.get(first.full_name), false);
  assertEquals(f.calls.filter((c) => c.path.endsWith("/repos") && c.method === "POST").length, 1);
  assertEquals(f.calls.filter((c) => c.path.endsWith("/access_tokens")).length, 1);
});

Deno.test("a preexisting public or forked repository cannot hold private evidence", async () => {
  for (const fields of [{ private: false, fork: false }, { private: true, fork: true }]) {
    const f = backend();
    f.repos.set(organization + "/" + assigned.privateRepository, {
      id: 1,
      full_name: organization + "/" + assigned.privateRepository,
      ...fields,
    });
    await assertRejects(() => f.app.privateParticipantRepository(user), GitHubError);
  }
});

Deno.test("forking fixes source commit before fork and keeps participant workflows disabled", async () => {
  const f = backend();
  f.repos.set("example/project", {
    id: 72,
    full_name: "example/project",
    private: false,
    fork: false,
    default_branch: "main",
  });
  const result = await f.app.forkPublicSource(user, "https://github.com/example/project");
  assertEquals(result.sourceCommit, sha);
  assertEquals(result.sourceRepository, "example/project");
  assertEquals(result.repository.private, false);
  assertEquals(f.permissions.get(result.repository.full_name), false);
  const read = f.calls.findIndex((c) => c.path === "/repos/example/project/commits/main");
  const fork = f.calls.findIndex((c) => c.path === "/repos/example/project/forks");
  assert(read >= 0 && fork > read);
});

Deno.test("private links require an authorized ZIP instead of exposing a source fork", async () => {
  const f = backend();
  f.repos.set("example/project", { id: 72, private: true, default_branch: "main" });
  await assertRejects(
    () => f.app.forkPublicSource(user, "https://github.com/example/project"),
    GitHubError,
    "private_source_requires_zip",
  );
  assert(!f.calls.some((c) => c.path.endsWith("/forks")));
});

Deno.test("only approved private control workflow commits may be dispatched", async () => {
  const f = backend();
  f.repos.set(organization + "/" + CONTROL_REPOSITORY, { id: 10, private: true, fork: false });
  await f.app.dispatch(organization, "observer-execute.yml", user, "x".repeat(43), sha);
  assertEquals(f.calls.at(-1)?.body, { ref: "main", inputs: { job_id: user, job_nonce: "x".repeat(43) } });
  // Only a fallback dispatch names the runner pool; older runtimes reject unknown inputs.
  await f.app.dispatch(organization, "observer-execute.yml", user, "x".repeat(43), sha, "self-hosted");
  assertEquals(f.calls.at(-1)?.body, {
    ref: "main",
    inputs: { job_id: user, job_nonce: "x".repeat(43), runner: "self-hosted" },
  });
  f.wrongBranch();
  await assertRejects(
    () => f.app.dispatch(organization, "observer-engine.yml", user, "x".repeat(43), sha),
    GitHubError,
  );
  assertEquals(f.calls.filter((c) => c.path.endsWith("/dispatches")).length, 2);
});

Deno.test("archive redirects return only codeload destinations without forwarding installation secrets", async () => {
  const f = backend();
  const url = await f.app.archiveDownload(organization, assigned.privateRepository, sha);
  assert(url.startsWith("https://codeload.github.com/"));
  assert(!url.includes("installation-secret"));
  assertEquals(f.calls.filter((c) => c.path.includes("/zipball/")).length, 1);
});

Deno.test("queued runtime releases survive a main update but a moved tag is rejected",async()=>{
  const f=backend();f.repos.set(organization+"/"+CONTROL_REPOSITORY,{id:10,private:true,fork:false});
  f.tag(sha);f.wrongBranch();
  await f.app.dispatch(organization,"observer-engine.yml",user,"x".repeat(43),sha);
  assertEquals(f.calls.at(-1)?.body.ref,"observer-runtime-"+sha);
  f.tag("b".repeat(40));
  await assertRejects(()=>f.app.dispatch(organization,"observer-engine.yml",user,"x".repeat(43),sha),GitHubError);
});

const expected: WorkflowIdentity = {
  organization,
  repositoryId: "123",
  organizationId: "456",
  workflow: "observer-engine.yml",
  approvedSha: sha,
  runId: "789",
  runAttempt: "1",
};
const claims = {
  repository_id: "123",
  repository_owner_id: "456",
  repository: organization + "/" + CONTROL_REPOSITORY,
  repository_visibility: "private",
  workflow_ref: organization + "/" + CONTROL_REPOSITORY + "/.github/workflows/observer-engine.yml@refs/heads/main",
  workflow_sha: sha,
  sha,
  ref: "refs/heads/main",
  event_name: "workflow_dispatch",
  run_id: "789",
  run_attempt: "1",
};
async function signed(overrides: Record<string, unknown> = {}, audience = "agentic-observer26") {
  return await new SignJWT({ ...claims, ...overrides }).setProtectedHeader({ alg: "RS256", kid: "test-key" })
    .setIssuedAt().setExpirationTime("5m").setIssuer("https://token.actions.githubusercontent.com")
    .setAudience(audience).setJti(crypto.randomUUID()).setSubject(
      "repo:" + organization + "/" + CONTROL_REPOSITORY + ":ref:refs/heads/main",
    )
    .sign(pair.privateKey);
}

Deno.test("OIDC validates signature, audience and exact trusted workflow identity", async () => {
  const verified = await verifyWorkflowIdentity(await signed(), expected, keys);
  assertEquals(verified.runId, "789");
  await assertRejects(
    async () => verifyWorkflowIdentity(await signed({}, "different-service"), expected, keys),
    GitHubError,
  );
});

Deno.test("release OIDC requires the exact approved tag and workflow commit",async()=>{
  const ref="refs/tags/observer-runtime-"+sha;
  const workflow_ref=organization+"/"+CONTROL_REPOSITORY+"/.github/workflows/observer-engine.yml@"+ref;
  assertEquals((await verifyWorkflowIdentity(await signed({ref,workflow_ref}),expected,keys)).runId,"789");
  await assertRejects(async()=>verifyWorkflowIdentity(await signed({ref:ref+"x",workflow_ref}),expected,keys),GitHubError);
  await assertRejects(async()=>verifyWorkflowIdentity(await signed({ref,workflow_ref,sha:"b".repeat(40)}),expected,keys),GitHubError);
});

Deno.test("a valid GitHub signature from another repo, workflow, ref or attempt cannot claim a job", async () => {
  for (
    const invalid of [
      { repository_id: "999" },
      { repository_owner_id: "999" },
      { repository_visibility: "public" },
      { workflow_sha: "b".repeat(40) },
      { sha: "b".repeat(40) },
      { ref: "refs/pull/1/merge" },
      { event_name: "pull_request_target" },
      { workflow_ref: organization + "/" + CONTROL_REPOSITORY + "/.github/workflows/participant.yml@refs/heads/main" },
      { run_id: "other" },
      { run_attempt: "2" },
    ]
  ) {
    await assertRejects(async () => verifyWorkflowIdentity(await signed(invalid), expected, keys), GitHubError);
  }
});
