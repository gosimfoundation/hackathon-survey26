"""Bridge from the unchanged trusted Python simulator to the public session API.

This module runs only in the trusted job. It must never be imported by the
participant project or used on the executor host with a hidden scenario mounted.
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

from challenge.challenge_workflow import ChallengeWorkflow
from .session import SessionClient, long_poll_seconds, wait_until
from .scenario_instances import PANEL_VERSION, calibrated_score


def result_summary(result: dict) -> dict:
    """Small database summary; full action/replay evidence stays in private storage."""
    report=result["score_report"]
    completion=report.get("completion",{})
    summary = {
        "schema_version":"observer-run-summary-v1",
        "score":report["score"],
        "completed_tiles":len(completion.get("completed_tiles",[])),
        "required_missing":len(completion.get("required_missing",[])),
        "termination_reason":result["termination_reason"],
        "committed_action_count":result["committed_action_count"],
        "accounted_wallclock_seconds":result["accounted_wallclock_seconds"],
    }
    if "calibration" in result:
        summary["raw_score"] = summary["score"]
        summary["score"] = {"total": result["calibration"]["adjusted_score"]}
        summary["calibration"] = result["calibration"]
    return summary


class RemoteProvider:
    def __init__(self, workflow: ChallengeWorkflow, client: SessionClient, *, startup_seconds: float = 900,
                 evaluation: dict | None = None):
        self.workflow, self.client = workflow, client
        self.startup_seconds = startup_seconds
        self.server_deadline: float | None = None
        self.flushed_sequence = 0
        self.flushed_rows = 0
        self.evaluation = evaluation
        self.initialization_error: Exception | None = None

    def publish_initial(self, publication):
        try:
            self._publish_initial(publication)
        except Exception as error:
            self.initialization_error = error
            raise

    def _publish_initial(self, publication):
        if self.evaluation is not None:
            publication = {**publication, "evaluation": self.evaluation}
        startup = time.monotonic()+self.startup_seconds
        self.client.call("initialize",publication=publication,deadline=startup)
        wait_until(lambda:self.client.call("poll",scope="engine",wait=long_poll_seconds(startup),wait_for="ready",
                                           deadline=startup)["ready"],deadline=startup)
        deadline_at = self.client.call("begin",deadline=startup)
        server_time = datetime.fromisoformat(deadline_at.replace("Z","+00:00"))
        self.server_deadline=time.monotonic()+max(0,(server_time-datetime.now(timezone.utc)).total_seconds())

    def pending_commits(self):
        # Steps the simulator has validated and actually committed but the
        # server has not recorded yet. Includes report rows emitted by that action.
        commits=[]; rows_seen=self.flushed_rows
        for entry in self.workflow.commit_log:
            if not entry["committed"] or entry["sequence"]<=self.flushed_sequence:
                continue
            rows=[item.csv_row() for item in self.workflow.committed[rows_seen:]]
            commits.append({"sequence":entry["sequence"],"committed":{"rows":rows}})
            rows_seen=len(self.workflow.committed)
        return commits

    def _flushed(self,commits):
        if commits:
            self.flushed_rows=len(self.workflow.committed)
            self.flushed_sequence=commits[-1]["sequence"]

    def flush(self):
        for item in self.pending_commits():
            self.client.call("commit",sequence=item["sequence"],committed=item["committed"])
            self._flushed([item])

    def __call__(self,snapshot,deadline_monotonic):
        deadline=min(deadline_monotonic,self.server_deadline or deadline_monotonic)
        commits=self.pending_commits()
        sequence=snapshot["decision_sequence"]
        # One request records the previous step, publishes this one and waits
        # server-side for the answer; retries are idempotent.
        message=self.client.call("advance",commits=commits,sequence=sequence,observation=snapshot,
                                 wait=long_poll_seconds(deadline),wait_for="response",deadline=deadline)
        self._flushed(commits)
        if message["response"]:
            return message["response"]
        return wait_until(lambda:self.client.call("poll",scope="engine",wait=long_poll_seconds(deadline),
                                                  wait_for="response",deadline=deadline)["response"],
                          deadline=deadline,interval=0.02)


class ColocatedProvider:
    """The participant runs in a Docker container on this machine.

    Steps go straight to its stdin instead of through the session database, so
    a public scenario runs at local speed. The protocol is unchanged: one
    observation at a time, the next only after the answer. The session is still
    opened and closed so model proxy quotas, status and scoring work as before.
    """

    def __init__(self, transport, client: SessionClient, participant: SessionClient, *, startup_seconds: float = 900):
        self.transport, self.client, self.participant = transport, client, participant
        self.startup_seconds = startup_seconds
        self.server_deadline: float | None = None
        self.initialization_error: Exception | None = None

    def publish_initial(self, publication):
        try:
            startup = time.monotonic()+self.startup_seconds
            self.client.call("initialize", publication={"transport_format": COLOCATED_FORMAT}, deadline=startup)
            self.transport.publish_initial(publication)
            self.participant.call("ready", deadline=startup)
            deadline_at = self.client.call("begin", deadline=startup)
            server_time = datetime.fromisoformat(deadline_at.replace("Z","+00:00"))
            self.server_deadline=time.monotonic()+max(0,(server_time-datetime.now(timezone.utc)).total_seconds())
        except Exception as error:
            self.initialization_error = error
            raise

    def flush(self):
        pass

    def __call__(self, snapshot, deadline_monotonic):
        return self.transport(snapshot, min(deadline_monotonic, self.server_deadline or deadline_monotonic))


COLOCATED_FORMAT = "observer-colocated-v1"


def run_session(scenario: Path, output: Path, client: SessionClient, *, wallclock_seconds: float | None = None,
                instance_record: dict | None = None, provider=None):
    workflow=ChallengeWorkflow(scenario)
    evaluation = None if instance_record is None else {
        "instance_commitment": instance_record["instance_digest"], "calibration_version": PANEL_VERSION,
        "score_formula": "10000 * (raw_score - wait_score) / (reference_panel_mean - wait_score)",
    }
    if provider is None:
        provider=RemoteProvider(workflow,client,evaluation=evaluation)
    elif instance_record is not None:
        raise ValueError("private instances never run next to the participant")
    result=workflow.run(provider,wallclock_seconds=wallclock_seconds)
    if provider.initialization_error is not None:
        # A failed startup has no scored trace. Preserve the safe transport code
        # instead of uploading an empty result and later reporting run_not_running.
        raise provider.initialization_error
    provider.flush()
    if instance_record is not None:
        difficulty = instance_record["difficulty"]
        result["calibration"] = {
            "version": PANEL_VERSION, "instance_commitment": instance_record["instance_digest"],
            "wait_score": difficulty["wait_score"], "reference_score": difficulty["reference_score"],
            "span": difficulty["span"],
            "adjusted_score": calibrated_score(result["score_report"]["score"]["total"], difficulty),
        }
    workflow.write_outputs(output,result)
    digest=hashlib.sha256((output/"decisions.csv").read_bytes()).hexdigest()
    return result,digest
