"""Batch DeepSeek recommendation reason generation for all plan modes.

Called AFTER Step3 finalises route_points. One bounded DeepSeek batch call
creates optional presentation copy; failure never blocks the route.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from pydantic import BaseModel, Field

from . import config
from .api_client import call_llm


# ── Pydantic response models ──────────────────────────
class ReasonItemResponse(BaseModel):
    poi_id: str = ""
    name: str = ""
    highlight: str = ""
    matched_preferences: list[dict] = Field(default_factory=list)
    preference_match: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    recommend_reason: str = ""
    short_recommend_reason: str = ""
    confidence: float = 0.5


class RouteReasonResponse(BaseModel):
    route_recommend_reason: str = ""
    items: list[ReasonItemResponse] = Field(default_factory=list)


# ── Generic placeholder patterns to reject ─────────────
_GENERIC_PLACEHOLDERS = frozenset({
    "符合用户偏好", "符合本次路线偏好", "值得推荐", "适合用户需求",
    "环境优美，值得一去", "值得一去", "推荐", "很好",
    "本次搜索的核心目标", "符合本次路线偏好",
})


# ── System prompt ─────────────────────────────────────
_REASON_SYSTEM_PROMPT = """你是本地旅行路线的个性化推荐理由生成器。

你的任务是为每个POI生成2-4条"主标题：次标题"格式的短句推荐理由。主标题是时段/场景/行程节点，次标题是核心价值。

严格规则：
1. 只能使用输入中提供的事实和证据。
2. 禁止编造任何信息。
3. 每条POI的 recommend_reason 总字数不得超过70个中文字符（不含标点）。
4. 必须输出2-4条短句，格式为"主标题：次标题"，每条不超过24字。
5. 主标题使用：上午、中餐、下午、晚餐、夜景、亮点、交通、拍照 等场景节点词。
6. 次标题写核心价值，简洁明确，不要啰嗦。
7. 禁止输出长段落、禁止解释性文字、禁止重复POI名称。
8. short_recommend_reason 取推荐理由的第一条主标题（不含冒号和次标题），最多8字。
9. 不要输出Markdown。
10. 只输出严格JSON。
11. items数量和poi_id必须与输入POI一一对应。
12. evidence_ids 只能使用每个POI输入中的 allowed_evidence_ids；不得输出未提供的 bocha 或其他来源证据。

示例 recommend_reason：
"上午：乍浦路桥拍陆家嘴机位
中餐：Mozzarella e Vino意式美食
下午：外白渡桥赏万国建筑群"

输出格式：
{
  "route_recommend_reason": "25至60字的中文路线概括，说明路线特色。如无法生成请返回空字符串。",
  "items": [
    {
      "poi_id": "与输入完全一致",
      "name": "与输入完全一致",
      "highlight": "该地点特点",
      "preference_match": "符合哪项偏好",
      "route_fit": "路线位置价值",
      "recommend_reason": "最终展示的50至100字中文理由",
      "matched_preferences": [{"term": "冷门", "source": "explicit", "evidence": "博查摘要或热度证据"}],
      "evidence_ids": ["仅使用该POI的allowed_evidence_ids"],
      "confidence": 0.86
    }
  ]
}"""


# ── Context builder ────────────────────────────────────
def _build_poi_context(poi: dict[str, Any]) -> dict[str, Any]:
    poi_id = str(poi.get("poi_id") or poi.get("name", ""))
    allowed_evidence_ids = [f"route:{poi_id}"]
    if poi.get("typecode"):
        allowed_evidence_ids.append(f"gaode:typecode:{poi.get('typecode')}")
    if poi.get("rating") or poi.get("gaode_rating"):
        allowed_evidence_ids.append("gaode:rating")
    for term in list(poi.get("matched_keywords", []) or [])[:6]:
        if str(term).strip():
            allowed_evidence_ids.append(f"route:match:{str(term).strip()}")
    return {
        "poi_id": poi_id,
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
        "matched_facets": list(poi.get("matched_facets", []) or [])[:8],
        "matched_keywords": list(poi.get("matched_keywords", []) or [])[:10],
        "allowed_evidence_ids": allowed_evidence_ids,
    }


def _build_user_context(parsed_intent: Any, user_profile: Any, user_request: str = "") -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    ctx["user_request"] = str(user_request or getattr(parsed_intent, "user_request", "") or "")[:200]
    ctx["plan_mode"] = str(getattr(parsed_intent, "plan_mode", "exploratory") or "exploratory")
    ctx["primary_query"] = str(getattr(parsed_intent, "primary_query", "") or "")
    ctx["theme_profile"] = str(getattr(parsed_intent, "theme_profile", "") or "")
    ctx["duration"] = str(getattr(parsed_intent, "duration", "") or "")
    ctx["preferences"] = list(getattr(parsed_intent, "raw_keywords", []) or [])[:8]
    ctx["food_prefs"] = list(getattr(parsed_intent, "food_pref_keywords", []) or [])[:4]
    ctx["budget"] = getattr(parsed_intent, "budget_per_capita", None)
    ctx["constraints"] = list(getattr(parsed_intent, "other_constraints", []) or [])[:6]
    ctx["transport"] = str(getattr(parsed_intent, "transport_hint", "") or "")
    ctx["proximity"] = bool(getattr(parsed_intent, "proximity_requested", False))
    ctx["search_area"] = str(getattr(parsed_intent, "search_area_label", "") or "")
    return ctx


def _local_match_terms(poi: dict[str, Any], user_ctx: dict[str, Any]) -> list[str]:
    """Use only route facts already available to the renderer as fallback evidence."""
    terms: list[str] = []
    for field in ("matched_keywords", "matched_facets"):
        for value in poi.get(field, []) or []:
            text = str(value or "").strip()
            if text and text not in terms:
                terms.append(text)

    if not terms:
        source_terms = [
            *(user_ctx.get("preferences", []) or []),
            *(user_ctx.get("food_prefs", []) or []),
            *(user_ctx.get("constraints", []) or []),
        ]
        for value in source_terms:
            text = str(value or "").strip()
            if text and text not in terms:
                terms.append(text)
            if len(terms) >= 2:
                break
    return terms[:3]


def _local_poi_reason(poi: dict[str, Any], user_ctx: dict[str, Any]) -> tuple[str, str]:
    """Fill the same renderer fields when the optional LLM reason is unavailable."""
    kind = str(poi.get("kind", "") or "")
    category = str(poi.get("category", "") or "")
    slot = str(poi.get("display_slot", "") or "")
    slot_label = {
        "morning": "上午",
        "lunch": "午餐",
        "afternoon": "下午",
        "dinner": "晚餐",
        "evening": "夜晚",
    }.get(slot, "行程中")
    terms = _local_match_terms(poi, user_ctx)
    term_text = "、".join(terms) if terms else "本次行程"

    if kind == "meal" or category == "meal":
        detail = "贴合当前餐饮安排，方便在游览衔接处停留。"
    elif kind == "cafe" or "cafe" in category.lower() or "咖啡" in str(poi.get("name", "")):
        detail = "适合作为途中休息点，兼顾咖啡停留与行程节奏。"
    elif kind in {"park", "riverfront", "walk"}:
        detail = "适合步行停留，给路线留出轻松的活动节奏。"
    else:
        detail = "与前后地点衔接顺路，可作为本次行程的有效停留点。"

    short = _generate_short_reason(
        str(poi.get("name", "")), str(poi.get("typecode", "")), kind, category,
    )[:20]
    return f"{slot_label}：命中{term_text}，{detail}", short


def _local_route_reason(route_points: list[dict[str, Any]], user_ctx: dict[str, Any]) -> str:
    display_names = [
        str(poi.get("name", "")) for poi in route_points
        if poi.get("kind") not in {"start", "origin", "hint", "free_explore", "route_only"}
        and str(poi.get("name", ""))
    ]
    terms: list[str] = []
    for poi in route_points:
        for term in _local_match_terms(poi, user_ctx):
            if term not in terms:
                terms.append(term)
    if not terms:
        terms = [str(item) for item in (user_ctx.get("preferences", []) or [])[:3] if str(item)]
    theme = "、".join(terms[:3]) or "本次需求"
    endpoints = "到".join(display_names[:2]) if len(display_names) >= 2 else (display_names[0] if display_names else "核心地点")
    return f"路线围绕{theme}安排，串联{endpoints}等已选地点，按当前顺路顺序组织，并兼顾游览与停留节奏。"


# ── Short reason fallback generator ────────────────────
_SHORT_REASON_TEMPLATES: dict[str, list[str]] = {
    "park": [
        "在这里，时间是用来浪费的", "树比人多，呼吸都变甜了",
        "把烦恼丢在公园门口", "今天的主角是阳光和草坪",
    ],
    "museum": [
        "吹着空调，把故事慢慢逛完", "历史在玻璃后面眨了眨眼",
        "知识的殿堂，也可以很温柔",
    ],
    "zoo": [
        "今日治愈额度由动物朋友提供", "狮子老虎都在等你合影",
        "和国宝比，谁更会撒娇？",
    ],
    "aquarium": [
        "蓝色世界的入口在这里", "看海豚转圈，心情也跟着转",
    ],
    "restaurant": [
        "先别数热量，好吃才是正事", "筷子的下一站，是快乐",
        "这一口的幸福感，值得绕路",
    ],
    "cafe": [
        "咖啡是成年人白天的酒", "这杯喝完，今天就圆满了",
    ],
    "night_view": [
        "天一黑，浪漫就准时上线", "城市的星空，是万家灯火",
    ],
    "shopping": [
        "买买买不需要理由", "钱包说不，但脚步很诚实",
    ],
    "bridge": [
        "桥的那一头，藏着老故事", "走过这座桥，就走进画里了",
    ],
    "riverfront": [
        "江水滔滔，心事都带走", "散步的尽头，是橘色落日",
    ],
    "art": [
        "给眼睛喝一杯艺术的酒", "看不懂也没关系，美就够了",
    ],
    "default": [
        "藏在城市里的温柔角落", "来了就会爱上这里的空气",
        "今天的目的地，不会让你失望",
    ],
}

_PARK_TERMS = {"公园", "花园", "植物园", "绿道", "步道", "湿地"}
_MUSEUM_TERMS = {"博物馆", "科技馆", "展览馆", "美术馆", "画廊", "陈列馆"}
_ZOO_TERMS = {"动物园", "野生动物"}
_AQUARIUM_TERMS = {"水族馆", "海洋馆", "海底世界"}
_RESTAURANT_TERMS = {"餐厅", "饭店", "小吃", "火锅", "美食", "面馆", "烧烤", "日料"}
_CAFE_TERMS = {"咖啡", "茶馆", "茶饮", "甜品", "烘焙"}
_NIGHT_TERMS = {"夜景", "灯光", "夜游", "观景台", "天台"}
_SHOPPING_TERMS = {"商场", "步行街", "集市", "买手"}
_BRIDGE_TERMS = {"桥", "大桥"}
_RIVER_TERMS = {"滨江", "河畔", "码头", "江边", "湖边"}
_ART_TERMS = {"艺术", "创意", "画廊", "美术馆", "展"}


def _generate_short_reason(name: str, typecode: str = "", kind: str = "", category: str = "") -> str:
    """Generate a short, witty recommendation reason from POI metadata."""
    import random
    combined = f"{name} {category or ''} {kind or ''}"
    # Match by terms
    for term_set, template_key in [
        (_PARK_TERMS, "park"), (_MUSEUM_TERMS, "museum"),
        (_ZOO_TERMS, "zoo"), (_AQUARIUM_TERMS, "aquarium"),
        (_RESTAURANT_TERMS, "restaurant"), (_CAFE_TERMS, "cafe"),
        (_NIGHT_TERMS, "night_view"), (_SHOPPING_TERMS, "shopping"),
        (_BRIDGE_TERMS, "bridge"), (_RIVER_TERMS, "riverfront"),
        (_ART_TERMS, "art"),
    ]:
        for t in term_set:
            if t in combined:
                templates = _SHORT_REASON_TEMPLATES.get(template_key, _SHORT_REASON_TEMPLATES["default"])
                return random.choice(templates)
    return random.choice(_SHORT_REASON_TEMPLATES["default"])


# ── JSON validation ────────────────────────────────────
def _validate_reason_item(item: dict, input_poi: dict) -> tuple[bool, str, str]:
    """Validate a single DeepSeek reason item. Returns (valid, failure_reason, detail)."""
    if not isinstance(item, dict):
        return False, "not_a_dict", ""
    pid = str(item.get("poi_id", ""))
    expected_pid = str(input_poi.get("poi_id") or input_poi.get("name", ""))
    if pid != expected_pid:
        return False, "poi_id_mismatch", f"got={pid} expected={expected_pid}"
    reason = str(item.get("recommend_reason", "")).strip()
    if not reason:
        return False, "empty_recommend_reason", ""
    if len(reason) < 12 or len(reason) > 120:
        return False, "reason_length_out_of_range", f"len={len(reason)}"
    if reason in _GENERIC_PLACEHOLDERS:
        return False, "generic_placeholder", reason
    prefs = item.get("matched_preferences")
    if not prefs or not isinstance(prefs, list) or len(prefs) == 0:
        return False, "empty_matched_preferences", str(prefs)[:120]
    evidence = item.get("evidence_ids")
    if not evidence or not isinstance(evidence, list) or len(evidence) == 0:
        return False, "empty_evidence_ids", str(evidence)[:120]
    pref_match = str(item.get("preference_match", "")).strip()
    if not pref_match or pref_match in _GENERIC_PLACEHOLDERS:
        return False, "vague_or_missing_preference_match", pref_match[:120]
    return True, "", ""


# ── Main entry point ───────────────────────────────────
async def generate_exploratory_reasons(
    route_points: list[dict[str, Any]],
    parsed_intent: Any,
    user_profile: Any,
    city: str = "",
    user_request: str = "",
) -> list[dict[str, Any]]:
    """Generate independent recommendation reasons for all display POIs.

    Returns the route_points list with recommend_reason fields populated.
    Never blocks route generation on failure.
    Works for all plan modes (exploratory, planned, mixed).
    """
    t0 = time.monotonic()

    # 1. Filter: only display POIs
    display_pois = [
        p for p in route_points
        if p.get("is_display_poi") or p.get("display_order") is not None
        if p.get("kind") not in ("start", "origin", "hint", "free_explore", "route_only")
        if p.get("is_waypoint", True) is not False
    ]
    if not display_pois:
        return route_points

    bocha_count = 0
    deepseek_count = 0
    valid_count = 0
    empty_count = 0

    # 2. Build context. Recommendation copy is intentionally LLM-only: POI
    # selection has already finished, and optional web enrichment used to add
    # a slow, failure-prone dependency without changing the route itself.
    user_ctx = _build_user_context(parsed_intent, user_profile, user_request)
    poi_ctxs = [_build_poi_context(p) for p in display_pois]

    prompt = json.dumps({
        "user_context": user_ctx,
        "pois": poi_ctxs,
        "task": "为每个POI生成独立的推荐理由，并为整条路线生成一个概括推荐理由",
    }, ensure_ascii=False)

    messages = [
        {"role": "system", "content": _REASON_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    # 3. Call DeepSeek once for the whole route. Keep the output budget tight:
    # each item is short structured UI copy rather than a second planning task.
    route_reason = ""
    try:
        response = await asyncio.wait_for(
            call_llm(
                RouteReasonResponse,
                messages,
                max_tokens=config.REASON_LLM_MAX_TOKENS,
                temperature=0.3,
            ),
            timeout=config.REASON_LLM_TIMEOUT,
        )
        deepseek_count = 1

        data = response.model_dump()
        items = data.get("items", []) if isinstance(data, dict) else []
        route_reason = str(data.get("route_recommend_reason", "") if isinstance(data, dict) else "").strip()
        if route_reason and (len(route_reason) < 10 or len(route_reason) > 100):
            route_reason = ""
        if route_reason in _GENERIC_PLACEHOLDERS:
            route_reason = ""

        # Build index by poi_id
        reason_map: dict[str, dict] = {}
        for item in items:
            if isinstance(item, dict):
                pid = str(item.get("poi_id", ""))
                reason_map[pid] = item
            elif hasattr(item, "model_dump"):
                d = item.model_dump()
                pid = str(d.get("poi_id", ""))
                reason_map[pid] = d

        # Validate and write
        for i, poi in enumerate(display_pois):
            pid = str(poi.get("poi_id") or poi.get("name", ""))
            item = reason_map.get(pid, {})
            valid, failure, detail = _validate_reason_item(item, poi)
            if valid:
                poi["recommend_reason"] = str(item.get("recommend_reason", "")).strip()
                poi["short_recommend_reason"] = str(item.get("short_recommend_reason", "")).strip()[:20]
                poi["_reason_matched_prefs"] = item.get("matched_preferences", [])
                poi["_reason_evidence"] = item.get("evidence_ids", [])
                poi["_reason_confidence"] = float(item.get("confidence", 0.5))
                valid_count += 1
            else:
                fallback_reason, fallback_short_reason = _local_poi_reason(poi, user_ctx)
                poi["recommend_reason"] = poi.get("recommend_reason") or fallback_reason
                poi["short_recommend_reason"] = poi.get("short_recommend_reason") or fallback_short_reason
                fallback_terms = _local_match_terms(poi, user_ctx)
                poi["_reason_matched_prefs"] = [
                    {"term": term, "source": "route_match"} for term in fallback_terms
                ]
                poi["_reason_evidence"] = [f"route:{pid}"]
                empty_count += 1
                print(
                    f"[ReasonAudit] plan_mode={user_ctx['plan_mode']} poi_id={pid} "
                    f"poi_name={poi.get('name','')} "
                    f"matched_preferences={item.get('matched_preferences',str(item.get('preference_match',''))[:80])} "
                    f"evidence_ids={item.get('evidence_ids',str(item.get('recommend_reason',''))[:40])} "
                    f"json_valid=False preference_valid=False evidence_valid=False "
                    f"reason_written=False confidence=0.0 "
                    f"source=deepseek failure_reason={failure} detail={detail}"
                )

    except Exception as exc:
        print(
            f"[ReasonGenError] type={type(exc).__name__} "
            f"detail={exc!r}"
        )
        deepseek_count = 0
        empty_count = len(display_pois)
        for poi in display_pois:
            fallback_reason, fallback_short_reason = _local_poi_reason(poi, user_ctx)
            poi["recommend_reason"] = poi.get("recommend_reason") or fallback_reason
            poi["short_recommend_reason"] = poi.get("short_recommend_reason") or fallback_short_reason
            fallback_terms = _local_match_terms(poi, user_ctx)
            poi["_reason_matched_prefs"] = [
                {"term": term, "source": "route_match"} for term in fallback_terms
            ]
            poi["_reason_evidence"] = [
                f"route:{poi.get('poi_id') or poi.get('name', '')}"
            ]
            print(
                f"[ReasonAudit] plan_mode={user_ctx.get('plan_mode','')} poi_id={poi.get('poi_id') or poi.get('name','')} "
                f"poi_name={poi.get('name','')} "
                f"reason_written=False source=deepseek failure_reason={type(exc).__name__}"
            )

    if not route_reason:
        route_reason = _local_route_reason(display_pois, user_ctx)

    # Always write route_reason to all display POIs for frontend transport.
    # This preserves the current frontend contract even if the LLM times out.
    for poi in display_pois:
        poi["_route_recommend_reason"] = route_reason
        # v20: Fallback short reason if DeepSeek didn't provide one
        if not (poi.get("short_recommend_reason") or "").strip():
            _kind = str(poi.get("kind", "") or "")
            if _kind not in ("start", "origin", "hint", "free_explore"):
                poi["short_recommend_reason"] = _generate_short_reason(
                    poi.get("name", ""), poi.get("typecode", ""),
                    _kind, poi.get("category", ""),
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
