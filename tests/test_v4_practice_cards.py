"""The v4 practice cards gamma and delta (scripts/build-v4-practice-cards.py):
reproducible, seedless bundles with the published card facts; gamma a medium season,
delta the extreme one (stress events on, no leaked truth in initialize)."""
from __future__ import annotations

import csv
import importlib.util
import json
import time
from pathlib import Path

from challenge import v4_workflow
from test_v4_engine import run_card

ROOT = Path(__file__).resolve().parents[1]


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
