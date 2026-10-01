"""The v4 practice cards (Playground α β γ δ, cards/v4-practice-*/spec): bundles built by
scripts/build-v4-practice-cards.py are reproducible and seedless, agree with their spec and their
card page, keep their truth out of `initialize`, and run end to end."""
from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

from challenge import v4_workflow
from test_v4_engine import run_card

ROOT = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("build_v4_practice_cards", ROOT / "scripts" / "build-v4-practice-cards.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _script()
SPECS = MODULE.spec_dirs()


@pytest.fixture(scope="module")
def bundles(tmp_path_factory) -> dict[str, Path]:
    out = tmp_path_factory.mktemp("practice")
    return {slug: MODULE.build_spec_bundle(out / slug, spec) for slug, spec in SPECS.items()}


def test_four_practice_cards_alpha_to_delta():
    cards = {slug: MODULE.load_spec(spec)["card"] for slug, spec in SPECS.items()}
    assert sorted(cards) == ["v4-practice-a", "v4-practice-b", "v4-practice-c", "v4-practice-d"]
    assert [card["card_id"] for card in cards.values()] == ["alpha", "beta", "gamma", "delta"]
    for slug, card in cards.items():
        assert card["scenario_slug"] == card["name"] == slug and card["phase"] == "practice-projects"
        assert card["wallclock_seconds"] == 900
    assert [card["stress"] for card in cards.values()] == [False, False, False, True]


def test_bundles_agree_with_spec_facts_and_hide_no_seed(bundles):
    for slug, root in bundles.items():
        facts, built = MODULE.facts(SPECS[slug]), MODULE.describe(root)
        for key in ("first_night", "last_night", "nights", "targets", "required", "regions"):
            assert built[key] == facts[key], (slug, key)
        assert (built["scenario_slug"], built["card_id"]) == (slug, facts["card_id"])
        assert built["global_wallclock_seconds"] == 900 and built["observation_requests"] > 0
        assert sorted(built["stress_events"]) == (["data_loss", "pointing_offset"] if facts["stress"] else [])
        scenario = json.loads((root / "config" / "v4_scenario.json").read_text(encoding="utf-8"))
        assert scenario["site"] == facts["site"]
        for path in root.rglob("*.json"):
            assert '"seed"' not in path.read_text(encoding="utf-8"), path


def test_a_card_rebuilds_identically(tmp_path, bundles):
    slug = "v4-practice-a"
    again = MODULE.build_spec_bundle(tmp_path / slug, SPECS[slug])
    assert MODULE.pack(again) == MODULE.pack(bundles[slug])


def test_card_pages_are_rendered_from_their_specs():
    # A page edit that is not in the renderer (or a spec change without --pages) fails here.
    for slug, spec in SPECS.items():
        card_id = MODULE.load_spec(spec)["card"]["card_id"]
        for language in ("en", "zh"):
            assert MODULE.page_path(card_id, language).read_text(encoding="utf-8") == MODULE.render_page(spec, language), \
                f"{card_id}/{language}: run scripts/build-v4-practice-cards.py --pages"


COMPARATIVE = re.compile(r"新卡|旧卡|老卡|替换|换成|新版|旧版|改版|更新后|原来的|new card|old card|replac|previous (?:card|version)|"
                         r"updated card|new version|no longer", re.I)


def test_card_pages_describe_each_card_on_its_own():
    # Participant pages state what a card is; they never compare it with an earlier set of cards.
    for spec in SPECS.values():
        card_id = MODULE.load_spec(spec)["card"]["card_id"]
        for language in ("en", "zh"):
            match = COMPARATIVE.search(MODULE.page_path(card_id, language).read_text(encoding="utf-8"))
            assert match is None, f"{card_id}/{language}: {match.group(0)!r}"


def test_initialize_carries_no_truth(bundles):
    root = bundles["v4-practice-d"]
    init = v4_workflow.V4Workflow(root).initialize_payload(900)
    assert init["task_card"] == {"card_id": "delta", "scenario_slug": "v4-practice-d", "phase": "practice-projects"}
    text = json.dumps(init)
    for hidden in ("is_observable", "seed", "instrument_efficiency", "stress", "rocket_launch", "terrain_obstruction",
                   "observation_requests_jsonl"):
        assert hidden not in text, hidden


def test_a_practice_card_runs_end_to_end(tmp_path, bundles):
    # A short wall clock keeps CI fast; the full-season kit-baseline smoke (all four within 900 s) is
    # in the PR description. The run still settles a score when the clock runs out.
    result, *_ = run_card(bundles["v4-practice-c"], tmp_path / "out", wallclock_seconds=20, env={"PATH": os.environ["PATH"]})
    assert result["termination_reason"] in ("survey_complete", "agent_finished", "global_wallclock_expired")
    assert result["score_report"]["counts"]["observe_actions"] > 0
