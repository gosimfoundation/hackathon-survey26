"""The v4 practice cards gamma and delta (scripts/build-v4-practice-cards.py):
reproducible, seedless bundles with the published card facts; gamma a medium season,
delta the extreme one (stress events on, no leaked truth in initialize)."""
from __future__ import annotations

import csv
import importlib.util
import json
import math
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from challenge import v4_workflow
from challenge.tile_geometry_simulator import _local_sidereal_deg
from test_v4_engine import run_card

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "starter_kit_v4"


def _script():
    spec = importlib.util.spec_from_file_location("build_v4_practice_cards", ROOT / "scripts" / "build-v4-practice-cards.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_both_cards_are_reproducible_and_seedless(tmp_path):
    module = _script()
    for name, spec in module.PRACTICE_SPECS.items():
        first = module.build_card_bundle(tmp_path / f"{name}-one", spec)
        second = module.build_card_bundle(tmp_path / f"{name}-two", spec)
        assert module.pack(first) == module.pack(second), name
        for path in first.rglob("*.json"):
            assert '"seed"' not in path.read_text(encoding="utf-8"), path
        assert not list(first.rglob("*summary*"))


def test_card_facts_match_the_task_card_pages(tmp_path):
    module = _script()
    facts = {name: module.describe(module.build_card_bundle(tmp_path / name, spec), spec)
             for name, spec in module.PRACTICE_SPECS.items()}
    gamma, delta = facts["v4-gamma"], facts["v4-delta"]
    # web/src/content/taskcard.gamma.v4.*.md
    assert (gamma["first_night"], gamma["last_night"], gamma["nights"]) == ("2026-11-08", "2026-12-12", 35)
    assert (gamma["targets"], gamma["required"], gamma["regions"]) == (9600, 480, 3)
    # web/src/content/taskcard.delta.v4.*.md
    assert (delta["first_night"], delta["last_night"], delta["nights"]) == ("2026-12-20", "2027-01-23", 35)
    assert (delta["targets"], delta["required"], delta["regions"]) == (9800, 490, 3)
    for card in (gamma, delta):
        assert card["global_wallclock_seconds"] == 900 and card["contract"] == "v4-score-v1"
    # Medium vs extreme: gamma has no stress rows and few closed slots; delta is the brutal season.
    assert gamma["stress_events"] == [] and not (tmp_path / "v4-gamma" / "truth" / "v4_stress_events.csv").exists()
    assert sorted(delta["stress_events"]) == ["data_loss", "pointing_offset"]
    assert 0 < gamma["closed_slots"] < delta["closed_slots"]
    assert delta["closed_slots"] > 0.2 * delta["slots"]
    with (tmp_path / "v4-delta" / "truth" / "v4_stress_events.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert all('"seed"' not in json.dumps(row) for row in rows)


def test_delta_hides_its_stress_truth_from_the_agent(tmp_path):
    module = _script()
    bundle = module.build_card_bundle(tmp_path / "delta", module.PRACTICE_SPECS["v4-delta"])
    workflow = v4_workflow.V4Workflow(bundle)
    assert workflow.wallclock_budget(None) == 900
    init = workflow.initialize_payload(900)
    assert init["task_card"] == {"card_id": "delta", "scenario_slug": "v4-delta", "phase": "practice-projects"}
    text = json.dumps(init)
    for hidden in ("is_observable", "seed", "instrument_fault", "instrument_efficiency",
                   "stress", "rocket_launch", "terrain_obstruction"):
        assert hidden not in text, hidden


def test_the_extreme_card_still_runs_end_to_end(tmp_path):
    import os
    module = _script()
    bundle = module.build_card_bundle(tmp_path / "delta", module.PRACTICE_SPECS["v4-delta"])
    started = time.monotonic()
    result, *_ = run_card(bundle, tmp_path / "out", wallclock_seconds=900,
                          env={"PATH": os.environ["PATH"]})
    assert result["termination_reason"] in ("survey_complete", "agent_finished")
    # The 900 s cap is far away even for a trivial agent on the longest, nastiest season.
    assert time.monotonic() - started < 300
    report = result["score_report"]
    assert report["counts"]["observe_actions"] > 0


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def test_every_region_is_up_at_night(tmp_path):
    """The regions follow the season: in mid-night sky, not where the October reference put them
    (a December card built on those centres left a region set at dusk, and its required targets
    were lost whatever the strategy)."""
    module = _script()
    for name, spec in module.PRACTICE_SPECS.items():
        bundle = module.build_card_bundle(tmp_path / name, spec)
        scenario = json.loads((bundle / "config" / "v4_scenario.json").read_text(encoding="utf-8"))
        longitude = scenario["site"]["longitude_deg"]
        with (bundle / "public" / "v4_night_calendar.csv").open() as handle:
            mids = [_local_sidereal_deg(_utc(r["observing_start_utc"]) + (_utc(r["observing_end_utc"]) - _utc(r["observing_start_utc"])) / 2,
                                        longitude) for r in csv.DictReader(handle)]
        regions = defaultdict(list)
        with (bundle / "public" / "footprint.csv").open() as handle:
            for row in csv.DictReader(handle):
                regions[row["component_id"]].append(math.radians(float(row["ra_deg"])))
        assert len(regions) == 3, name
        for component, ras in regions.items():
            ra = math.degrees(math.atan2(sum(map(math.sin, ras)), sum(map(math.cos, ras))))
            hour_angles = sorted(abs((mid - ra + 180.0) % 360.0 - 180.0) for mid in mids)
            assert hour_angles[len(hour_angles) // 2] < 60.0, (name, component, hour_angles[len(hour_angles) // 2])


def _baseline(card: Path, out: Path) -> dict:
    proc = subprocess.run([sys.executable, "-B", str(KIT / "local_runner.py"), "--card", str(card), "--out", str(out), "--quiet"],
                          cwd=str(KIT), capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout)


def test_starter_kit_baseline_difficulty(tmp_path):
    """The practice set gets harder card by card. The kit baseline ends both seasons with a positive
    score, delta (the extreme one) below gamma, and delta still leaves required targets on the table
    for a better strategy. Its data loss fires and the baseline recovers from the state_resync."""
    module = _script()
    runs = {}
    for name, spec in module.PRACTICE_SPECS.items():
        runs[name] = _baseline(module.build_card_bundle(tmp_path / name, spec), tmp_path / f"{name}-out")
        assert runs[name]["termination_reason"] == "survey_complete", name
        assert runs[name]["wall_seconds"] < 300, name
    gamma, delta = runs["v4-gamma"], runs["v4-delta"]
    assert 0 < delta["total"] < gamma["total"]
    assert delta["required_missing"] >= 20
    report = json.loads((tmp_path / "v4-delta-out" / "score_report.json").read_text(encoding="utf-8"))
    assert report["invalidations"] and report["invalidations"][0]["invalidated_observations"] > 0
    assert "state_resync:" in (tmp_path / "v4-delta-out" / "agent.log").read_text(encoding="utf-8")
