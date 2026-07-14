"""Run a reproducible eight-case serial validation against the local dynamic API.

The runner intentionally does not alter route-planning code or fixed-route fixtures.
It samples only the benchmark's single-turn dynamic cases, because a follow-up turn
needs the previous route context and therefore is not an independent timing sample.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = ROOT / "evaluation" / "cases" / "benchmark_v1_draft.md"
API_URL = "http://localhost:8000/api/meituan/chat/stream"
SEED = 20260714
SAMPLE_SIZE = 8
RUNNER_VERSION = "v1-random8-validation-1"


PROFILE_PRESETS: dict[str, dict[str, Any]] = {
    "P-BJ-ART": {
        "nickname": "评测游客-北京文艺",
        "activity_pref_tag": ["摄影打卡", "艺术展览", "美食探店"],
        "food_pref_tag": ["咖啡", "清淡"],
        "home_location": {
            "lat": 40.008561,
            "lng": 116.48788,
            "label": "北京恒基伟业大厦",
            "city": "北京市",
            "district": "朝阳区",
        },
        "permanent_city_coord": {"lat": 40.008561, "lng": 116.48788},
        "budget_per_capita": 150,
    },
    "P-BJ-FOOD": {
        "nickname": "评测游客-北京美食",
        "activity_pref_tag": ["历史文化", "城市漫游", "自然风光"],
        "food_pref_tag": ["北京菜", "清淡"],
        "home_location": {
            "lat": 39.9059,
            "lng": 116.4123,
            "label": "北京饭店",
            "city": "北京市",
            "district": "东城区",
        },
        "permanent_city_coord": {"lat": 39.9059, "lng": 116.4123},
        "budget_per_capita": 200,
    },
    "P-SH-LOCAL": {
        "nickname": "评测游客-上海本地",
        "activity_pref_tag": ["城市漫游", "摄影打卡", "自然风光"],
        "food_pref_tag": ["咖啡", "本帮菜"],
        "home_location": {
            "lat": 31.2810,
            "lng": 121.3520,
            "label": "上海桃浦",
            "city": "上海市",
            "district": "普陀区",
        },
        "permanent_city_coord": {"lat": 31.2810, "lng": 121.3520},
        "budget_per_capita": 150,
    },
    "P-BJ-GROUP": {
        "nickname": "评测游客-北京同行",
        "activity_pref_tag": ["美食探店", "城市漫游", "夜生活"],
        "food_pref_tag": ["清淡", "川菜"],
        "home_location": {
            "lat": 40.008561,
            "lng": 116.48788,
            "label": "北京恒基伟业大厦",
            "city": "北京市",
            "district": "朝阳区",
        },
        "permanent_city_coord": {"lat": 40.008561, "lng": 116.48788},
        "budget_per_capita": 180,
    },
}


def _git_revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unavailable"


def _load_single_turn_cases() -> list[dict[str, str]]:
    text = CASE_FILE.read_text(encoding="utf-8")
    body = text.split("## Single-turn cases", 1)[1].split("## Multi-turn", 1)[0]
    cases: list[dict[str, str]] = []
    for line in body.splitlines():
        if not line.startswith("| S"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            continue
        case_id = cells[0].split()[0]
        cases.append({
            "case_id": case_id,
            "profile": cells[1],
            "message": cells[2],
            "expected": cells[3],
            "hard_constraints": cells[4],
        })
    if len(cases) < SAMPLE_SIZE:
        raise RuntimeError(f"Only parsed {len(cases)} single-turn cases from {CASE_FILE}")
    return cases


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _visible_points(route_data: dict[str, Any]) -> list[dict[str, Any]]:
    points = route_data.get("points", []) if isinstance(route_data, dict) else []
    return [
        point for point in points
        if isinstance(point, dict)
        and point.get("kind") not in {"start", "origin", "hint", "free_explore", "route_only"}
        and point.get("is_waypoint", True) is not False
    ]


def _compact_stage_stats(stats: Any) -> dict[str, Any]:
    if not isinstance(stats, dict):
        return {}
    wanted = ("step1_intent", "step2_macro", "step3_micro", "planned_route", "exploratory_route", "reason_generation", "photo_enrichment")
    stages = stats.get("stage_durations_ms", stats.get("stages", stats))
    if not isinstance(stages, dict):
        return {}
    return {name: stages[name] for name in wanted if name in stages}


def _quality_signals(case: dict[str, str], complete: dict[str, Any] | None, error: str) -> dict[str, Any]:
    if not complete:
        return {"status": "technical_invalid", "verdict": "FAIL", "checks": [error or "missing complete event"]}
    content = complete.get("content", {}) if isinstance(complete.get("content"), dict) else {}
    route_data = content.get("route_data", {}) if isinstance(content.get("route_data"), dict) else {}
    points = _visible_points(route_data)
    segments = route_data.get("segments", []) if isinstance(route_data.get("segments"), list) else []
    polyline_count = sum(bool(segment.get("polyline")) for segment in segments if isinstance(segment, dict))
    poi_text = " ".join(
        " ".join(str(point.get(key, "")) for key in ("name", "address", "recommend_reason", "tags", "category"))
        for point in points
    )
    intent = content.get("intent", {}) if isinstance(content.get("intent"), dict) else {}
    intent_text = json.dumps(intent, ensure_ascii=False)
    combined_text = f"{poi_text} {intent_text}"
    message = case["message"]
    checks: list[str] = []
    if not points:
        checks.append("无可见 POI")
    if len(points) >= 2:
        checks.append(f"可见 POI {len(points)} 个")
    else:
        checks.append(f"可见 POI 过少：{len(points)} 个")
    if len(points) >= 2 and polyline_count >= len(points) - 1:
        checks.append(f"路线段完整：{polyline_count}/{len(points) - 1}")
    else:
        checks.append(f"路线段不足：{polyline_count}/{max(0, len(points) - 1)}")
    named_groups = {
        "天安门": ("天安门",), "故宫": ("故宫",), "景山": ("景山",), "北海": ("北海",),
        "三里河": ("三里河",), "什刹海": ("什刹海",), "天坛": ("天坛",), "前门": ("前门",),
        "王府井": ("王府井",), "外滩": ("外滩",), "南京路": ("南京路",), "颐和园": ("颐和园",),
        "国贸": ("国贸",), "三里屯": ("三里屯",),
    }
    required = [name for name in named_groups if name in message]
    missed = [name for name in required if not any(alias in combined_text for alias in named_groups[name])]
    if missed:
        checks.append("固定锚点未见：" + "、".join(missed))
    elif required:
        checks.append("固定锚点可见：" + "、".join(required))
    lower_features = {
        "咖啡": ("咖啡",), "奶茶": ("奶茶", "茶饮"), "饭馆": ("餐", "饭", "菜", "小吃"),
        "散步": ("公园", "步行", "滨", "绿地", "广场", "街"), "拍照": ("拍照", "艺术", "展", "创意", "文艺"),
        "夜景": ("夜景", "观景", "灯", "塔", "江", "河"),
    }
    feature_terms = [key for key in lower_features if key in message]
    missed_features = [key for key in feature_terms if not any(alias in combined_text for alias in lower_features[key])]
    if missed_features:
        checks.append("需求证据不足：" + "、".join(missed_features))
    elif feature_terms:
        checks.append("需求证据可见：" + "、".join(feature_terms))
    pass_core = bool(points) and (not required or not missed)
    route_ok = len(points) < 2 or polyline_count >= len(points) - 1
    verdict = "PASS" if pass_core and route_ok and not missed_features else "REVIEW"
    return {
        "status": "complete",
        "verdict": verdict,
        "checks": checks,
        "visible_poi_count": len(points),
        "polyline_segment_count": polyline_count,
        "poi_names": [str(point.get("name", "")) for point in points],
        "missed_anchors": missed,
        "missing_feature_evidence": missed_features,
    }


def _run_case(case: dict[str, str], run_id: str, run_dir: Path) -> dict[str, Any]:
    raw_lines: list[str] = []
    events: list[dict[str, Any]] = []
    current_event = "message"
    complete: dict[str, Any] | None = None
    error = ""
    payload = {
        "message": case["message"],
        "user_id": f"{run_id}-{case['case_id'].lower()}",
        "plan_mode": "auto",
        "guest_profile": PROFILE_PRESETS[case["profile"]],
        "client_timezone": "Asia/Shanghai",
    }
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=httpx.Timeout(310.0, connect=12.0)) as client:
            with client.stream("POST", API_URL, json=payload, headers={"Accept": "text/event-stream"}) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    raw_lines.append(line)
                    if line.startswith("event: "):
                        current_event = line[7:]
                    elif line.startswith("data: "):
                        raw_data = line[6:]
                        try:
                            data: Any = json.loads(raw_data)
                        except json.JSONDecodeError:
                            data = raw_data
                        events.append({"event": current_event, "elapsed_ms": round((time.perf_counter() - started) * 1000), "data": data})
                        if current_event == "complete" and isinstance(data, dict):
                            complete = data
                            break
                        if current_event == "error":
                            error = str(data.get("error", data)) if isinstance(data, dict) else str(data)
                            break
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    wall_clock_ms = round((time.perf_counter() - started) * 1000)
    (run_dir / "raw_sse" / f"{case['case_id']}.txt").write_text("\n".join(raw_lines), encoding="utf-8")
    _write_json(run_dir / "events" / f"{case['case_id']}.json", events)
    if complete:
        _write_json(run_dir / "responses" / f"{case['case_id']}.json", complete)
    signal = _quality_signals(case, complete, error)
    content = complete.get("content", {}) if isinstance(complete, dict) and isinstance(complete.get("content"), dict) else {}
    route_data = content.get("route_data", {}) if isinstance(content.get("route_data"), dict) else {}
    result = {
        **case,
        "wall_clock_ms": wall_clock_ms,
        "terminal_event": "complete" if complete else "error",
        "error": error,
        "stage_stats": _compact_stage_stats(complete.get("stats", {}) if complete else {}),
        "route_title": route_data.get("title", ""),
        "quality": signal,
    }
    _write_json(run_dir / "scores" / f"{case['case_id']}.json", result)
    return result


def _format_seconds(milliseconds: Any) -> str:
    try:
        return f"{float(milliseconds) / 1000:.1f}s"
    except (TypeError, ValueError):
        return "-"


def _write_summary(run_dir: Path, results: list[dict[str, Any]], run_id: str) -> None:
    with (run_dir / "summary.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case_id", "profile", "wall_clock_s", "verdict", "visible_pois", "polyline_segments", "error"])
        for item in results:
            quality = item["quality"]
            writer.writerow([item["case_id"], item["profile"], _format_seconds(item["wall_clock_ms"]), quality["verdict"], quality.get("visible_poi_count", 0), quality.get("polyline_segment_count", 0), item["error"]])
    total = len(results)
    invalid = [item for item in results if item["quality"]["status"] == "technical_invalid"]
    review = [item for item in results if item["quality"]["verdict"] == "REVIEW"]
    durations = [item["wall_clock_ms"] for item in results if item["terminal_event"] == "complete"]
    stage_names = ("step1_intent", "step2_macro", "step3_micro", "planned_route", "exploratory_route", "reason_generation", "photo_enrichment")
    lines = [
        "# Dynamic Route Benchmark V1 - Random 8 Validation",
        "",
        f"- Run: `{run_id}`",
        f"- Sampling: fixed seed `{SEED}`, 8 cases sampled from the 24 single-turn dynamic cases.",
        "- Execution: serial (`concurrency=1`), local API only, no fixed-route snapshot endpoint.",
        f"- Complete: {total - len(invalid)}/{total}; technical invalid: {len(invalid)}; review required: {len(review)}.",
        f"- End-to-end average (completed): {_format_seconds(sum(durations) / len(durations)) if durations else '-'}.",
        "",
        "| Case | Profile | Total | Key stages | POIs / polylines | Verdict | Evaluation |",
        "| --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for item in results:
        quality = item["quality"]
        stages = item["stage_stats"]
        stage_text = "; ".join(f"{name} {_format_seconds(stages[name])}" for name in stage_names if name in stages) or "not emitted"
        route_bits = f"{quality.get('visible_poi_count', 0)} / {quality.get('polyline_segment_count', 0)}"
        evaluation = "；".join(quality["checks"]) if quality.get("checks") else item.get("error", "")
        lines.append(f"| {item['case_id']} | {item['profile']} | {_format_seconds(item['wall_clock_ms'])} | {stage_text} | {route_bits} | {quality['verdict']} | {evaluation} |")
    lines += ["", "## Major issue decision", ""]
    if invalid:
        lines.append("Major issue: yes. At least one request did not produce a parseable complete response; inspect its raw SSE artifact before changing scoring or route logic.")
    elif review:
        lines.append("Major issue: no technical outage detected. However, one or more completed cases need semantic review; inspect the listed missing constraint evidence before further algorithm changes.")
    else:
        lines.append("Major issue: none detected in this eight-case serial sample. This is a smoke-level stability result, not a substitute for the full benchmark or multi-turn evaluation.")
    lines.append("")
    for name in stage_names:
        values = [item["stage_stats"][name] for item in results if isinstance(item["stage_stats"].get(name), (int, float))]
        if values:
            lines.append(f"- `{name}` mean: {_format_seconds(sum(values) / len(values))} across {len(values)} emitted cases.")
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    cases = _load_single_turn_cases()
    sampled = random.Random(SEED).sample(cases, SAMPLE_SIZE)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-v1-random8"
    run_dir = ROOT / "evaluation" / "runs" / run_id
    for name in ("raw_sse", "events", "responses", "scores"):
        (run_dir / name).mkdir(parents=True, exist_ok=False)
    checksum = hashlib.sha256(CASE_FILE.read_bytes()).hexdigest()
    _write_json(run_dir / "manifest.json", {
        "run_id": run_id,
        "runner_version": RUNNER_VERSION,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "git_revision": _git_revision(),
        "case_file": str(CASE_FILE.relative_to(ROOT)),
        "case_file_sha256": checksum,
        "seed": SEED,
        "sample_size": SAMPLE_SIZE,
        "concurrency": 1,
        "api_url": API_URL,
        "fixed_route_snapshots_excluded": True,
    })
    with (run_dir / "cases_resolved.jsonl").open("w", encoding="utf-8") as handle:
        for index, case in enumerate(sampled, start=1):
            handle.write(json.dumps({"execution_order": index, **case, "guest_profile": PROFILE_PRESETS[case["profile"]]}, ensure_ascii=False) + "\n")
    results: list[dict[str, Any]] = []
    consecutive_invalid = 0
    for case in sampled:
        print(f"[{len(results) + 1}/{len(sampled)}] {case['case_id']} {case['message']}", flush=True)
        result = _run_case(case, run_id, run_dir)
        results.append(result)
        invalid = result["quality"]["status"] == "technical_invalid"
        consecutive_invalid = consecutive_invalid + 1 if invalid else 0
        if consecutive_invalid >= 3:
            break
    _write_json(run_dir / "stop_report.json", {
        "completed": len(results) == len(sampled),
        "executed_count": len(results),
        "planned_count": len(sampled),
        "active_stop_rule": "three_consecutive_technical_failures" if consecutive_invalid >= 3 else "none",
        "remaining_case_ids": [case["case_id"] for case in sampled[len(results):]],
    })
    _write_summary(run_dir, results, run_id)
    print(str(run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
