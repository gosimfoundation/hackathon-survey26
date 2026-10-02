#!/usr/bin/env python3
"""Build the v4 PRACTICE cards (Practice α β γ δ) from their committed specs, and write their pages.

    python3 scripts/build-v4-practice-cards.py OUT_ROOT [--card v4-practice-a] [--zip]
    python3 scripts/build-v4-practice-cards.py --pages          # (re)write web/src/content/taskcard.<id>.v4.*.md
    python3 scripts/build-v4-practice-cards.py --check-pages    # exit 1 if a page differs from its spec

Each card is a self-contained spec folder, cards/v4-practice-<x>/spec/ (card.json + the catalog,
weather, fiber and score generator configs). The cards differ in site, season, footprint, target
count and fibre layout, so nothing is shared beyond the score rules. Practice material is fully
public: config/, public/ and truth/ are released, the specs (seeds included) live in git and anyone
rebuilds the identical bundles. Nothing here touches the formal cards A-D or the hidden cards E-H.

OUT_ROOT/<slug>/ gets the bundle (challenge.v4_bundle.build_spec_bundle: catalogue -> weather ->
observation requests), optionally <slug>.zip next to it, and one JSON summary per card is printed.

The card pages are rendered from web/src/content/taskcard.template.v4.<lang>.md with the facts of
the spec (site, season, nights, targets, regions, fibres, worked example) and the per-card story
below, so a page can never disagree with its card (tests/test_v4_practice_cards.py checks it).

Registration (organizer): scenario slug = the card's scenario_slug, contract 'v4-score-v1',
weather/forecasts/events public, global_wallclock_seconds 900; the bundle ZIP as its evaluation
bundle; config/, public/ and truth/ in the public 'scenarios' bucket under <slug>/; parked in the
sealed staging phase until scripts/configure-v4-phases.py --practice <the four slugs> runs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from challenge import v4_weather_simulator  # noqa: E402
from challenge.v4_bundle import build_spec_bundle  # noqa: E402
from challenge.v4_workflow import V4Workflow  # noqa: E402
from project_platform.artifacts import pack_files  # noqa: E402
from project_platform.package import ProjectFile  # noqa: E402

CARDS = ROOT / "cards"
CONTENT = ROOT / "web" / "src" / "content"
SYMBOLS = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ"}

# Per-card wording the specs cannot give: a title and a one-sentence story (en, zh).
STORIES = {
    "alpha": (("First light", "A season to learn the rules at a classic southern site."),
              ("初见星光", "在经典的南天站点熟悉规则的季节。")),
    "beta": (("Crowded field", "Fifty thousand targets and small fibres: choosing what to point at matters most."),
             ("拥挤的星场", "五万个目标、细小的光纤：选准指向最要紧。")),
    "gamma": (("Northern sky", "A northern site with only nine wide fibres: every exposure must count."),
              ("北天", "北半球站点，只有九根宽光纤：每一次曝光都要算数。")),
    "delta": (("The long year", "A whole year with a hundred fibres, and part of your recent data can be lost once."),
              ("漫长的一年", "整整一年、一百根光纤，最近的一部分数据还可能丢失一次。")),
}
# Site names as the pages show them, keyed by the spec's site name.
SITES = {
    "VISTA/Paranal (4MOST)": ("Paranal, Chile (virtual)", "智利帕拉纳尔（虚拟站点）"),
    "Cape Town, South Africa (virtual)": ("Cape Town, South Africa (virtual)", "南非开普敦（虚拟站点）"),
    "Mauna Kea, Hawaii (virtual)": ("Mauna Kea, Hawaii (virtual)", "美国夏威夷莫纳克亚（虚拟站点）"),
    "Nemo Observatory, South Pacific (fictional)": ("Nemo Observatory, South Pacific (fictional)", "尼莫天文台，南太平洋（虚构站点）"),
}
# The template states these score rules in words; a spec that changes them needs new wording.
FIXED_RULES = {("program", "multipliers"): {"DARK": 1.2, "BRIGHT": 1.12, "BACKUP": 1.06},
               ("required", "penalty_per_missing"): 50, ("required", "observed_factor_threshold"): 0.5,
               ("uniformity", "weight"): 200.0, ("reporting", "correct_reward"): 100, ("reporting", "false_penalty"): -150}


def spec_dirs() -> dict[str, Path]:
    return {path.parent.name: path for path in sorted(CARDS.glob("v4-practice-*/spec"))}


def load_spec(spec: Path) -> dict:
    names = ("card", "v4_catalog_config", "v4_weather_config", "v4_fiber_config", "v4_score_config")
    return {name: json.loads((spec / f"{name}.json").read_text(encoding="utf-8")) for name in names}


def facts(spec: Path) -> dict:
    """What a card page states, read from the spec alone (no bundle build)."""
    cfg = load_spec(spec)
    card, catalog, weather, fiber, score = (cfg[k] for k in ("card", "v4_catalog_config", "v4_weather_config",
                                                              "v4_fiber_config", "v4_score_config"))
    for keys, expected in FIXED_RULES.items():
        value = score[keys[0]][keys[1]]
        if value != expected:
            raise ValueError(f"{spec}: score {'.'.join(keys)} is {value!r}; the page template assumes {expected!r}")
    nights, _ = v4_weather_simulator.build_nights(weather)
    field = fiber["field"]
    n_fibers = int(field["n_fibers"])
    side = math.isqrt(n_fibers)
    if side * side != n_fibers or float(field["gap_deg"]) != 0.0:
        raise ValueError(f"{spec}: the page wording assumes a square grid without gaps")
    targets = int(catalog["targets"]["total_count"])
    observability = catalog["observability"]
    return {
        "card_id": card["card_id"], "slug": card["scenario_slug"], "stress": bool(card.get("stress")),
        "wallclock": int(card["wallclock_seconds"]), "site": catalog["site"],
        "first_night": nights[0].night_date.isoformat(), "last_night": nights[-1].night_date.isoformat(),
        "nights": len(nights), "targets": targets,
        "required": int(round(targets * float(catalog["targets"]["required_fraction"]))),
        "regions": int(catalog["footprint"]["n_components"]), "area": float(catalog["footprint"]["total_area_deg2"]),
        "sun_limit": float(observability["sun_altitude_limit_deg"]), "min_alt": float(observability["minimum_altitude_deg"]),
        "fibers": n_fibers, "grid": side, "field_area": n_fibers * float(field["fiber_area_deg2"]),
        "exposure": (int(fiber["exposure"]["min_duration_seconds"]), int(fiber["exposure"]["max_duration_seconds"])),
        "f0": float(score["flux_zero_point"]), "t0": float(score["exposure_zero_point_seconds"]),
    }


# ------------------------------------------------------------------ pages
def _num(value: float, digits: int = 0) -> str:
    return f"{value:,.{digits}f}"


def _deg(value: float) -> str:
    return f"{value:+.2f}°".replace("+", "" if value >= 0 else "").replace("-", "−")


def _swap(text: str, old: str, new: str) -> str:
    if old not in text:
        raise ValueError(f"template text changed; cannot find {old[:60]!r}")
    return text.replace(old, new)


def render_page(spec: Path, language: str) -> str:
    f = facts(spec)
    card_id = f["card_id"]
    symbol = SYMBOLS[card_id]
    zh = language == "zh"
    title, story = STORIES[card_id][1 if zh else 0]
    template = (CONTENT / f"taskcard.template.v4.{language}.md").read_text(encoding="utf-8")
    text = re.sub(r"\A<!--.*?-->\n\n", "", template, flags=re.S)
    lat, lon = _deg(f["site"]["latitude_deg"]), _deg(f["site"]["longitude_deg"])
    site = SITES[f["site"]["name"]][1 if zh else 0]
    # Worked example: brightness 0.60 and sky quality 0.75 for twice the zero point, so the factor is 0.90.
    zero = f["f0"] * f["t0"]
    long_exposure = round(2 * zero)
    short_factor = 0.60 * long_exposure / 3 * 0.75 / zero
    across = math.sqrt(f["field_area"])
    if zh:
        weather = ("本卡完整的天气和事件文件是公开的（见资源页）。智能体拿不到这些文件：运行中只会逐步收到每 15 分钟一条的简报和大约每周一次的预报。")
        extra = "限时观测请求（`observation_request`）及其结果（`observation_request_result`）。"
        if f["stress"]:
            extra += "另外可能收到一条 `state_resync` 消息。它表示最近的一部分数据丢失了。消息里列出仍然有效的目标和各自的最好得分。请据此重建\"已完成目标\"列表。已经用掉的时间不会退回。"
        try_it = (f"1. 在资源页下载 v4 入门包和卡片 {symbol}。把卡片文件夹放进入门包的 `cards/` 目录。\n"
                  f"2. 运行 `python3 local_runner.py --card cards/{card_id}`。最后一行是你的得分。天气文件是公开的，所以同样的决策在本地和平台上得分相同。\n"
                  f"3. 和 `python3 local_runner.py --card cards/{card_id} --agent examples/idle_agent.py`（什么都不做的智能体）比一比。\n"
                  "4. 修改 `agent/planner.py`，再运行，再比较。\n"
                  f"5. 用 `python3 pack_agent.py --out ../my-agent.zip` 打包，在「参赛」页提交。练习赛会在云端运行全部练习卡 α、β、γ、δ，时间限制同样是 {f['wallclock']} 秒。每日次数见规则页。\n\n"
                  "练习赛成绩只用于练习，不决定奖项。")
        rows = [
            ("| 站点 | 智利帕拉纳尔（虚拟站点）。纬度 −24.62°，经度 −70.40°。 |", f"| 站点 | {site}。纬度 {lat}，经度 {lon}。 |"),
            ("| 仪器 | 16 个光纤可指派方格，排成 4 × 4、无间隙。总面积 6.4 平方度，视场宽约 2.53°。 |",
             f"| 仪器 | {f['fibers']} 个光纤可指派方格，排成 {f['grid']} × {f['grid']}、无间隙。总面积 {f['field_area']:g} 平方度，视场宽约 {across:.2f}°。 |"),
            ("给最多 16 根光纤各分配一个目标", f"给最多 {f['fibers']} 根光纤各分配一个目标"),
            ("太阳低于 −18° 时可以观测", f"太阳低于 {_deg(f['sun_limit']).replace('.00', '')} 时可以观测"),
            ("全程不低于 30° 高度角", f"全程不低于 {f['min_alt']:g}° 高度角"),
            ("你曝光 900 秒。", f"你曝光 {long_exposure} 秒。"),
            ("0.60 × 900 × 0.75 ÷ 450 = 0.90", f"0.60 × {long_exposure} × 0.75 ÷ {zero:g} = 0.90"),
            ("如果只曝光 300 秒，系数只有 0.30。", f"如果只曝光 {long_exposure // 3} 秒，系数只有 {short_factor:.2f}。"),
            ("- 一次曝光变差就报告故障。天气也会让分数变低。\n",
             "- 一次曝光变差就报告故障。天气也会让分数变低。\n- 让智能体读取天气文件。在平台上，智能体只能访问自己的文件夹。\n"),
        ]
    else:
        weather = ("The full weather and event files of this card are public (Resources page). Your agent does not get them: "
                   "during a run it only receives a short bulletin every 15 minutes and a forecast about once a week.")
        extra = "Time-limited observation requests (`observation_request`) and their results (`observation_request_result`)."
        if f["stress"]:
            extra += (" Possibly one `state_resync` message. It means part of your recent data was lost. It lists the targets "
                      "that still count and their best scores. Rebuild your list of finished targets from it. "
                      "The time already spent is not returned.")
        try_it = (f"1. Download the v4 starter kit and card {symbol} from the Resources page. Put the card folder into the kit's `cards/` folder.\n"
                  f"2. Run `python3 local_runner.py --card cards/{card_id}`. The last line shows your score. The weather files are public, so the same decisions give the same score here and on the platform.\n"
                  f"3. Compare with `python3 local_runner.py --card cards/{card_id} --agent examples/idle_agent.py` (an agent that does nothing).\n"
                  "4. Change `agent/planner.py`, run again, and compare.\n"
                  f"5. Pack with `python3 pack_agent.py --out ../my-agent.zip` and submit it on Participate. Practice runs all practice cards α, β, γ and δ in the cloud, with the same {f['wallclock']} s limit. Daily limits are on the Rules page.\n\n"
                  "Practice scores do not decide awards.")
        rows = [
            ("| Site | Paranal, Chile (virtual). Latitude −24.62°, longitude −70.40°. |", f"| Site | {site}. Latitude {lat}, longitude {lon}. |"),
            ("| Instrument | 16 contiguous fibre assignment cells in a 4 × 4 grid. The field covers 6.4 deg² and is about 2.53° across. |",
             f"| Instrument | {f['fibers']} contiguous fibre assignment cells in a {f['grid']} × {f['grid']} grid. The field covers {f['field_area']:g} deg² and is about {across:.2f}° across. |"),
            ("put up to 16 targets on fibres", f"put up to {f['fibers']} targets on fibres"),
            ("when the sun is below −18°", f"when the sun is below {_deg(f['sun_limit']).replace('.00', '')}"),
            ("stays at or above 30° altitude", f"stays at or above {f['min_alt']:g}° altitude"),
            ("You expose it for 900 s.", f"You expose it for {long_exposure} s."),
            ("0.60 × 900 × 0.75 ÷ 450 = 0.90", f"0.60 × {long_exposure} × 0.75 ÷ {zero:g} = 0.90"),
            ("With a 300 s exposure the factor is only 0.30.", f"With a {long_exposure // 3} s exposure the factor is only {short_factor:.2f}."),
            ("- Reporting a fault after one bad exposure. Weather also lowers scores.\n",
             "- Reporting a fault after one bad exposure. Weather also lowers scores.\n"
             "- Reading the weather files from your agent. On the platform your agent only has its own folder.\n"),
        ]
    for old, new in rows:
        text = _swap(text, old, new)
    exposure = f"{f['exposure'][0]}–{f['exposure'][1]}"
    text = _swap(text, "60–3600", exposure)
    fields = {
        "CARD_ID": f"{symbol}（{card_id}）" if zh else f"{symbol} ({card_id})", "CARD_TITLE": title,
        "ONE_SENTENCE_STORY": story, "START_DATE": f["first_night"], "END_DATE": f["last_night"],
        "NIGHTS": str(f["nights"]), "TARGETS": _num(f["targets"]), "AREA_DEG2": _num(f["area"]),
        "REGIONS": str(f["regions"]), "COMPONENTS": str(f["regions"]), "REQUIRED": _num(f["required"]),
        "WALLCLOCK": str(f["wallclock"]), "WEATHER": weather, "EXTRA_MESSAGES": extra, "TRY_IT": try_it,
    }
    text = re.sub(r"\{\{([A-Z_0-9]+)\}\}", lambda m: fields[m.group(1)], text)
    if "{{" in text:
        raise ValueError(f"unfilled template field in {card_id}/{language}")
    return text


def page_path(card_id: str, language: str) -> Path:
    return CONTENT / f"taskcard.{card_id}.v4.{language}.md"


# ------------------------------------------------------------------ bundles
def pack(root: Path) -> bytes:
    files = tuple(ProjectFile(p.relative_to(root).as_posix(), p.read_bytes())
                  for p in sorted(root.rglob("*")) if p.is_file())
    return pack_files(files)


def describe(root: Path) -> dict:
    """Facts read back from a built bundle (cross-checks the page facts)."""
    scenario = json.loads((root / "config" / "v4_scenario.json").read_text(encoding="utf-8"))
    rows = lambda rel: list(csv.DictReader((root / rel).open(encoding="utf-8")))  # noqa: E731
    nights, targets, slots = rows("public/v4_night_calendar.csv"), rows("public/targets.csv"), rows("truth/v4_slots.csv")
    stress = root / "truth" / "v4_stress_events.csv"
    return {"scenario_slug": scenario["task_card"]["scenario_slug"], "card_id": scenario["task_card"]["card_id"],
            "first_night": nights[0]["night_date"], "last_night": nights[-1]["night_date"], "nights": len(nights),
            "slots": len(slots), "targets": len(targets), "required": sum(r["required"] == "true" for r in targets),
            "regions": len({r["component_id"] for r in rows("public/footprint.csv")}),
            "closed_slots": sum(r["is_observable"] != "true" for r in rows("truth/v4_weather_truth.csv")),
            "events": dict(sorted(Counter(r["event_type"] for r in rows("truth/v4_events.csv")).items())),
            "stress_events": [r["event_type"] for r in csv.DictReader(stress.open())] if stress.exists() else [],
            "observation_requests": sum(1 for line in (root / "truth" / "v4_observation_requests.jsonl").open() if line.strip()),
            "global_wallclock_seconds": V4Workflow(root).wallclock_budget(None),
            "bytes": sum(p.stat().st_size for p in root.rglob("*") if p.is_file())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out", type=Path, nargs="?", help="new directory holding one bundle per card")
    parser.add_argument("--card", choices=sorted(spec_dirs()), help="only this card")
    parser.add_argument("--zip", action="store_true", help="also write <slug>.zip next to each bundle")
    parser.add_argument("--pages", action="store_true", help="write the card pages from the specs")
    parser.add_argument("--check-pages", action="store_true", help="fail if a committed page differs from its spec")
    args = parser.parse_args()
    specs = spec_dirs()
    slugs = [args.card] if args.card else list(specs)
    if args.pages or args.check_pages:
        stale = []
        for slug in slugs:
            card_id = load_spec(specs[slug])["card"]["card_id"]
            for language in ("en", "zh"):
                text, path = render_page(specs[slug], language), page_path(card_id, language)
                if args.pages:
                    path.write_text(text, encoding="utf-8")
                elif not path.exists() or path.read_text(encoding="utf-8") != text:
                    stale.append(path.relative_to(ROOT).as_posix())
        if stale:
            print("stale card pages (run --pages):", *stale, sep="\n  ")
            return 1
        return 0
    if args.out is None:
        parser.error("OUT_ROOT is required to build bundles")
    if any((args.out / slug).exists() for slug in slugs):
        parser.error(f"{args.out} already holds one of {slugs}; build into a fresh directory")
    summaries = []
    for slug in slugs:
        root = build_spec_bundle(args.out / slug, specs[slug])
        summary = describe(root)
        if args.zip:
            data = pack(root)
            (args.out / f"{slug}.zip").write_bytes(data)
            summary.update(zip_bytes=len(data), zip_sha256=hashlib.sha256(data).hexdigest())
        summaries.append(summary)
    print(json.dumps(summaries[0] if args.card else summaries, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
