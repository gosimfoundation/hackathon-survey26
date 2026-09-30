#!/usr/bin/env python3
"""试验脚本：生成 v4 正式任务卡 v4-a/v4-b/v4-c/v4-d（首批 ABCD）。

用法（本文件位于 agent-observer-0927/cards/，从仓库根目录运行）：

    conda run -n survey-agent python cards/build_ABCD_cards.py [v4-a v4-b ...]

目录约定（本目录 = cards/）：

    cards/<卡>/spec/    输入：v4_catalog_config.json、v4_weather_config.json、
                        v4_fiber_config.json、v4_score_config.json 与 card.json
                        {name, card_id, scenario_slug, phase, stress, wallclock_seconds}
    cards/<卡>/card/    输出卡片包：config/ public/ truth/（可直接作为卡片根使用）
    cards/<卡>/smoke/   冒烟运行产物（decisions.csv、score_report.json 等）

注意：card/ 与 smoke/ 是生成产物，且本脚本与 build_card_bundle() 一样拒绝覆盖已存在的
目录；就地重建前需先移除该卡的 card/ 与 smoke/。已被提交进仓库的产物即当前这批试验结果。

组装约定逐条继承自 challenge/v4_bundle.py 的 build_card_bundle()：PUBLIC/TRUTH 文件白名单
（直接从 v4_bundle 导入）、scenario products 的 ../public/... ../truth/... 路径改写、
task_card 块、fiber_config/score_config 引用、移除 agent_params、
limits.global_wallclock_seconds 写法、stress 时挂 stress.stress_events_csv、
scenario 以 reference 的 v4_scenario_default.json / v4_scenario_stress.json 为底。

观测请求：与 build_card_bundle 同款接线——card.json 的 "observation_requests" 段覆写
challenge/v4_observation_requests.DEFAULTS（空对象 = 全默认），completion_factor_threshold
缺省取 score 配置 observation_requests.completion_factor_threshold，minimum_feature_flux
缺省按 threshold * flux_zero_point * exposure_zero_point_seconds / max_duration_seconds 推导；
种子沿用同一卡片密钥，流名用官方同款 v4.observation_requests（生成器内部
derive_stream_seed 处理）；产物写入 truth/v4_observation_requests.jsonl，scenario products
登记 observation_requests_jsonl。

种子纪律：catalog 与 weather 共用同一卡片密钥，并统一写上 "seed_derivation": "sha256-v1"
（同一密钥、不同随机流名派生）。密钥只出现在 cardspec 输入与临时目录中，绝不写入卡片产物；
生成前以 cross_validate_generator_configs(..., require_hashed_seeds=True) 交叉校验。
试验卡的密钥取 spec 配置里自带的参考种子值（A 卡与 challenge/reference/v4 的参考种子相同）；
正式卡片必须改为从外部注入的 128 位机密，并把 spec 中的 seed 字段去掉。

冒烟验证：用平台引擎适配层 challenge/v4_workflow.py 的 V4Workflow 真实驱动卡片；
decide 回调内嵌一个由 initialize 公开数据构造的 challenge/v4_probe_agent
（max_observes 调小，不跑完整赛季），跑若干次决策后主动 finish，核对终止原因与得分。
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent      # cards/
REPO = BASE.parent                          # the agent-observer-0927 checkout
if not (REPO / "challenge" / "v4_bundle.py").is_file():
    raise SystemExit(f"repository not found at {REPO}")
sys.path.insert(0, str(REPO))

from challenge import v4_catalog_generator, v4_observation_requests, v4_weather_simulator  # noqa: E402
from challenge.v4_bundle import PUBLIC, TRUTH, REFERENCE  # noqa: E402
from challenge.v4_config_check import cross_validate_generator_configs  # noqa: E402
from challenge import v4_probe_agent, v4_workflow  # noqa: E402

CARDS = BASE

# 冒烟参数：限制决策规模与墙钟，不跑完整赛季。
SMOKE_MAX_OBSERVES = 12
SMOKE_WALLCLOCK_SECONDS = 120.0

CONFIG_FILES = (
    "v4_catalog_config.json",
    "v4_weather_config.json",
    "v4_fiber_config.json",
    "v4_score_config.json",
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def assemble_scenario(card: dict) -> dict:
    """scenario JSON：以 reference 的 default/stress 为底，按 v4_bundle 约定改写。"""
    stress = bool(card.get("stress", False))
    base_name = "v4_scenario_stress.json" if stress else "v4_scenario_default.json"
    scenario = _load_json(REFERENCE / base_name)
    scenario["name"] = str(card["name"])
    scenario["task_card"] = {
        "card_id": str(card["card_id"]),
        "scenario_slug": str(card["scenario_slug"]),
        "phase": str(card["phase"]),
    }
    scenario["fiber_config"] = "v4_fiber_config.json"
    scenario["score_config"] = "v4_score_config.json"
    scenario["products"] = {
        "targets_csv": "../public/targets.csv",
        "footprint_csv": "../public/footprint.csv",
        "night_calendar_csv": "../public/v4_night_calendar.csv",
        "bulletins_jsonl": "../public/v4_bulletins.jsonl",
        "forecasts_jsonl": "../public/v4_forecasts.jsonl",
        "slots_csv": "../truth/v4_slots.csv",
        "weather_truth_csv": "../truth/v4_weather_truth.csv",
        "events_csv": "../truth/v4_events.csv",
        "earthquake_effects_csv": "../truth/v4_earthquake_effects.csv",
        "observation_requests_jsonl": "../truth/v4_observation_requests.jsonl",
    }
    scenario.pop("agent_params", None)
    scenario["stress"] = {"enabled": stress}
    if stress:
        scenario["stress"]["stress_events_csv"] = "../truth/v4_stress_events.csv"
    if card.get("wallclock_seconds") is not None:
        scenario["limits"] = {"global_wallclock_seconds": int(card["wallclock_seconds"])}
    return scenario


def _count_csv(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def smoke_run(card_root: Path, output_dir: Path) -> dict:
    """用 V4Workflow 真实驱动卡片；decide 内嵌由 initialize 公开数据构造的 probe agent。"""
    workflow = v4_workflow.V4Workflow(card_root)  # validate_bundle + load_scenario 全部通过
    holder: dict = {}

    def initialize(payload: dict) -> None:
        columns = payload["targets"]["columns"]
        targets = [dict(zip(columns, row)) for row in payload["targets"]["rows"]]
        context = {
            "max_observes": SMOKE_MAX_OBSERVES,
            "site": payload["site"],
            "fiber": payload["instrument"],  # 含 n_fibers / fiber_area_deg2 / gap_deg
            "scenario": {"name": "smoke", "minimum_altitude_deg": payload["site"]["minimum_altitude_deg"]},
            "targets": targets,
        }
        holder["agent"] = v4_probe_agent.make_agent(context)

    def decide(message: dict, deadline: float) -> dict:
        action = holder["agent"](message["payload"])
        if action is None:
            action = {"action": "finish"}
        return {
            "protocol_version": v4_workflow.PROTOCOL_VERSION,
            "message_type": "decision_response",
            "decision_sequence": message["decision_sequence"],
            **action,
        }

    return v4_workflow.V4Workflow.run(
        workflow, decide, output_dir,
        wallclock_seconds=SMOKE_WALLCLOCK_SECONDS, initialize=initialize,
    )


def build_card(spec_dir: Path) -> dict:
    card = _load_json(spec_dir / "card.json")
    name = str(card["name"])
    stress = bool(card.get("stress", False))
    catalog = _load_json(spec_dir / "v4_catalog_config.json")
    weather = _load_json(spec_dir / "v4_weather_config.json")
    fiber = _load_json(spec_dir / "v4_fiber_config.json")
    fiber.pop("demo", None)  # 与 build_card_bundle 一致

    # 种子纪律：同一卡片密钥（试验取 cardspec 自带参考种子），sha256-v1 分流。
    secret = int(catalog["seed"])
    if int(weather["seed"]) != secret:
        raise ValueError(f"{name}: catalog 与 weather 的种子必须相同（同一密钥、不同流）")
    catalog.update(seed=secret, seed_derivation="sha256-v1")
    weather.update(seed=secret, seed_derivation="sha256-v1")
    weather.setdefault("stress_tests", {})["enabled"] = stress

    scenario = assemble_scenario(card)
    # 站点以 cardspec 为准（reference 的 scenario 底版是 Paranal；交叉校验要求四处一致）
    scenario["site"] = catalog["site"]
    score = _load_json(spec_dir / "v4_score_config.json")
    cross_validate_generator_configs(catalog, weather, scenario, fiber, require_hashed_seeds=True)

    card_root = CARDS / name / "card"
    if card_root.exists():
        raise ValueError(f"{card_root} 已存在（与 build_card_bundle 一样拒绝覆盖；就地重建请先移除）")
    with tempfile.TemporaryDirectory(prefix=f"v4-card-{name}-") as temporary:
        work = Path(temporary)
        _write_json(work / "catalog.json", catalog)
        _write_json(work / "weather.json", weather)
        catalog_summary = v4_catalog_generator.generate_catalog(work / "catalog.json", work / "gen")
        weather_summary = v4_weather_simulator.generate(work / "weather.json", work / "gen")
        # 观测请求（build_card_bundle 同款接线）：card.json 的 observation_requests 覆写
        # DEFAULTS；阈值与最低亮度缺省从 score/fiber 配置推导。
        request_settings = dict(card.get("observation_requests") or {})
        request_settings.setdefault(
            "completion_factor_threshold", score["observation_requests"]["completion_factor_threshold"]
        )
        request_settings.setdefault(
            "minimum_feature_flux",
            float(request_settings["completion_factor_threshold"])
            * float(score["flux_zero_point"])
            * float(score["exposure_zero_point_seconds"])
            / float(fiber["exposure"]["max_duration_seconds"]),
        )
        requests = v4_observation_requests.generate_requests(
            seed=secret,
            targets_csv=work / "gen" / "targets.csv",
            night_calendar_csv=work / "gen" / "v4_night_calendar.csv",
            slots_csv=work / "gen" / "v4_slots.csv",
            site=scenario["site"],
            minimum_altitude_deg=float(scenario["minimum_altitude_deg"]),
            output_path=work / "gen" / "v4_observation_requests.jsonl",
            settings=request_settings,
        )
        for sub in ("config", "public", "truth"):
            (card_root / sub).mkdir(parents=True)
        _write_json(card_root / "config" / "v4_scenario.json", scenario)
        _write_json(card_root / "config" / "v4_fiber_config.json", fiber)
        shutil.copyfile(spec_dir / "v4_score_config.json", card_root / "config" / "v4_score_config.json")
        for filename in PUBLIC:
            shutil.copyfile(work / "gen" / filename, card_root / "public" / filename)
        for filename in TRUTH + (("v4_stress_events.csv",) if stress else ()):
            shutil.copyfile(work / "gen" / filename, card_root / "truth" / filename)

    # 产物卫生：白名单之外不得有别的文件；任何 JSON 中不得出现种子。
    produced = sorted(p.relative_to(card_root).as_posix() for p in card_root.rglob("*") if p.is_file())
    expected = sorted(
        [f"config/{n}" for n in ("v4_scenario.json", "v4_fiber_config.json", "v4_score_config.json")]
        + [f"public/{n}" for n in PUBLIC]
        + [f"truth/{n}" for n in TRUTH + (("v4_stress_events.csv",) if stress else ())]
    )
    if produced != expected:
        raise ValueError(f"{name}: 产物文件清单与白名单不符: {produced}")
    for path in card_root.rglob("*.json"):
        if '"seed"' in path.read_text(encoding="utf-8"):
            raise ValueError(f"{name}: 种子泄漏进产物 {path}")

    smoke_dir = CARDS / name / "smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    smoke = smoke_run(card_root, smoke_dir)
    if "initialization_error" in smoke:
        raise ValueError(f"{name}: 冒烟初始化失败: {smoke['initialization_error']}")
    report = smoke["score_report"]
    if smoke["termination_reason"] not in ("agent_finished", "survey_complete"):
        raise ValueError(f"{name}: 冒烟异常终止: {smoke['termination_reason']} {smoke['termination_detail']}")
    if report["counts"]["observe_actions"] != SMOKE_MAX_OBSERVES:
        raise ValueError(f"{name}: 冒烟观测次数异常: {report['counts']['observe_actions']}")
    if "observation_request_reward" not in report["components"]:
        raise ValueError(f"{name}: score_report 缺少 observation_request_reward 分量")

    return {
        "card": name,
        "card_id": card["card_id"],
        "scenario_slug": card["scenario_slug"],
        "stress": stress,
        "wallclock_seconds": int(card.get("wallclock_seconds", 900)),
        "targets": _count_csv(card_root / "public" / "targets.csv"),
        "required": sum(
            1
            for row in csv.DictReader((card_root / "public" / "targets.csv").open(encoding="utf-8"))
            if row["required"] == "true"
        ),
        "footprint_area_deg2": catalog_summary["footprint"]["total_area_deg2"],
        "nights": _count_csv(card_root / "public" / "v4_night_calendar.csv"),
        "slots": weather_summary["survey"]["slot_count"],
        "events": _count_csv(card_root / "truth" / "v4_events.csv"),
        "events_by_type": weather_summary["events"]["by_type"],
        "observation_requests": [
            {
                "request_id": r["request_id"],
                "issued_at_utc": r["issued_at_utc"],
                "deadline_utc": r["deadline_utc"],
                "n_targets": len(r["target_ids"]),
                "minimum_completed": r["minimum_completed"],
                "completion_reward": r["completion_reward"],
            }
            for r in requests
        ],
        "smoke": {
            "termination_reason": smoke["termination_reason"],
            "decision_requests": smoke["decision_requests"],
            "observe_actions": report["counts"]["observe_actions"],
            "observations": report["counts"]["observations"],
            "total": report["total"],
            "components": report["components"],
            "observation_requests_issued": report["counts"]["observation_requests_issued"],
            "observation_requests_completed": report["counts"]["observation_requests_completed"],
        },
    }


def main() -> int:
    only = set(sys.argv[1:])
    summaries = []
    for card_dir in sorted(p for p in CARDS.iterdir() if p.is_dir() and (p / "spec").is_dir()):
        spec_dir = card_dir / "spec"
        if only and card_dir.name not in only:
            continue
        missing = [n for n in (*CONFIG_FILES, "card.json") if not (spec_dir / n).is_file()]
        if missing:
            raise SystemExit(f"{spec_dir}: 缺少 {missing}")
        print(f"[build] {card_dir.name} ...", flush=True)
        summaries.append(build_card(spec_dir))
        print(f"[build] {card_dir.name} done", flush=True)
    print(json.dumps(summaries, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
