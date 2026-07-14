"""Compare full Step1 extraction with sparse Step1 activation only.

This runner deliberately avoids Step2/3, Gaode, Bocha, and SSE.  It records a
small immutable artifact under evaluation/runs so latency and semantic checks
can be reviewed before the sparse path is relied upon in production.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import time
from pathlib import Path
import sys


EVALUATION_ROOT = Path(__file__).resolve().parent
LOCAL_PROJECT_ROOT = EVALUATION_ROOT.parent
BACKEND_ROOT = Path("/app") if Path("/app/services").is_dir() else LOCAL_PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from services.step1_intent import _llm_parse, _normalize_unified_routing_fields, parse_step1_llm_stage


CASES = [
    {
        "id": "L01",
        "input": "附近找一家饭馆",
        "context": None,
        "expected": {"plan_mode": "planned", "waypoint_categories": ["meal"], "path": "compact_llm"},
    },
    {
        "id": "L02",
        "input": "附近找一家餐厅，再找一家奶茶店",
        "context": None,
        "expected": {"plan_mode": "planned", "waypoint_categories": ["meal", "cafe"], "path": "compact_llm"},
    },
    {
        "id": "S12",
        "input": "下班后想在附近买点水果，再找个地方简单吃晚饭",
        "context": None,
        "expected": {"plan_mode": "planned", "waypoint_categories": ["purchase", "meal"], "path": "compact_llm"},
    },
    {
        "id": "S01",
        "input": "帮我推荐一条适合拍照的文艺路线，有咖啡馆和特色小店，节奏轻松一点",
        "context": None,
        "expected": {"plan_mode": "exploratory", "path": "full_llm"},
    },
    {
        "id": "S02",
        "input": "想去天安门和故宫附近转转，中午吃顿地道的北京菜，下午去景山公园看日落",
        "context": None,
        "expected": {"path": "full_llm"},
    },
    {
        "id": "M01",
        "input": "不想吃烤鸭。想吃川菜",
        "context": {
            "points": [
                {"name": "北海公园", "kind": "visit", "day": 1},
                {"name": "烤鸭店", "kind": "meal", "day": 1},
                {"name": "景山公园", "kind": "visit", "day": 1},
            ],
            "previous_intent": {"duration": "a full day", "plan_mode": "planned"},
        },
        "expected": {"plan_mode": "planned", "conversation_mode": "refine_current", "path": "full_llm"},
    },
]


def summarize(intent) -> dict:
    return {
        "conversation_mode": getattr(intent, "conversation_mode", ""),
        "plan_mode": getattr(intent, "plan_mode", ""),
        "duration": getattr(intent, "duration", ""),
        "raw_keywords": list(getattr(intent, "raw_keywords", []) or []),
        "search_keywords": list(getattr(intent, "search_keywords", []) or []),
        "waypoints": [
            {
                "name": waypoint.name,
                "search_keyword": waypoint.search_keyword,
                "category": waypoint.category,
            }
            for waypoint in (getattr(intent, "planned_waypoints", []) or [])
        ],
    }


def score(summary: dict, expected: dict, *, path: str | None = None) -> dict:
    matched: dict[str, bool] = {}
    if "plan_mode" in expected:
        matched["plan_mode"] = summary["plan_mode"] == expected["plan_mode"]
    if "conversation_mode" in expected:
        matched["conversation_mode"] = summary["conversation_mode"] == expected["conversation_mode"]
    if "waypoint_categories" in expected:
        actual = [item["category"] for item in summary["waypoints"]]
        matched["waypoint_categories"] = actual[: len(expected["waypoint_categories"])] == expected["waypoint_categories"]
    if "path" in expected and path is not None:
        matched["path"] = path == expected["path"]
    return {"passed": all(matched.values()), "matched": matched}


async def run_case(case: dict) -> dict:
    now = dt.datetime.now().astimezone()
    started = time.perf_counter()
    baseline = await _llm_parse(
        case["input"], now, plan_mode="auto", routing_context=case["context"],
    )
    baseline = _normalize_unified_routing_fields(baseline, case["context"])
    baseline_ms = round((time.perf_counter() - started) * 1000)

    started = time.perf_counter()
    sparse, path = await parse_step1_llm_stage(
        case["input"], now, plan_mode="auto", routing_context=case["context"],
    )
    sparse = _normalize_unified_routing_fields(sparse, case["context"])
    sparse_ms = round((time.perf_counter() - started) * 1000)
    baseline_summary = summarize(baseline)
    sparse_summary = summarize(sparse)
    return {
        "case_id": case["id"],
        "input": case["input"],
        "expected": case["expected"],
        "baseline": {
            "duration_ms": baseline_ms,
            "result": baseline_summary,
            "score": score(baseline_summary, case["expected"]),
        },
        "sparse": {
            "duration_ms": sparse_ms,
            "path": path,
            "result": sparse_summary,
            "score": score(sparse_summary, case["expected"], path=path),
        },
    }


async def main() -> None:
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-step1-sparse"
    run_dir = EVALUATION_ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    results = []
    for case in CASES:
        result = await run_case(case)
        results.append(result)
        (run_dir / f"{case['id']}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    baseline_passed = sum(item["baseline"]["score"]["passed"] for item in results)
    sparse_passed = sum(item["sparse"]["score"]["passed"] for item in results)
    baseline_mean = round(sum(item["baseline"]["duration_ms"] for item in results) / len(results))
    sparse_mean = round(sum(item["sparse"]["duration_ms"] for item in results) / len(results))
    compact_rows = [item for item in results if item["sparse"]["path"] == "compact_llm"]
    compact_baseline_mean = round(sum(item["baseline"]["duration_ms"] for item in compact_rows) / len(compact_rows))
    compact_sparse_mean = round(sum(item["sparse"]["duration_ms"] for item in compact_rows) / len(compact_rows))
    summary = {
        "case_count": len(results),
        "baseline_accuracy": baseline_passed / len(results),
        "sparse_accuracy": sparse_passed / len(results),
        "baseline_mean_duration_ms": baseline_mean,
        "sparse_mean_duration_ms": sparse_mean,
        "compact_case_count": len(compact_rows),
        "compact_baseline_mean_duration_ms": compact_baseline_mean,
        "compact_sparse_mean_duration_ms": compact_sparse_mean,
        "compact_latency_delta_ms": compact_sparse_mean - compact_baseline_mean,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), **summary}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
