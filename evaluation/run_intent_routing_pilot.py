"""Live, recognition-only pilot for the unified Step1 routing change.

This intentionally measures LLM routing and structured intent extraction only.
It does not call Step2/3, Gaode, Bocha, or SSE endpoints.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from services.conversation_replan import classify_planning_dispatch, decision_from_step1_intent
from services.step1_intent import _llm_parse, _normalize_unified_routing_fields


CASES = [
    {
        "id": "S01",
        "input": "帮我推荐一条适合拍照的文艺路线，有咖啡馆和特色小店，节奏轻松一点",
        "context": {},
        "expected": {"conversation_mode": "new_plan", "plan_mode": "exploratory"},
    },
    {
        "id": "S12",
        "input": "下班后想在附近买点水果，再找个地方简单吃晚饭",
        "context": {},
        "expected": {"conversation_mode": "new_plan", "plan_mode": "planned"},
    },
    {
        "id": "M01",
        "input": "不想吃烤鸭。想吃川菜",
        "context": {
            "points": [
                {"name": "北海公园", "kind": "visit", "day": 1, "display_slot": "morning"},
                {"name": "烤鸭店", "kind": "meal", "day": 1, "display_slot": "lunch"},
                {"name": "景山公园", "kind": "visit", "day": 1, "display_slot": "afternoon"},
            ],
            "point_names": ["北海公园", "烤鸭店", "景山公园"],
            "previous_intent": {
                "duration": "a full day",
                "plan_mode": "planned",
                "fixed_pois": [{"name": "北海公园"}, {"name": "景山公园"}],
                "food_pref_keywords": ["烤鸭"],
            },
        },
        "expected": {
            "conversation_mode": "refine_current",
            "plan_mode": "planned",
            "required_intent_patch_keys": ["meal_replacement", "new_food_keywords", "meal_slot"],
        },
    },
    {
        "id": "M03",
        "input": "不想去咖啡馆了，改成书店",
        "context": {
            "points": [
                {"name": "望京公园", "kind": "visit", "day": 1},
                {"name": "地球咖啡", "kind": "cafe", "day": 1},
                {"name": "特色小店", "kind": "visit", "day": 1},
            ],
            "point_names": ["望京公园", "地球咖啡", "特色小店"],
            "previous_intent": {
                "duration": "a full day",
                "plan_mode": "exploratory",
                "raw_keywords": ["拍照", "文艺路线", "咖啡馆", "特色小店"],
            },
        },
        "expected": {
            "conversation_mode": "point_edit",
            "plan_mode": "exploratory",
            "required_operation_actions": ["remove_category", "add"],
        },
    },
    {
        "id": "M08",
        "input": "不吃饭了，改成下午逛展和喝咖啡",
        "context": {
            "points": [
                {"name": "川菜餐厅", "kind": "meal", "day": 1},
                {"name": "附近公园", "kind": "visit", "day": 1},
            ],
            "point_names": ["川菜餐厅", "附近公园"],
            "previous_intent": {
                "duration": "a half day",
                "plan_mode": "planned",
                "food_pref_keywords": ["川菜"],
            },
        },
        "expected": {"conversation_mode": "new_plan", "plan_mode": "planned"},
    },
]


def compact_result(parsed, dispatch=None, prefer_dispatch=False):
    source = dispatch if prefer_dispatch and dispatch is not None else parsed
    return {
        "conversation_mode": getattr(source, "conversation_mode", ""),
        "plan_mode": getattr(parsed, "plan_mode", ""),
        "earliest_step": getattr(source, "earliest_step", ""),
        "point_operations": getattr(source, "point_operations", []),
        "intent_patch": getattr(source, "intent_patch", {}),
        "reason": getattr(source, "dispatch_reason", "") or getattr(source, "reason", ""),
    }


def score(result, expected):
    matched = {
        key: result.get(key) == value
        for key, value in expected.items()
        if key not in {"required_operation_actions", "required_intent_patch_keys"}
    }
    actual_actions = {str(item.get("action", "")) for item in result.get("point_operations", []) if isinstance(item, dict)}
    actual_patch = set((result.get("intent_patch") or {}).keys())
    if "required_operation_actions" in expected:
        matched["required_operation_actions"] = set(expected["required_operation_actions"]) <= actual_actions
    if "required_intent_patch_keys" in expected:
        matched["required_intent_patch_keys"] = set(expected["required_intent_patch_keys"]) <= actual_patch
    return {"passed": all(matched.values()), "matched": matched}


async def run_case(case):
    now = dt.datetime.now().astimezone()
    context = case["context"]

    baseline_start = time.perf_counter()
    baseline_dispatch = await classify_planning_dispatch(case["input"], context or None)
    baseline_intent = await _llm_parse(
        case["input"],
        now,
        plan_mode=(baseline_dispatch.target_plan_mode if baseline_dispatch else "auto"),
    )
    baseline_ms = round((time.perf_counter() - baseline_start) * 1000)

    unified_start = time.perf_counter()
    unified_intent = await _llm_parse(
        case["input"],
        now,
        plan_mode="auto",
        routing_context=context or None,
    )
    unified_intent = _normalize_unified_routing_fields(unified_intent, context or None)
    unified_dispatch = decision_from_step1_intent(unified_intent, context or None)
    unified_ms = round((time.perf_counter() - unified_start) * 1000)

    baseline = compact_result(baseline_intent, baseline_dispatch, prefer_dispatch=True)
    unified = compact_result(unified_intent, unified_dispatch, prefer_dispatch=True)
    return {
        "case_id": case["id"],
        "input": case["input"],
        "expected": case["expected"],
        "baseline": {"duration_ms": baseline_ms, "result": baseline, "score": score(baseline, case["expected"])},
        "unified": {"duration_ms": unified_ms, "result": unified, "score": score(unified, case["expected"])},
    }


async def main():
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-intent-routing-pilot"
    run_dir = ROOT / "evaluation" / "runs" / run_id
    traces_dir = run_dir / "traces"
    traces_dir.mkdir(parents=True, exist_ok=False)

    (run_dir / "manifest.json").write_text(json.dumps({
        "run_id": run_id,
        "scope": "llm-recognition-only",
        "cases": [case["id"] for case in CASES],
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "baseline": "legacy dispatch plus Step1 extraction",
        "candidate": "single Step1 extraction with routing context",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    resolved_path = run_dir / "cases_resolved.jsonl"
    with resolved_path.open("w", encoding="utf-8") as handle:
        for case in CASES:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")

    results = []
    for case in CASES:
        result = await run_case(case)
        results.append(result)
        (traces_dir / f"{case['id']}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    baseline_passed = sum(item["baseline"]["score"]["passed"] for item in results)
    unified_passed = sum(item["unified"]["score"]["passed"] for item in results)
    baseline_mean = round(sum(item["baseline"]["duration_ms"] for item in results) / len(results))
    unified_mean = round(sum(item["unified"]["duration_ms"] for item in results) / len(results))
    summary = {
        "case_count": len(results),
        "baseline_accuracy": baseline_passed / len(results),
        "unified_accuracy": unified_passed / len(results),
        "baseline_mean_duration_ms": baseline_mean,
        "unified_mean_duration_ms": unified_mean,
        "latency_delta_ms": unified_mean - baseline_mean,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "summary.md").write_text(
        "# Intent Routing Pilot\n\n"
        f"- Cases: {summary['case_count']}\n"
        f"- Baseline accuracy: {summary['baseline_accuracy']:.0%}\n"
        f"- Unified accuracy: {summary['unified_accuracy']:.0%}\n"
        f"- Baseline mean: {summary['baseline_mean_duration_ms']} ms\n"
        f"- Unified mean: {summary['unified_mean_duration_ms']} ms\n"
        f"- Latency delta: {summary['latency_delta_ms']} ms\n",
        encoding="utf-8",
    )
    print(json.dumps({"run_dir": str(run_dir), **summary}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
