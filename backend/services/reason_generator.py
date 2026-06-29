"""Batch DeepSeek recommendation reason generation for exploratory mode.

Called AFTER Step3 finalises route_points.  One batch DeepSeek call per
plan; bocha enrichment is batched as well.  Failure never blocks the route.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from .api_client import bocha_search_batch


# ── System prompt ─────────────────────────────────────
_REASON_SYSTEM_PROMPT = """你是本地旅行路线的个性化推荐理由生成器。

你的任务是根据用户真实表达的旅行需求、偏好、限制条件、经过验证的POI信息以及当前路线顺序，为每一个POI生成独立、可信、具体的中文推荐理由。

严格规则：
1. 只能使用输入中提供的事实和证据。
2. 禁止编造历史、活动、客流、评分、菜品、开放时间、价格和交通信息。
3. 每条推荐理由必须包含：POI本身的具体特点；它符合用户哪一项偏好或约束；它在当前路线和时段中的安排价值。
4. 不得只写"环境优美""值得一去""评分较高"等空泛表述。
5. 不得输出"符合本次路线偏好"或"本次搜索的核心目标"这类没有解释的结论。
6. 不要为不同POI重复同一套模板。
7. 冷门、小众、人少等属性必须有enrichment、热度或博查证据。
8. 餐厅优先说明口味、素食、预算、距离或餐段衔接。
9. 如果用户明确提出雨天、室内、低强度、亲子、养生、拍照等要求，应明确说明POI如何满足该要求。
10. 每条推荐理由控制在50至100个汉字。
11. 不要重复POI名称作为句子开头。
12. 不要输出Markdown。
13. 只输出严格JSON。
14. items数量和poi_id必须与输入POI一一对应。

输出格式：
{
  "items": [
    {
      "poi_id": "与输入完全一致",
      "name": "与输入完全一致",
      "highlight": "该地点经过证据支持的特点",
      "preference_match": "它符合用户哪项偏好以及对应证据",
      "route_fit": "它为什么适合当前时段和路线位置",
      "recommend_reason": "最终展示的50至100字中文理由",
      "matched_preferences": [{"term": "冷门", "source": "explicit", "evidence": "博查摘要或热度证据"}],
      "evidence_ids": ["gaode:typecode", "gaode:rating", "bocha:0"],
      "confidence": 0.86
    }
  ]
}"""


# ── Context builder ────────────────────────────────────
def _build_poi_context(poi: dict[str, Any]) -> dict[str, Any]:
    return {
        "poi_id": str(poi.get("poi_id") or poi.get("name", "")),
        "name": str(poi.get("name", "")),
        "kind": str(poi.get("kind", "")),
        "typecode": str(poi.get("typecode", "")),
        "category": str(poi.get("category", "")),
        "address": str(poi.get("address", "")),
        "district": str(poi.get("district", "")),
        "rating": poi.get("rating") or poi.get("gaode_rating"),
        "avg_cost": poi.get("avg_cost"),
        "display_slot": str(poi.get("display_slot", "")),
        "display_order": poi.get("display_order"),
        "enrichment_text": str(poi.get("enrichment_text", "")[:300]),
        "enrichment_heat": poi.get("enrichment_heat", 0),
    }


def _build_user_context(parsed_intent: Any, user_profile: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    ctx["user_request"] = str(getattr(parsed_intent, "user_request", "") or "")[:200]
    ctx["plan_mode"] = "exploratory"
    ctx["primary_query"] = str(getattr(parsed_intent, "primary_query", "") or "")
    ctx["theme_profile"] = str(getattr(parsed_intent, "theme_profile", "") or "")
    ctx["duration"] = str(getattr(parsed_intent, "duration", "") or "")
    ctx["preferences"] = list(getattr(parsed_intent, "raw_keywords", []) or [])[:8]
    ctx["food_prefs"] = list(getattr(parsed_intent, "food_pref_keywords", []) or [])[:4]
    ctx["budget"] = getattr(parsed_intent, "budget_per_capita", None)
    ctx["constraints"] = list(getattr(parsed_intent, "other_constraints", []) or [])[:6]
    ctx["transport"] = str(getattr(parsed_intent, "transport_hint", "") or "")
    ctx["weather"] = str(getattr(parsed_intent, "weather_info", {}) or {})
    ctx["proximity"] = bool(getattr(parsed_intent, "proximity_requested", False))
    ctx["search_area"] = str(getattr(parsed_intent, "search_area_label", "") or "")
    return ctx


# ── BoCha enrichment ──────────────────────────────────
async def _enrich_pois_with_bocha(
    pois: list[dict[str, Any]],
    parsed_intent: Any,
    city: str = "",
) -> None:
    """Batch-enrich POIs that lack description/preference evidence via Bocha."""
    queries = []
    for poi in pois:
        if poi.get("enrichment_text") and len(poi.get("enrichment_text", "")) > 50:
            continue
        name = poi.get("name", "")
        prefs = " ".join(getattr(parsed_intent, "raw_keywords", []) or [])[:40]
        city_label = city[:-1] if city.endswith("市") else city
        queries.append(f"{city_label} {name} {prefs} 特色 游玩体验")
    if not queries:
        return
    try:
        results = await asyncio.wait_for(bocha_search_batch(queries), timeout=15.0)
        for i, items in enumerate(results):
            if i < len(pois) and items:
                snippet = " ".join(
                    str(item.get("snippet", "") or item.get("content", "") or "")
                    for item in items[:3]
                )[:400]
                if snippet:
                    pois[i]["enrichment_text"] = (
                        (pois[i].get("enrichment_text", "") or "") + " | " + snippet
                    )[:600]
                    pois[i]["enrichment_heat"] = max(
                        float(pois[i].get("enrichment_heat", 0) or 0), 0.3
                    )
    except (asyncio.TimeoutError, Exception):
        pass


# ── JSON validation ────────────────────────────────────
def _validate_reason_item(item: dict, input_poi: dict) -> tuple[bool, str]:
    """Validate a single DeepSeek reason item. Returns (valid, failure_reason)."""
    if not isinstance(item, dict):
        return False, "not_a_dict"
    if str(item.get("poi_id", "")) != str(input_poi.get("poi_id") or input_poi.get("name", "")):
        return False, "poi_id_mismatch"
    reason = str(item.get("recommend_reason", "")).strip()
    if not reason:
        return False, "empty_recommend_reason"
    if len(reason) < 20 or len(reason) > 180:
        return False, f"reason_length_{len(reason)}"
    prefs = item.get("matched_preferences")
    if not prefs or not isinstance(prefs, list) or len(prefs) == 0:
        return False, "empty_matched_preferences"
    evidence = item.get("evidence_ids")
    if not evidence or not isinstance(evidence, list) or len(evidence) == 0:
        return False, "empty_evidence_ids"
    pref_match = str(item.get("preference_match", "")).strip()
    if not pref_match or "符合" in pref_match:
        return False, "vague_preference_match"
    return True, ""


# ── Main entry point ───────────────────────────────────
async def generate_exploratory_reasons(
    route_points: list[dict[str, Any]],
    parsed_intent: Any,
    user_profile: Any,
    city: str = "",
) -> list[dict[str, Any]]:
    """Generate independent recommendation reasons for all display POIs.

    Returns the route_points list with recommend_reason fields populated.
    Never blocks route generation on failure.
    """
    t0 = time.monotonic()

    # 1. Filter: only display POIs
    display_pois = [
        p for p in route_points
        if p.get("is_display_poi") or p.get("display_order") is not None
        if p.get("kind") not in ("start", "origin", "hint", "free_explore", "route_only")
        if p.get("is_waypoint") not in (False, None)
    ]
    if not display_pois:
        return route_points

    bocha_count = 0
    deepseek_count = 0
    valid_count = 0
    empty_count = 0

    # 2. BoCha enrichment
    try:
        await _enrich_pois_with_bocha(display_pois, parsed_intent, city)
        bocha_count = 1
    except Exception:
        pass

    # 3. Build context
    user_ctx = _build_user_context(parsed_intent, user_profile)
    poi_ctxs = [_build_poi_context(p) for p in display_pois]

    prompt = json.dumps({
        "user_context": user_ctx,
        "pois": poi_ctxs,
        "task": "为每个POI生成独立的推荐理由",
    }, ensure_ascii=False)

    messages = [
        {"role": "system", "content": _REASON_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    # 4. Call DeepSeek (one batch call)
    try:
        from .api_client import call_llm
        response = await asyncio.wait_for(
            call_llm(messages, temperature=0.3, max_tokens=3000),
            timeout=25.0,
        )
        deepseek_count = 1

        # Parse JSON
        content = str(getattr(response, "content", response) if hasattr(response, "content") else response)
        # Strip markdown fences if present
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("\n```", 1)[0]
        data = json.loads(content)
        items = data.get("items", []) if isinstance(data, dict) else []

        # Build index by poi_id
        reason_map: dict[str, dict] = {}
        for item in items:
            pid = str(item.get("poi_id", ""))
            reason_map[pid] = item

        # Validate and write
        for i, poi in enumerate(display_pois):
            pid = str(poi.get("poi_id") or poi.get("name", ""))
            item = reason_map.get(pid, {})
            valid, failure = _validate_reason_item(item, poi)
            if valid:
                poi["recommend_reason"] = str(item.get("recommend_reason", "")).strip()
                poi["_reason_matched_prefs"] = item.get("matched_preferences", [])
                poi["_reason_evidence"] = item.get("evidence_ids", [])
                poi["_reason_confidence"] = float(item.get("confidence", 0.5))
                valid_count += 1
                print(
                    f"[ReasonAudit] plan_mode=exploratory poi_id={pid} "
                    f"poi_name={poi.get('name','')} "
                    f"matched_preferences={item.get('matched_preferences',[])} "
                    f"evidence_ids={item.get('evidence_ids',[])} "
                    f"json_valid=True preference_valid=True evidence_valid=True "
                    f"reason_written=True confidence={item.get('confidence',0.5)} "
                    f"source=deepseek failure_reason="
                )
            else:
                poi["recommend_reason"] = ""
                empty_count += 1
                print(
                    f"[ReasonAudit] plan_mode=exploratory poi_id={pid} "
                    f"poi_name={poi.get('name','')} "
                    f"matched_preferences=[] evidence_ids=[] "
                    f"json_valid=False preference_valid=False evidence_valid=False "
                    f"reason_written=False confidence=0.0 "
                    f"source=deepseek failure_reason={failure}"
                )

    except (asyncio.TimeoutError, json.JSONDecodeError, Exception) as e:
        deepseek_count = 0
        empty_count = len(display_pois)
        for poi in display_pois:
            poi["recommend_reason"] = ""
            print(
                f"[ReasonAudit] plan_mode=exploratory poi_id={poi.get('poi_id') or poi.get('name','')} "
                f"poi_name={poi.get('name','')} "
                f"reason_written=False source=deepseek failure_reason={type(e).__name__}"
            )

    elapsed = int((time.monotonic() - t0) * 1000)
    print(
        f"[ReasonSummary] final_display_poi_count={len(display_pois)} "
        f"reason_request_poi_count={len(display_pois)} "
        f"valid_reason_count={valid_count} empty_reason_count={empty_count} "
        f"bocha_call_count={bocha_count} deepseek_call_count={deepseek_count} "
        f"elapsed_ms={elapsed}"
    )

    return route_points
