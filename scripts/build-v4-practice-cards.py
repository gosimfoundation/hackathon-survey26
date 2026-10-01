#!/usr/bin/env python3
"""Build the v4 PRACTICE cards gamma and delta: the second half of the Playground
practice set (alpha, beta, gamma, delta). gamma practices what the formal card C asks
(medium difficulty), delta what the formal card D asks (an extreme season).

Both cards are fully public practice material: like alpha/beta their config/, public/
and truth/ files are released to participants, so their specs (including the seeds)
are fixed here and anyone can rebuild the identical bundles. They never predict the
formal cards A-D: those are generated separately with secret seeds. Nothing here
touches the hidden cards E-H.

  python3 scripts/build-v4-practice-cards.py OUT_ROOT [--card v4-gamma|v4-delta] [--zip]

Writes OUT_ROOT/v4-gamma/ and OUT_ROOT/v4-delta/ (bundle layout of
challenge.v4_bundle), optionally a ZIP per card next to them, and prints one JSON
summary per card with the facts the task-card pages quote (nights, targets, required
count, regions, area, wall clock).

What each card asks, beyond the shared rules (see web/src/content/taskcard.*.v4.*.md):
  gamma (medium): a variable instrument and an unsettled sky. Several instrument
      faults (never announced in bulletins) make fault reporting pay; earthquakes and
      horizon-sector weather force re-planning; no data loss. Different from alpha
      (a calm first season) and beta (one data loss).
  delta (extreme): everything at once. Frequent dome closures and long bad-weather
      stretches leave narrow observing windows; several earthquakes degrade the
      instrument for nights; faults and storms stack; one data loss (state_resync,
      like beta); stress pointing errors are part of the season (never announced,
      like every stress card). Still 900 s of wall clock.

Registration (organizer; the same shape as alpha/beta, W2 owns the upload):
  * scenario slug v4-gamma / v4-delta, contract 'v4-score-v1', active,
    weather/forecasts/events public, global_wallclock_seconds 900;
  * upload each bundle ZIP as the scenario's evaluation bundle;
  * upload config/, public/ and truth/ to the public 'scenarios' bucket under
    <slug>/ (practice cards release their full file set);
  * park both cards in the sealed staging phase until the practice phase is
    re-run with all four cards:
      scripts/configure-v4-phases.py --practice v4-alpha,v4-beta,v4-gamma,v4-delta ...
    (the practice phase switch releases their files at once, like alpha/beta).
"""
import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from challenge import v4_weather_simulator  # noqa: E402
from challenge.tile_geometry_simulator import _local_sidereal_deg  # noqa: E402
from challenge.v4_bundle import REFERENCE, build_card_bundle  # noqa: E402
from challenge.v4_workflow import V4Workflow  # noqa: E402
from project_platform.artifacts import pack_files  # noqa: E402
from project_platform.package import ProjectFile  # noqa: E402

# Three regions placed around the season's mean night-middle sidereal time (the same template the
# formal cards use), so every region is up during the night whatever the season. The reference
# footprint is centred for an October season; a December one would leave a region set at dusk.
FOOTPRINT_OFFSETS = [(-48.0, -24.0), (8.0, -52.0), (52.0, -16.0)]


def three_regions(start_date: str, end_date: str) -> dict:
    weather = json.loads((REFERENCE / "v4_weather_config.json").read_text(encoding="utf-8"))
    weather["survey"].update(start_date=start_date, end_date=end_date)
    nights, _ = v4_weather_simulator.build_nights(weather)
    lon = weather["site"]["longitude_deg"]
    mids = [math.radians(_local_sidereal_deg(n.observing_start_utc + (n.observing_end_utc - n.observing_start_utc) / 2, lon))
            for n in nights]
    mid_lst = math.degrees(math.atan2(sum(map(math.sin, mids)), sum(map(math.cos, mids)))) % 360.0
    return {"n_components": 3, "component_area_weights": [0.4, 0.32, 0.28], "vertices_per_component": 40,
            "component_centers": [[round((mid_lst + dra) % 360.0, 2), ddec] for dra, ddec in FOOTPRINT_OFFSETS]}

PRACTICE_SPECS = {
    # Medium: fault reporting and re-planning around earthquakes and sector weather. No data loss.
    "v4-gamma": {
        "name": "v4-gamma", "card_id": "gamma", "scenario_slug": "v4-gamma", "phase": "practice-projects",
        "seed": 3307, "start_date": "2026-11-08", "end_date": "2026-12-13",
        "targets": 9600, "area_deg2": 1920.0, "stress": False, "wallclock_seconds": 900,
        "catalog_overrides": {"footprint": three_regions("2026-11-08", "2026-12-13")},
        "event_counts": {"rainy": 3, "cloudy": 5, "smoggy": 3, "cold_wave": 2, "tornado": 0,
                         "rocket_launch": 2, "earthquake": 2, "instrument_fault": 3},
    },
    # Extreme: narrow windows (frequent closures, long bad weather), stacked events, one data loss,
    # stress pointing errors. The practice counterpart of the hardest formal card.
    "v4-delta": {
        "name": "v4-delta", "card_id": "delta", "scenario_slug": "v4-delta", "phase": "practice-projects",
        "seed": 4409, "start_date": "2026-12-20", "end_date": "2027-01-24",
        "targets": 9800, "area_deg2": 1950.0, "stress": True, "wallclock_seconds": 900,
        "catalog_overrides": {"footprint": three_regions("2026-12-20", "2027-01-24")},
        "event_counts": {"rainy": 8, "cloudy": 12, "smoggy": 6, "cold_wave": 5, "tornado": 2,
                         "rocket_launch": 5, "earthquake": 4, "instrument_fault": 4},
        "weather_overrides": {"background_closure": {"start_probability_per_open_slot": 0.025,
                                                     "reopen_probability_per_closed_slot": 0.22,
                                                     "seasonal_probability_amplitude": 0.01}},
    },
}


def pack(root: Path) -> bytes:
    files = tuple(ProjectFile(p.relative_to(root).as_posix(), p.read_bytes())
                  for p in sorted(root.rglob("*")) if p.is_file())
    return pack_files(files)


def describe(root: Path, spec: dict) -> dict:
    """The facts the task-card pages quote, read back from the generated bundle."""
    with (root / "public" / "v4_night_calendar.csv").open() as handle:
        nights = list(csv.DictReader(handle))
    with (root / "public" / "targets.csv").open() as handle:
        targets = list(csv.DictReader(handle))
    with (root / "public" / "footprint.csv").open() as handle:
        regions = {row["component_id"] for row in csv.DictReader(handle)}
    with (root / "truth" / "v4_events.csv").open() as handle:
        events = Counter(row["event_type"] for row in csv.DictReader(handle))
    with (root / "truth" / "v4_slots.csv").open() as handle:
        slots = list(csv.DictReader(handle))
    with (root / "truth" / "v4_weather_truth.csv").open() as handle:
        closed = sum(1 for row in csv.DictReader(handle) if row["is_observable"] != "true")
    stress_csv = root / "truth" / "v4_stress_events.csv"
    stress = [row["event_type"] for row in csv.DictReader(stress_csv.open())] if stress_csv.exists() else []
    workflow = V4Workflow(root)
    return {"scenario_slug": spec["scenario_slug"], "card_id": spec["card_id"], "contract": "v4-score-v1",
            "first_night": nights[0]["night_date"], "last_night": nights[-1]["night_date"],
            "nights": len(nights), "slots": len(slots), "closed_slots": closed,
            "targets": len(targets), "required": sum(1 for row in targets if row["required"] == "true"),
            "regions": len(regions), "area_deg2": spec["area_deg2"],
            "global_wallclock_seconds": workflow.wallclock_budget(None),
            "events": dict(sorted(events.items())), "stress_events": stress}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path, help="new directory holding one bundle per card")
    parser.add_argument("--card", choices=sorted(PRACTICE_SPECS), help="build only this card")
    parser.add_argument("--zip", action="store_true", help="also write <slug>.zip next to each bundle")
    args = parser.parse_args()
    slugs = [args.card] if args.card else list(PRACTICE_SPECS)
    if args.out.exists() and any((args.out / slug).exists() for slug in slugs):
        parser.error(f"{args.out} already holds one of {slugs}; build into a fresh directory")
    summaries = []
    for slug in slugs:
        root = build_card_bundle(args.out / slug, PRACTICE_SPECS[slug])
        summary = describe(root, PRACTICE_SPECS[slug])
        if args.zip:
            data = pack(root)
            (args.out / f"{slug}.zip").write_bytes(data)
            summary["zip_sha256"] = hashlib.sha256(data).hexdigest()
        summaries.append(summary)
    print(json.dumps(summaries[0] if args.card else summaries, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
