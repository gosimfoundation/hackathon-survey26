"""Build small v4 card bundles (the layout of challenge.v4_workflow) for engine tests."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from challenge import v4_catalog_generator, v4_weather_simulator
from challenge.v4_config_check import cross_validate_generator_configs

REFERENCE = Path(__file__).resolve().parents[1] / "challenge" / "reference" / "v4"
PUBLIC = ("targets.csv", "footprint.csv", "v4_night_calendar.csv", "v4_bulletins.jsonl", "v4_forecasts.jsonl")
TRUTH = ("v4_slots.csv", "v4_weather_truth.csv", "v4_events.csv", "v4_earthquake_effects.csv")


def _load(name: str) -> dict:
    return json.loads((REFERENCE / name).read_text(encoding="utf-8"))


def build_bundle(root: Path, *, start="2026-10-01", end="2026-10-06", targets=1500, seed=4242,
                 stress=False, card_id="T", wallclock_seconds=None) -> Path:
    """A hashed-seed card with a short season; returns the bundle root."""
    work = root.parent / (root.name + "-work")
    catalog = _load("v4_catalog_config.json")
    catalog.update(seed=seed, seed_derivation="sha256-v1")
    catalog["footprint"].update(total_area_deg2=900.0, n_components=2, component_area_weights=[0.6, 0.4],
                                vertices_per_component=24)
    catalog["targets"]["total_count"] = targets
    catalog["observability"].update(start_date=start, end_date=end)
    weather = _load("v4_weather_stress_config.json" if stress else "v4_weather_config.json")
    weather.update(seed=seed + 1, seed_derivation="sha256-v1")
    weather["survey"].update(start_date=start, end_date=end)
    weather["stress_tests"]["enabled"] = stress
    scenario = _load("v4_scenario_stress.json" if stress else "v4_scenario_default.json")
    scenario["name"] = f"test-card-{card_id.lower()}"
    scenario["task_card"] = {"card_id": card_id, "scenario_slug": f"v4-test-{card_id.lower()}", "phase": "test"}
    scenario["fiber_config"] = "v4_fiber_config.json"
    scenario["score_config"] = "v4_score_config.json"
    scenario["products"] = {
        "targets_csv": "../public/targets.csv", "footprint_csv": "../public/footprint.csv",
        "night_calendar_csv": "../public/v4_night_calendar.csv", "bulletins_jsonl": "../public/v4_bulletins.jsonl",
        "forecasts_jsonl": "../public/v4_forecasts.jsonl", "slots_csv": "../truth/v4_slots.csv",
        "weather_truth_csv": "../truth/v4_weather_truth.csv", "events_csv": "../truth/v4_events.csv",
        "earthquake_effects_csv": "../truth/v4_earthquake_effects.csv",
    }
    scenario.pop("agent_params", None)
    if stress:
        scenario["stress"]["stress_events_csv"] = "../truth/v4_stress_events.csv"
    if wallclock_seconds is not None:
        scenario["limits"] = {"global_wallclock_seconds": wallclock_seconds}
    fiber = _load("v4_fiber_config.json")
    fiber.pop("demo", None)
    cross_validate_generator_configs(catalog, weather, scenario, fiber, require_hashed_seeds=True)

    work.mkdir(parents=True)
    (work / "catalog.json").write_text(json.dumps(catalog))
    (work / "weather.json").write_text(json.dumps(weather))
    v4_catalog_generator.generate_catalog(work / "catalog.json", work / "out")
    v4_weather_simulator.generate(work / "weather.json", work / "out")
    for name in ("config", "public", "truth"):
        (root / name).mkdir(parents=True)
    (root / "config" / "v4_scenario.json").write_text(json.dumps(scenario, indent=2))
    (root / "config" / "v4_fiber_config.json").write_text(json.dumps(fiber, indent=2))
    shutil.copyfile(REFERENCE / "v4_score_config.json", root / "config" / "v4_score_config.json")
    for name in PUBLIC:
        shutil.copyfile(work / "out" / name, root / "public" / name)
    for name in TRUTH + (("v4_stress_events.csv",) if stress else ()):
        shutil.copyfile(work / "out" / name, root / "truth" / name)
    shutil.rmtree(work)
    return root
