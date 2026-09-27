import { assertEquals } from "@std/assert";
import { decryptCredential } from "./observer-model.ts";
import { placement } from "./observer-github.ts";

// Recorded placement from public.observer_placement; runner-9 is one of the added organizations.
const locate = () => Promise.resolve("AGENTIC-OBSERVER26-runner-9");
import { schedulePreparations } from "./observer-prepare.ts";

const user = "00000000-0000-4000-8000-000000000001";
const revision = "00000000-0000-4000-8000-000000000002";
const modelRun = "00000000-0000-4000-8000-000000000003";
const lease = "00000000-0000-4000-8000-000000000004";
const key = btoa("k".repeat(32));

for (const source_kind of ["repository", "zip"]) {
  Deno.test(
    source_kind + " preparation snapshots source and scopes the model budget without installation secrets",
    async () => {
      const { organization, privateRepository } = await placement(user, locate);
      const privateRepo = {
        id: 42,
        full_name: organization + "/" + privateRepository,
        private: true,
        fork: false,
        default_branch: "main",
      };
      let scheduled: Record<string, any> = {};
      let forks = 0;
      const source_location = source_kind === "repository"
        ? "https://github.com/example/project"
        : user + "/" + revision + "/source.zip";
      const output = await schedulePreparations({
        masterKey: key,
        apiBase: "https://platform.test",
        app: {
          privateParticipantRepository: async (owner) => {
            assertEquals(owner, user);
            return privateRepo;
          },
          forkPublicSource: async (owner, url) => {
            assertEquals([owner, url], [user, source_location]);
            forks++;
            return {
              repository: {
                ...privateRepo,
                full_name: organization + "/source-" + "c".repeat(20),
                private: false,
                fork: true,
              },
              sourceCommit: "d".repeat(40),
              sourceRepository: "example/project",
            };
          },
        },
        rpc: (name, args) => {
          if (name === "observer_placement") return Promise.resolve("AGENTIC-OBSERVER26-runner-9");
          if (name === "observer_runner_configuration") return Promise.resolve([{ organization }]);
          if (name === "observer_pending_preparations") {
            return Promise.resolve([{
              id: revision,
              owner_id: user,
              lease,
              source_kind,
              source_location,
              model_run_id: modelRun,
              model: "qwen-test",
            }]);
          }
          assertEquals(name, "observer_schedule_preparation");
          scheduled = args;
          return Promise.resolve(null);
        },
      });
      assertEquals(output, [{ id: revision, scheduled: true }]);
      assertEquals(scheduled.p_lease, lease);
      const j = scheduled.p_job;
      const input = JSON.parse(await decryptCredential(j.encrypted_input, j.id, key));
      assertEquals(await decryptCredential(j.encrypted_nonce, j.id + ":nonce", key), j.nonce);
      assertEquals(input.repository, { full_name: privateRepo.full_name });
      assertEquals(input.run_credential, "obs_" + modelRun + "." + scheduled.p_participant_token);
      assertEquals(input.model, "qwen-test");
      assertEquals(input.scenario_ref, undefined);
      assertEquals(input.artifact_upload, { kind: "github" });
      assertEquals(input.archive_url, undefined);
      if (source_kind === "repository") {
        assertEquals(forks, 1);
        assertEquals(input.archive_ref, "github:" + organization + "/source-" + "c".repeat(20) + "@" + "d".repeat(40));
      } else {
        assertEquals(forks, 0);
        assertEquals(input.archive_storage_ref, { bucket: "observer-staging", path: source_location });
      }
    },
  );
}

Deno.test("an unavailable source does not open a model session or expose backend diagnostics", async () => {
  const { organization } = await placement(user, locate);
  const calls: string[] = [];
  const output = await schedulePreparations({
    masterKey: key,
    apiBase: "https://platform.test",
    app: {
      privateParticipantRepository: () => Promise.reject(new Error("credential-bearing response")),
      forkPublicSource: () => {
        throw new Error("must not fork");
      },
    },
    rpc: (name, args) => {
      if (name === "observer_placement") return Promise.resolve("AGENTIC-OBSERVER26-runner-9");
      calls.push(name);
      if (name === "observer_runner_configuration") return Promise.resolve([{ organization }]);
      if (name === "observer_pending_preparations") return Promise.resolve([{ id: revision, lease, owner_id: user }]);
      assertEquals(name, "observer_preparation_error");
      assertEquals(args.p_error, "preparation_unavailable");
      return Promise.resolve(null);
    },
  });
  assertEquals(output, [{ id: revision, scheduled: false, error: "preparation_unavailable" }]);
  assertEquals(calls.includes("observer_schedule_preparation"), false);
});
