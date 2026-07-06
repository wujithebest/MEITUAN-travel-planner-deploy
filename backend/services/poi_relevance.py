"""Unified POI relevance validation — answers "is this POI what the user actually asked for?"

Used by Step2 (filter recalled candidates) and Step3 (validate final waypoints).
All rules are data-driven; no city- or keyword-specific patches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .poi_typecodes import matches_typecode, split_typecodes

# ── v20 品类族映射 — 数据驱动，不含具体城市/POI名称 ──
# Each family defines identity terms, allowed typecode prefixes, and excluded prefixes.
# Only searchable categories go here — concrete POIs NEVER appear.

CATEGORY_FAMILIES: dict[str, dict[str, Any]] = {
    "convenience_store": {
        "label": "便利店",
        "required_identity_terms": [
            "便利店", "便利", "超市", "小卖部", "士多", "杂货",
        ],
        "allowed_typecode_prefixes": [
            "060200", "060201",  # 便利店/小卖部
        ],
        "excluded_typecode_prefixes": ["05", "11"],
        "synonyms": ["便利店", "小卖部"],
    },
    "market_collectibles": {
        "label": "古玩/收藏品市场",
        "required_identity_terms": [
            "古玩", "文玩", "收藏品", "旧货", "古董", "钱币", "邮票",
            "古玩城", "收藏品市场",
        ],
        "allowed_typecode_prefixes": [
            "0612",  # 购物服务-古玩/收藏品/旧货
            "1907",  # 古玩/收藏品
        ],
        "excluded_typecode_prefixes": ["05", "11"],  # 餐饮, 风景名胜
        "synonyms": ["古玩市场", "旧货市场", "文玩市场", "收藏品市场", "古玩城"],
    },
    "market_flower_pet": {
        "label": "花鸟/宠物市场",
        "required_identity_terms": [
            "花鸟", "花卉", "鲜花", "宠物", "鸟", "鱼虫",
            "花市", "花鸟鱼虫",
        ],
        "allowed_typecode_prefixes": [
            "0611",  # 花鸟鱼虫市场
            "9914",  # 宠物商店/服务
        ],
        "excluded_typecode_prefixes": ["05"],
        "synonyms": ["花鸟市场", "宠物市场", "花卉市场"],
    },
    "flower_market_direct": {
        "label": "花艺/鲜花店",
        "required_identity_terms": [
            "花店", "花市", "花艺", "鲜花", "花卉", "花坊", "插花",
            "盆栽",
        ],
        "allowed_typecode_prefixes": [
            "061100", "0611",  # 花鸟鱼虫市场
        ],
        "excluded_typecode_prefixes": ["05", "11", "08"],
        "synonyms": ["花艺市场", "花店", "花市"],
    },
    "handcraft_intangible": {
        "label": "非遗手作/手工艺",
        "required_identity_terms": [
            "非遗", "手作", "手工", "工坊", "体验坊", "手工艺",
            "传统工艺", "DIY", "陶艺", "扎染", "木版", "刺绣",
        ],
        "allowed_typecode_prefixes": [
            "080500", "061202",  # 手工艺 / 工艺美术
        ],
        "excluded_typecode_prefixes": ["05", "11"],
        "synonyms": ["非遗手作", "手作体验", "工坊"],
    },
    "wood_craft": {
        "label": "木材工作坊/木艺",
        "required_identity_terms": [
            "木工坊", "木作", "木艺", "木工体验", "木工", "木器",
            "木制品", "木艺工作室",
        ],
        "allowed_typecode_prefixes": [
            "080500", "061200",
        ],
        "excluded_typecode_prefixes": ["05", "11"],
        "synonyms": ["木材工作坊", "木工坊", "木作体验"],
    },
    "retail_book_stationery": {
        "label": "书店/文具",
        "required_identity_terms": [
            "书店", "书局", "书城", "文具", "手账", "独立书店",
            "概念书店", "图书馆",
        ],
        "allowed_typecode_prefixes": [
            "061205",  # v20 fix: actual bookstore code, NOT 060400
            "0609",    # 文具/办公用品
        ],
        "excluded_typecode_prefixes": ["05", "08"],
        "synonyms": ["书店", "城市书房"],
    },
    "entertainment_script_game": {
        "label": "剧本杀/桌游/密室",
        "required_identity_terms": [
            "剧本杀", "桌游", "密室", "推理", "逃逸", "实景",
            "剧本推理",
        ],
        "allowed_typecode_prefixes": ["0804", "0805", "0810"],
        "excluded_typecode_prefixes": ["05", "14"],
        "synonyms": ["剧本杀", "桌游店", "密室逃脱"],
    },
    "cultural_art": {
        "label": "美术馆/博物馆/展览",
        "required_identity_terms": [
            "美术", "博物馆", "展览", "画廊", "艺术", "当代",
            "雕塑", "画展", "非遗", "收藏", "文物",
        ],
        "allowed_typecode_prefixes": ["11", "1402", "1403", "1404"],
        "excluded_typecode_prefixes": ["05", "08"],
        "synonyms": ["美术馆", "博物馆", "画廊"],
    },
}

# 搜索停用词 — 从关键词中剔除，不参与 POI 身份匹配
KEYWORD_STOP_WORDS: set[str] = {
    "推荐", "附近", "周边", "路线", "攻略", "打卡", "拍照", "游玩",
    "购物", "逛街", "一日游", "半日游", "探店",
}

# 城市名参与计分的禁止模式
_CITY_NAME_IN_TEXT_PATTERN = re.compile(
    r"北京|上海|天津|重庆|广州|深圳|杭州|苏州|南京|成都|武汉|西安"
)


# ── Data structures ─────────────────────────────────────
@dataclass
class PoiRelevanceEvidence:
    accepted: bool
    score: float
    query_match: bool
    identity_term_hits: list[str] = field(default_factory=list)
    typecode_match: bool = False
    theme_term_hits: list[str] = field(default_factory=list)
    excluded_term_hits: list[str] = field(default_factory=list)
    competing_theme_hits: list[str] = field(default_factory=list)
    matched_query: str = ""
    rejection_reasons: list[str] = field(default_factory=list)


# ── Helpers ─────────────────────────────────────────────
def _strip_city_from_query(query: str) -> str:
    """Remove known city names so they don't cause false identity matches."""
    return _CITY_NAME_IN_TEXT_PATTERN.sub("", query).strip()


def _clean_keyword_tokens(keyword: str) -> list[str]:
    """Split and clean a search keyword into meaningful category tokens."""
    body = _strip_city_from_query(keyword)
    tokens = re.split(r"[\s,，、]+", body)
    return [
        t for t in tokens
        if len(t) >= 2 and t not in KEYWORD_STOP_WORDS
    ]


def _poi_text(poi: dict[str, Any]) -> str:
    return " ".join(str(poi.get(f, "") or "") for f in (
        "name", "type", "typecode", "category",
        "address", "business_area",
    )).lower()


def _match_term(poi_text: str, term: str) -> bool:
    """Single character terms are never positive evidence."""
    if len(term) < 2:
        return False
    return term.lower() in poi_text


# ── Main scoring function ───────────────────────────────
def score_poi_against_intent(
    poi: dict[str, Any],
    parsed_intent: Any,
    theme_profile: dict[str, Any] | None = None,
    matched_query: str = "",
) -> PoiRelevanceEvidence:
    """Score a single POI candidate against the user's primary intent.

    Priority: 1) primary_query, 2) POI identity fields, 3) theme profile, 4) distance/rating.
    """

    poi_id_text = _poi_text(poi)
    poi_name = str(poi.get("name", "") or "")
    poi_typecode = str(poi.get("typecode", "") or "")
    poi_category = str(poi.get("category", "") or "")

    rejection_reasons: list[str] = []
    identity_hits: list[str] = []
    theme_hits: list[str] = []
    excluded_hits: list[str] = []
    query_matched = False

    # ── Extract primary intent ──
    primary_query: str = getattr(parsed_intent, "primary_query", "") or ""
    primary_required: list[str] = list(
        getattr(parsed_intent, "primary_required_terms", []) or []
    )
    primary_excluded: list[str] = list(
        getattr(parsed_intent, "primary_excluded_terms", []) or []
    )
    poi_query_type: str = getattr(parsed_intent, "poi_query_type", "") or ""
    allowed_typecodes: list[str] = list(
        getattr(parsed_intent, "allowed_typecode_prefixes", []) or []
    )
    excluded_typecodes: list[str] = list(
        getattr(parsed_intent, "excluded_typecode_prefixes", []) or []
    )

    # ── Check excluded terms ──
    for term in primary_excluded:
        if _match_term(poi_id_text, term):
            excluded_hits.append(term)
    if theme_profile:
        for term in (theme_profile.get("excluded_terms", []) or []):
            if _match_term(poi_id_text, str(term)):
                excluded_hits.append(str(term))
    if excluded_hits:
        return PoiRelevanceEvidence(
            accepted=False, score=-100,
            query_match=False,
            excluded_term_hits=excluded_hits,
            matched_query=matched_query,
            rejection_reasons=[f"excluded_terms: {excluded_hits}"],
        )

    # ── Check competing theme ──
    competing_hits: list[str] = []
    if theme_profile:
        competing = theme_profile.get("excluded_terms", []) or []
        for term in competing:
            if _match_term(poi_id_text, str(term)):
                competing_hits.append(str(term))

    # ── Typecode check (v20: use matches_typecode for compound code support) ──
    typecode_ok = True
    if excluded_typecodes:
        if matches_typecode(poi_typecode, excluded_typecodes):
            typecode_ok = False
            rejection_reasons.append(f"excluded_typecode_prefix={excluded_typecodes}")

    # ── Identity term check (primary_query + required_terms) ──
    query_tokens = _clean_keyword_tokens(primary_query) if primary_query else []
    for token in query_tokens:
        if _match_term(poi_id_text, token):
            identity_hits.append(token)
            query_matched = True

    for term in primary_required:
        if _match_term(poi_id_text, str(term)):
            if term not in identity_hits:
                identity_hits.append(str(term))

    # ── POI name check against primary query ──
    if not query_matched and primary_query:
        clean_query = _strip_city_from_query(primary_query)
        query_chars = set(clean_query)
        name_chars = set(poi_name)
        overlap = query_chars & name_chars
        # Require at least 2-char overlap for Chinese category names
        if len(overlap) >= 2:
            query_matched = True
            identity_hits.append(f"name_overlap:{clean_query[:6]}")

    # ── Theme profile evidence (secondary) ──
    if theme_profile:
        for field in ("required_terms", "micro_poi_keywords"):
            for term in (theme_profile.get(field, []) or []):
                t = str(term)
                if len(t) >= 2 and _match_term(poi_id_text, t):
                    theme_hits.append(t)
        # v20: Typecode-based theme evidence (e.g. 海洋馆/动物园 for family_child_friendly)
        _theme_allowed_tc = theme_profile.get("allowed_typecode_prefixes", []) or []
        if _theme_allowed_tc and not theme_hits:
            if matches_typecode(poi_typecode, _theme_allowed_tc):
                theme_hits.append(f"_tc_match:{poi_typecode[:6]}")
        # v20: Name-based theme evidence from allowed_name_terms (e.g. 海洋馆/动物园)
        _theme_name_terms = theme_profile.get("allowed_name_terms", []) or []
        for tn in _theme_name_terms:
            tns = str(tn)
            if len(tns) >= 2 and _match_term(poi_id_text, tns):
                if tns not in theme_hits:
                    theme_hits.append(tns)
    category_family_hits: list[str] = []
    if primary_query:
        for family_id, family in CATEGORY_FAMILIES.items():
            for syn in family.get("synonyms", []):
                if syn in primary_query.lower() or primary_query.lower() in syn:
                    # Expand allowed typecodes
                    if not allowed_typecodes:
                        allowed_typecodes = list(
                            family.get("allowed_typecode_prefixes", [])
                        )
                    if not excluded_typecodes:
                        excluded_typecodes = list(
                            family.get("excluded_typecode_prefixes", [])
                        )
                    for term in family.get("required_identity_terms", []):
                        if _match_term(poi_id_text, str(term)):
                            category_family_hits.append(str(term))
                    identity_hits.extend(category_family_hits)

    # ── Allowed typecode bonus (v20: compound code support) ──
    if allowed_typecodes and poi_typecode:
        if matches_typecode(poi_typecode, allowed_typecodes):
            typecode_ok = True
        else:
            # Not in allowed list — reduce score significantly
            if not identity_hits and not theme_hits:
                typecode_ok = False
                rejection_reasons.append(
                    f"typecode {poi_typecode[:4]} not in allowed {allowed_typecodes}"
                )

    # ── Restaurant detection for non-meal intents (v20: compound code) ──
    # v21: Cafe exemption — 0504xx typecode is not restaurant
    _is_cafe_typecode = matches_typecode(poi_typecode, ["0504"])
    _is_cafe_query = (
        str(getattr(parsed_intent, "category_id", "") or "") == "cafe"
        or any(c in str(getattr(parsed_intent, "primary_query", "") or "") for c in ["咖啡", "cafe", "coffee"])
    )
    if _is_cafe_query and _is_cafe_typecode:
        is_restaurant = False  # cafe query + 0504 typecode → not a restaurant
    else:
        is_restaurant = matches_typecode(poi_typecode, ["05"]) or (
            any(t in (poi_category + poi_name).lower() for t in [
                "餐厅", "饭馆", "饭店", "美食", "小吃", "面馆", "火锅",
                "川菜", "粤菜", "日料", "韩餐", "西餐",
            ])
        )
    explicit_meal = bool(getattr(parsed_intent, "explicit_meal_intent", False))
    if is_restaurant and not explicit_meal and poi_query_type not in ("", None):
        rejection_reasons.append("restaurant_in_non_meal_intent")

    # ── Score ──
    score = 0.0
    if identity_hits:
        score += len(identity_hits) * 20.0
    if theme_hits:
        score += len(theme_hits) * 4.0
    if typecode_ok:
        score += 10.0
    # v21: Cafe no penalty
    if is_restaurant and not _is_cafe_query and not explicit_meal and poi_query_type not in ("", None):
        score -= 80.0
    if rejection_reasons:
        score -= 50.0

    is_theme = (poi_query_type == "theme_route")
    has_any_positive = bool(identity_hits or theme_hits)
    # v20: For restaurant queries, typecode match alone is sufficient evidence
    is_meal_query = (poi_query_type == "poi_category" and explicit_meal and typecode_ok)
    accepted = (
        (identity_hits or is_meal_query or (theme_hits and typecode_ok) or (is_theme and has_any_positive))
        and not rejection_reasons
        and score > 0
    )

    return PoiRelevanceEvidence(
        accepted=accepted,
        score=round(score, 2),
        query_match=query_matched,
        identity_term_hits=identity_hits,
        typecode_match=typecode_ok,
        theme_term_hits=theme_hits,
        excluded_term_hits=excluded_hits,
        competing_theme_hits=competing_hits,
        matched_query=matched_query,
        rejection_reasons=rejection_reasons,
    )


# ── Audit logger ────────────────────────────────────────
def recall_audit_log(
    primary_query: str,
    poi_query_type: str,
    candidate: dict[str, Any],
    evidence: PoiRelevanceEvidence,
) -> str:
    return (
        f"[RecallAudit] "
        f"primary_query={primary_query!r} "
        f"poi_query_type={poi_query_type} "
        f"candidate={candidate.get('name','')!r} "
        f"matched_query={evidence.matched_query!r} "
        f"typecode={candidate.get('typecode','')} "
        f"identity_hits={evidence.identity_term_hits} "
        f"theme_hits={evidence.theme_term_hits} "
        f"accepted={evidence.accepted} "
        f"score={evidence.score} "
        f"rejection_reasons={evidence.rejection_reasons}"
    )
