#!/usr/bin/env python3
"""Build the home page's official demo replay: the baseline agent on the public dev-reference scenario.

Same pipeline as a Playground results submission, end to end and untrimmed:
  1. archive/starter_kit_v3/local_runner.py runs archive/starter_kit_v3/agent/minimal_agent.py on all 180 nights, as a
     participant would, and writes decisions.csv;
  2. the worker's scorer (challenge.scoring_core.score_files, termination "trace_complete") scores it;
  3. the worker's renderer (challenge.replay.write_replay_html, no decisions file, as in worker/main.py)
     writes decision_replay.html.
The page is gzipped as-is (the browser inflates it) into web/public/demo/, with a small JSON of the
facts the caption shows. Usage: python3 scripts/build-demo-replay.py
"""
from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from challenge.replay import write_replay_html  # noqa: E402
from challenge.scoring_core import score_files  # noqa: E402

SCENARIO = ROOT / "archive" / "starter_kit_v3" / "scenarios" / "dev-reference"
AGENT = ROOT / "archive" / "starter_kit_v3" / "agent" / "minimal_agent.py"
OUT = ROOT / "web" / "public" / "demo"
NAME = "baseline-dev-reference"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp) / "run"
        subprocess.run([sys.executable, str(ROOT / "archive" / "starter_kit_v3" / "local_runner.py"), "--scenario", str(SCENARIO),
                        "--agent", str(AGENT), "--out", str(run), "--no-replay", "--quiet"], check=True, cwd=ROOT / "archive" / "starter_kit_v3")
        decisions = run / "decisions.csv"
        report = score_files(SCENARIO, decisions, Path(tmp) / "score_report.json", "trace_complete")
        html = Path(tmp) / "decision_replay.html"
        write_replay_html(SCENARIO, report, html, title="dev-reference · official baseline",
                          agent_label="official baseline · archive/starter_kit_v3/agent/minimal_agent.py")
        page = html.read_bytes()
        OUT.mkdir(parents=True, exist_ok=True)
        # mtime=0 keeps the file byte-identical across rebuilds of the same run
        (OUT / f"{NAME}.html.gz").write_bytes(gzip.compress(page, compresslevel=9, mtime=0))
        config = json.loads((SCENARIO / "config" / "scenario_config.json").read_text(encoding="utf-8"))
        nights = {a["slot_id"].split("-S")[0] for a in report["actions"]}
        meta = {
            "scenario": SCENARIO.name,
            "scenario_id": config["scenario_id"],
            "seed": config["seed"],
            "agent": "archive/starter_kit_v3/agent/minimal_agent.py",
            "score": round(float(report["score"]["total"]), 3),
            "rounds": len(report["actions"]),
            "nights": len(nights),
            "termination": report["termination_reason"],
            "decisions_sha256": hashlib.sha256(decisions.read_bytes()).hexdigest(),
            "replay_sha256": hashlib.sha256(page).hexdigest(),
        }
        (OUT / f"{NAME}.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(meta, indent=2), f"\n{NAME}.html.gz: {(OUT / f'{NAME}.html.gz').stat().st_size} bytes")


if __name__ == "__main__":
    main()
