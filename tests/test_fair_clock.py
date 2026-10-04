"""Fair clock (challenge/fair_clock.py): normalized think time, engine time free, hard cap."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from challenge import fair_clock, v4_workflow
from challenge.fair_clock import FairClock, SpeedGauge, container_name
from project_platform.trusted_engine import DockerAgent, agent_hooks
from project_platform.transport import JsonlTransport
from v4_support import build_bundle

AGENT = Path(__file__).resolve().parent / "fixtures" / "v4_fake_agent.py"


class Fake:
    """A settable clock and CPU counter."""

    def __init__(self):
        self.now, self.used, self.events = 100.0, 0.0, []

    def clock(self):
        return self.now

    def cpu(self):
        return self.used

    def pause(self):
        self.events.append("pause")

    def resume(self):
        self.events.append("resume")


def fixed(factor):
    return SpeedGauge(reference=1.0, measure=lambda: factor)


def test_gauge_is_a_robust_median_of_recent_samples():
    values = iter([0.25] * 5 + [0.25, 2.5, 0.25] + [0.5, 0.5])
    gauge = SpeedGauge(reference=0.25, measure=lambda: next(values))
    assert gauge.factor == 1.0
    assert gauge.sample(5) == 1.0
    assert gauge.sample(3) == 1.0          # one slow outlier of three does not move the sample
    assert gauge.sample(1) == 1.0          # window 0.25, 0.25, 0.5: median unchanged
    assert gauge.sample(1) == 1.5          # window 0.25, 0.25, 0.5, 0.5: the machine slowed down
    assert fair_clock.REFERENCE_UNIT_SECONDS > 0 and 0.01 < fair_clock.time_unit() < 30


def test_turn_charges_computing_by_speed_and_waiting_one_to_one():
    fake = Fake()
    clock = FairClock(900, gauge=fixed(2.0), clock=fake.clock, cpu=fake.cpu)
    clock.calibrate()
    clock.agent_started()
    clock.begin_turn()
    fake.now += 10; fake.used += 10                 # 10 s computing on a machine 2x slower
    assert clock.end_turn() == pytest.approx(5.0)
    fake.now += 30                                  # engine simulates: free
    clock.begin_turn()
    fake.now += 10                                  # 10 s waiting (model API)
    assert clock.end_turn() == pytest.approx(10.0)
    view = clock.snapshot()
    assert view["normalized_remaining_seconds"] == pytest.approx(885.0)
    assert view["remaining_seconds"] == pytest.approx(1770.0)   # real seconds of this machine
    assert view["speed_factor"] == 2.0
    two_threads = FairClock(900, gauge=fixed(1.0), clock=fake.clock, cpu=fake.cpu)
    two_threads.agent_started(); two_threads.begin_turn()
    fake.now += 4; fake.used += 8                   # parallel work never costs more than the turn
    assert two_threads.end_turn() == pytest.approx(4.0)


def test_background_computing_between_turns_is_charged():
    fake = Fake()
    clock = FairClock(900, gauge=fixed(0.5), clock=fake.clock, cpu=fake.cpu)
    clock.calibrate(); clock.agent_started()
    fake.now += 3; fake.used += 2                   # reading initialize before the first request
    clock.begin_turn()
    assert clock.charged == pytest.approx(4.0)       # 2 CPU s on a 2x faster machine
    fake.now += 1; fake.used += 1
    clock.end_turn()
    fake.now += 5; fake.used += 5                   # keeps computing while the engine simulates
    clock.begin_turn()
    assert clock.charged == pytest.approx(4.0 + 2.0 + 10.0)
    assert clock.summary()["background_seconds"] == pytest.approx(7.0)


def test_without_a_cpu_meter_every_turn_second_counts_as_computing():
    fake = Fake()
    clock = FairClock(100, gauge=fixed(4.0), clock=fake.clock)
    clock.calibrate(); clock.agent_started(); clock.begin_turn()
    fake.now += 40
    assert clock.end_turn() == pytest.approx(10.0)
    assert clock.summary()["cpu_meter"] == "none"


def test_speed_is_resampled_with_the_agent_frozen_and_the_hard_cap_holds():
    fake = Fake()
    clock = FairClock(100, gauge=fixed(1.0), clock=fake.clock, cpu=fake.cpu, pause=fake.pause,
                      resume=fake.resume, interval=60)
    clock.calibrate(); clock.agent_started(); clock.begin_turn(); clock.end_turn()
    fake.now += 61
    clock.begin_turn(); clock.end_turn()
    assert fake.events == ["pause", "resume"] and clock.summary()["speed_samples"] == 2
    assert clock.turn_deadline() == pytest.approx(fake.now + 100)
    fake.now = clock.started + 299
    assert not clock.expired and clock.turn_deadline() == pytest.approx(fake.now + 1)
    fake.now += 1
    assert clock.expired


def test_container_name_and_hooks():
    command = ["docker", "run", "--rm", "--name", "observer-0123abcd", "img", "-c", "exec x"]
    assert container_name(command) == "observer-0123abcd"
    assert container_name(["python3", "agent.py", "--name", "x"]) is None
    assert isinstance(agent_hooks(type("T", (), {"command": command})()), DockerAgent)


def run_fake(bundle, out, mode, factor, budget):
    transport = JsonlTransport([sys.executable, "-u", str(AGENT), mode], cwd=out.parent,
                               environment={"PATH": os.environ["PATH"]})
    transport.protocol_version = v4_workflow.PROTOCOL_VERSION

    def decide(message, deadline):
        transport.send(message, deadline)
        return transport.receive(deadline)
    try:
        return v4_workflow.V4Workflow(bundle).run(
            decide, out, wallclock_seconds=budget, initialize=transport.publish_initial,
            agent_hooks=agent_hooks(transport), speed_gauge=fixed(factor))
    finally:
        transport.close(force=True)


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    return build_bundle(tmp_path_factory.mktemp("fair") / "bundle", card_id="A")


metered = pytest.mark.skipif(not (sys.platform.startswith("linux") or sys.platform == "darwin"),
                             reason="CPU meter on Linux and macOS only")


@metered
def test_engine_end_to_end_compute_and_wait(bundle, tmp_path):
    # Computing is metered and charged; the run ends when the normalized budget is spent.
    spin = run_fake(bundle, tmp_path / "spin", "spin", 0.5, 2)
    assert spin["termination_reason"] == "global_wallclock_expired"
    assert spin["fair_clock"]["cpu_meter"] == "cpu" and spin["accounted_wallclock_seconds"] == 2
    # Waiting (1 s per request, like a model call) counts one to one, however slow the
    # machine (factor 4): a 3 s budget lasts three requests, not twelve.
    nap = run_fake(bundle, tmp_path / "nap", "nap", 4.0, 3)
    assert nap["termination_reason"] == "global_wallclock_expired"
    assert 3 <= nap["decision_requests"] <= 4 and nap["fair_clock"]["busy_seconds"] < 0.5
    # A hung agent ends at the hard cap (3 x budget) at the latest.
    idle = run_fake(bundle, tmp_path / "idle", "sleep", 4.0, 2)
    assert idle["termination_reason"] == "global_wallclock_expired" and idle["fair_clock"]["hard_cap_reached"]
    assert idle["fair_clock"]["run_wall_seconds"] <= 6.5


@metered
def test_engine_charges_background_threads(bundle, tmp_path):
    honest = run_fake(bundle, tmp_path / "greedy", "greedy", 1.0, 30)
    assert honest["termination_reason"] in ("survey_complete", "agent_finished")
    sneaky = run_fake(bundle, tmp_path / "background", "background", 1.0, 2)
    assert sneaky["termination_reason"] == "global_wallclock_expired"
    assert sneaky["fair_clock"]["background_seconds"] > 0


def test_initialize_and_requests_carry_the_clock(bundle, tmp_path):
    result = run_fake(bundle, tmp_path / "view", "finish-after:2", 1.25, 60)
    assert result["speed_factor"] == 1.25 and result["fair_clock"]["schema_version"] == "fair-clock-v1"
    payload = v4_workflow.V4Workflow(bundle).initialize_payload(60, 1.25)
    assert payload["limits"]["clock"] == "fair-clock-v1" and payload["limits"]["speed_factor"] == 1.25
    view = v4_workflow.V4Workflow.request_message(1, {}, FairClock(60, gauge=fixed(1.25)).snapshot())
    assert set(view["payload"]["wallclock"]) == {"elapsed_seconds", "remaining_seconds", "speed_factor",
                                                 "normalized_elapsed_seconds", "normalized_remaining_seconds"}
