#!/usr/bin/env python3
"""Rebuild web/src/content/demo/replay.json — the run the homepage console plays.

The file used to be a hand-committed blob, so nobody could tell which agent or scenario produced it or
regenerate it after a change. This script makes it reproducible:

    python3 web/scripts/make_demo_replay.py                     # regenerate with the defaults below
    python3 web/scripts/make_demo_replay.py --keep-workdir DIR   # also keep the scenario and raw run

It generates a public scenario, runs the starter kit's minimal agent against it with the real workflow and
scorer, and writes the compact shape the console reads (tiles, per-slot weather, committed actions, score).

Defaults are tuned for the hero, not for difficulty: a short, dense survey keeps every night busy. A long run
is a worse demo, not a better one — the agent finishes the reachable tiles in the first nights and the rest of
the loop is dead air.

Standard library only; the challenge package and the starter kit do the real work.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
KIT = REPO / "archive" / "starter_kit_v3"
OUT_DEFAULT = REPO / "web" / "src" / "content" / "demo" / "replay.json"

# 7 nights x 256 tiles keeps observations flowing every night (measured: 21/50/36/10/19/3/28 per night).
DEFAULTS = dict(seed=20260907, days=7, start_date="2026-09-07", regions=8, tiles_per_region=32)


def run(cmd: list[str], cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit(f"command failed: {' '.join(cmd)}")


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build(work: Path, opts: argparse.Namespace) -> dict:
    scenario, output = work / "scenario", work / "run"
    run([sys.executable, str(KIT / "make_scenario.py"), "--out", str(scenario), "--force",
         "--seed", str(opts.seed), "--days", str(opts.days), "--start-date", opts.start_date,
         "--regions", str(opts.regions), "--tiles-per-region", str(opts.tiles_per_region),
         "--scenario-id", "demo"], cwd=KIT)
    run([sys.executable, str(KIT / "local_runner.py"), "--scenario", str(scenario),
         "--agent", str(KIT / "agent" / "minimal_agent.py"), "--out", str(output)], cwd=KIT)

    ref = scenario / "outputs" / "reference"
    report = json.loads((output / "score_report.json").read_text(encoding="utf-8"))
    site_cfg = json.loads((scenario / "config" / "calendar_config.json").read_text(encoding="utf-8"))["site"]
    score_cfg = json.loads((scenario / "config" / "score_config.json").read_text(encoding="utf-8"))

    tiles = [{
        "id": t["tile_id"],
        "ra": round(float(t["ra_deg"]), 2),
        "dec": round(float(t["dec_deg"]), 2),
        "cls": "R" if t["scheduling_class"].upper().startswith("R") else "F",
        "region": t["region_id"],
        "exp": int(float(t["nominal_exptime_seconds"])),
        "n": sum(int(t.get(k) or 0) for k in ("n_lrg", "n_elg", "n_qso", "n_bgs")),
    } for t in rows(ref / "tiles.csv")]

    # closed slots carry no measurements; the console renders them as "dome closed" rather than as zeroes
    def measure(value: str) -> float:
        return round(float(value), 6) if value.strip() else 0.0

    weather = [{
        "slot": w["slot_id"], "night": w["night_id"], "t": w["timestamp_utc"],
        "open": w["is_observable"].strip().lower() in ("true", "1", "yes"),
        "seeing": measure(w["seeing_arcsec"]),
        "transp": measure(w["transparency"]),
        "sky": measure(w["sky_quality"]),
        "eff": measure(w["instrument_efficiency"]),
    } for w in rows(ref / "weather.csv")]

    actions = [{
        "i": a["decision_id"], "slot": a["slot_id"],
        "a": "wait" if a["action"] == "wait" else "observe",
        "tile": a.get("tile_id") or "", "program": a.get("program") or "",
        "outcome": a["outcome"], "t": a["start_utc"], "dt": int(a["elapsed_seconds"]),
        "score": round(float(a["base_science_score"]) + float(a["program_bonus_score"]), 4),
        "penalty": round(float(a["penalty"]), 4),
    } for a in report["actions"]]

    completion = report["completion"]
    return {
        "site": {
            "lat": site_cfg["latitude_deg"], "lon": site_cfg["longitude_deg"],
            "min_alt": float(score_cfg.get("minimum_altitude_deg", 30.0)),
        },
        "tiles": tiles,
        "weather": weather,
        "actions": actions,
        "score": report["score"],
        "completed": len(completion["completed_tiles"]),
        "required_missing": completion["required_missing"],
        "requests": report.get("requests", []),
        "nights": len({w["night"] for w in weather}),
    }


def summarise(data: dict) -> str:
    per: dict[str, int] = {}
    for a in data["actions"]:
        night = a["slot"].split("-")[0]
        per[night] = per.get(night, 0) + (a["a"] == "observe")
    counts = list(per.values())
    return (f"{data['nights']} nights, {len(data['tiles'])} tiles, {len(data['actions'])} actions, "
            f"{data['completed']} completed, score {data['score']['total']:.0f}\n"
            f"observes per night: {counts}\n"
            f"nights with <= 2 observes: {sum(1 for c in counts if c <= 2)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=OUT_DEFAULT)
    p.add_argument("--keep-workdir", type=Path, default=None, help="keep the scenario and raw run here")
    for key, value in DEFAULTS.items():
        p.add_argument(f"--{key.replace('_', '-')}", type=type(value), default=value)
    opts = p.parse_args(argv)

    work = Path(tempfile.mkdtemp(prefix="demo-replay-"))
    try:
        data = build(work, opts)
        opts.out.parent.mkdir(parents=True, exist_ok=True)
        opts.out.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
        print(f"wrote {opts.out.relative_to(REPO)} ({opts.out.stat().st_size / 1024:.0f} KiB)")
        print(summarise(data))
        if opts.keep_workdir:
            shutil.copytree(work, opts.keep_workdir, dirs_exist_ok=True)
            print(f"kept scenario and run in {opts.keep_workdir}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
