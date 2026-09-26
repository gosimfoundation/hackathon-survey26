import { assertEquals, assertNotEquals, assertThrows } from "@std/assert";
import { decryptCredential } from "./observer-model.ts";
import { placement } from "./observer-github.ts";
import { scheduleRuns } from "./observer-orchestrate.ts";
import { validateJobPayload } from "./observer-job.ts";

const key = btoa("k".repeat(32));
const user = "00000000-0000-4000-8000-000000000001";
const run = "00000000-0000-4000-8000-000000000002";
const lease = "00000000-0000-4000-8000-000000000003";

for (const randomized of [false, true]) {
  for (const mode of ["local", "project"]) {
    Deno.test(
      mode + (randomized ? " randomized" : " fixed") +
        " scheduler encrypts separate capabilities and publishes no secrets in receipts",
      async () => {
        const { organization } = await placement(user);
        const manifest = {
          schema_version: "observer-project-v1",
          image: "python@sha256:" + "a".repeat(64),
          run: ["python3", "agent.py"],
        };
        const archive = "github:" + organization + "/participant-" + user.replaceAll("-", "") + "@" + "b".repeat(40);
        const instance = randomized
          ? {
            seed: "f".repeat(64),
            profile_id: lease,
            bundle_digest: "c".repeat(64),
            max_candidates: 32,
            profile: { schema_version: "observer-calibration-profile-v1" },
          }
          : null;
        let scheduled: Record<string, any> = {}, provisioned = false;
        const output = await scheduleRuns({
          masterKey: key,
          apiBase: "https://platform.test",
          ensureRepository: async (owner) => {
            assertEquals(owner, user);
            provisioned = true;
          },
          rpc: (name, args) => {
            if (name === "observer_runner_configuration") return Promise.resolve([{ organization }]);
            if (name === "observer_instance_input") return Promise.resolve(instance);
            if (name === "observer_run_colocated") return Promise.resolve(false);
            if (name === "observer_pending_runs") {
              return Promise.resolve([{
                id: run,
                user_id: user,
                lease,
                mode,
                storage_path: "scenario/bundle.zip",
                scenario_digest: "c".repeat(64),
                runtime_seconds: 3600,
                archive_ref: archive,
                materialized_digest: "d".repeat(64),
                manifest,
              }]);
            }
            assertEquals(name, "observer_schedule_run");
            assertEquals(provisioned, true);
            scheduled = args;
            return Promise.resolve(null);
          },
        });
        assertEquals(output, [{ id: run, scheduled: true }]);
        assertEquals(JSON.stringify(output).includes("f".repeat(64)), false);
        assertEquals(scheduled.p_organization, organization);
        assertEquals(scheduled.p_lease, lease);
        assertNotEquals(scheduled.p_participant_token, scheduled.p_engine_token);
        assertEquals(scheduled.p_jobs.length, mode === "local" ? 1 : 2);
        for (const job of scheduled.p_jobs) {
          assertEquals(await decryptCredential(job.encrypted_nonce, job.id + ":nonce", key), job.nonce);
          const input = JSON.parse(await decryptCredential(job.encrypted_input, job.id, key));
          assertEquals(input.job_id, job.id);
          assertEquals(input.run_id, run);
          if (job.kind === "engine") {
            assertEquals(input.instance, instance ?? undefined);
            assertEquals(input.run_credential, "obs_" + run + "." + scheduled.p_engine_token);
            assertEquals(input.scenario_ref, { bucket: "observer-scenarios", path: "scenario/bundle.zip" });
            assertEquals(input.archive_ref, undefined);
            delete input.scenario_ref;
            input.scenario_url = "https://storage.test/fresh.zip";
          } else {
            assertEquals(input.instance, undefined);
            assertEquals(input.run_credential, "obs_" + run + "." + scheduled.p_participant_token);
            assertEquals(input.archive_ref, archive);
            assertEquals(input.scenario_ref, undefined);
            assertEquals(input.scenario_digest, undefined);
            delete input.archive_ref;
            input.archive_url = "https://codeload.github.com/fresh.zip";
          }
          validateJobPayload(input, {
            organization,
            organizationId: "101",
            repositoryId: "303",
            approvedSha: "e".repeat(40),
            workflow: job.kind === "engine" ? "observer-engine.yml" : "observer-execute.yml",
          }, job.id);
          if (job.kind === "execute" && instance) {
            assertThrows(() =>
              validateJobPayload({ ...input, instance }, {
                organization,
                organizationId: "101",
                repositoryId: "303",
                approvedSha: "e".repeat(40),
                workflow: "observer-execute.yml",
              }, job.id)
            );
          }
        }
        if (mode === "local") {
          assertEquals(
            await decryptCredential(scheduled.p_local_credential, run + ":local", key),
            "obs_" + run + "." + scheduled.p_participant_token,
          );
        } else assertEquals(scheduled.p_local_credential, null);
      },
    );
  }
}

Deno.test("unconfigured deployments do not consume retries; provisioning failures never open a session", async () => {
  const { organization } = await placement(user);
  const calls: string[] = [];
  const disabled = await scheduleRuns({
    masterKey: key,
    apiBase: "https://platform.test",
    ensureRepository: () => {
      throw new Error("must not provision");
    },
    rpc: (name) => {
      calls.push(name);
      return Promise.resolve([]);
    },
  });
  assertEquals(disabled, []);
  assertEquals(calls, ["observer_runner_configuration"]);
  calls.length = 0;
  const output = await scheduleRuns({
    masterKey: key,
    apiBase: "https://platform.test",
    ensureRepository: () => {
      throw new Error("sensitive installation error");
    },
    rpc: (name, args) => {
      calls.push(name);
      if (name === "observer_runner_configuration") return Promise.resolve([{ organization }]);
      if (name === "observer_pending_runs") return Promise.resolve([{ id: run, user_id: user, lease, mode: "local" }]);
      assertEquals(name, "observer_run_schedule_error");
      assertEquals(args, { p_run: run, p_lease: lease, p_error: "schedule_unavailable" });
      return Promise.resolve(null);
    },
  });
  assertEquals(output, [{ id: run, scheduled: false, error: "schedule_unavailable" }]);
  assertEquals(calls.includes("observer_schedule_run"), false);
});

Deno.test("a final formal run whose instance lookup is refused is never scheduled", async () => {
  const { organization } = await placement(user);
  const calls: string[] = [];
  const output = await scheduleRuns({
    masterKey: key,
    apiBase: "https://platform.test",
    ensureRepository: async () => {},
    rpc: (name, args) => {
      calls.push(name);
      if (name === "observer_runner_configuration") return Promise.resolve([{ organization }]);
      if (name === "observer_pending_runs") {
        return Promise.resolve([{ id: run, user_id: user, lease, mode: "project" }]);
      }
      // observer_instance_input raises formal_instance_missing instead of returning NULL.
      if (name === "observer_instance_input") return Promise.reject(new Error("formal_instance_missing"));
      assertEquals(name, "observer_run_schedule_error");
      assertEquals(args, { p_run: run, p_lease: lease, p_error: "schedule_unavailable" });
      return Promise.resolve(null);
    },
  });
  assertEquals(output, [{ id: run, scheduled: false, error: "schedule_unavailable" }]);
  assertEquals(calls.includes("observer_schedule_run"), false);
});

Deno.test("a colocated public run gets one engine job that also starts the participant", async () => {
  const { organization } = await placement(user);
  const manifest = {
    schema_version: "observer-project-v1",
    image: "python@sha256:" + "a".repeat(64),
    run: ["python3", "agent.py"],
  };
  const archive = "github:" + organization + "/participant-" + user.replaceAll("-", "") + "@" + "b".repeat(40);
  let scheduled: Record<string, any> = {};
  const output = await scheduleRuns({
    masterKey: key,
    apiBase: "https://platform.test",
    ensureRepository: async () => {},
    rpc: (name, args) => {
      if (name === "observer_runner_configuration") return Promise.resolve([{ organization }]);
      if (name === "observer_instance_input") return Promise.resolve(null);
      if (name === "observer_run_colocated") return Promise.resolve(true);
      if (name === "observer_pending_runs") {
        return Promise.resolve([{
          id: run,
          user_id: user,
          lease,
          mode: "project",
          storage_path: "scenario/bundle.zip",
          scenario_digest: "c".repeat(64),
          runtime_seconds: 3600,
          archive_ref: archive,
          materialized_digest: "d".repeat(64),
          manifest,
        }]);
      }
      scheduled = args;
      return Promise.resolve(null);
    },
  });
  assertEquals(output, [{ id: run, scheduled: true }]);
  assertEquals(scheduled.p_jobs.map((job: { kind: string }) => job.kind), ["engine"]);
  const job = scheduled.p_jobs[0];
  const input = JSON.parse(await decryptCredential(job.encrypted_input, job.id, key));
  assertEquals(input.archive_ref, archive);
  assertEquals(input.colocated.run_credential, "obs_" + run + "." + scheduled.p_participant_token);
  assertEquals(input.run_credential, "obs_" + run + "." + scheduled.p_engine_token);
  assertEquals(input.colocated.source_digest, "d".repeat(64));
});
