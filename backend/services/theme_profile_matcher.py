from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_LIBRARY_PATH = Path(__file__).with_name("theme_profile_library.json")

WEIGHTS = {
    "seed_keywords": 10.0,
    "destination_anchor_terms": 8.0,
    "macro_search_terms": 6.0,
    "micro_poi_keywords": 4.0,
    "required_terms": 2.0,
    "label": 5.0,
}


def _norm_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _unique(values: list[str], limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        clean = str(value).strip()
        if clean and clean not in seen:
            result.append(clean)
            seen.add(clean)
        if limit is not None and len(result) >= limit:
            break
    return result


@lru_cache(maxsize=1)
def load_theme_profile_library() -> dict[str, Any]:
    with _LIBRARY_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def get_all_theme_profiles() -> dict[str, dict[str, Any]]:
    return load_theme_profile_library().get("profiles", {}) or {}


def get_theme_profile(profile_id: str | None) -> dict[str, Any]:
    if not profile_id:
        return {}
    return dict(get_all_theme_profiles().get(profile_id, {}) or {})


def normalize_theme_profile_id(value: str | None, text: str = "") -> str | None:
    raw = (value or "").strip()
    profiles = get_all_theme_profiles()
    if raw in profiles:
        return raw

    alias = {
        "art": "art_culture_lifestyle", "culture": "art_culture_lifestyle",
        "art_culture": "art_culture_lifestyle", "history": "history_heritage",
        "heritage": "history_heritage", "outdoor": "outdoor_nature_sports",
        "nature": "outdoor_nature_sports", "family": "family_child_friendly",
        "parent_child": "family_child_friendly", "pet": "pet_animal_friendly",
        "night": "nightlife_bar_music", "coffee": "coffee_tea_bakery",
        "tea": "coffee_tea_bakery", "market": "market_local_life",
        "craft": "handcraft_intangible_heritage", "religion": "religion_prayer",
        "food": "food_cuisine", "wellness": "health_wellness",
        "sports": "sports_recreation", "acg": "acg_esports_games",
        "anime": "acg_esports_games", "performance": "performing_arts_comedy",
        "study": "study_work_creation", "photo": "photo_identity_fashion",
        "film": "film_location_media", "accessibility": "accessibility_inclusive",
        "tech": "future_tech_ai",
    }
    if raw in alias and alias[raw] in profiles:
        return alias[raw]

    merged = f"{raw} {text}"
    matches = match_theme_profiles(merged, top_k=1, min_score=8.0)
    return matches[0]["id"] if matches else None


def _iter_terms(profile: dict[str, Any], field: str) -> list[str]:
    values = profile.get(field, []) or []
    if isinstance(values, dict):
        merged: list[str] = []
        for items in values.values():
            merged.extend(items or [])
        return merged
    return list(values)


def score_text_against_profile(text: str, profile: dict[str, Any]) -> tuple[float, list[str]]:
    text_l = _norm_text(text)
    score = 0.0
    matched: list[str] = []

    label = profile.get("label", "")
    if label and any(part and part.lower() in text_l for part in str(label).replace("/", " ").split()):
        score += WEIGHTS["label"]

    for field, weight in WEIGHTS.items():
        if field == "label":
            continue
        for term in _iter_terms(profile, field):
            term_l = _norm_text(term)
            if term_l and term_l in text_l:
                score += weight
                matched.append(str(term))

    for terms in (profile.get("subclusters", {}) or {}).values():
        for term in terms or []:
            term_l = _norm_text(term)
            if term_l and term_l in text_l:
                score += 5.0
                matched.append(str(term))

    return score, _unique(matched, limit=20)


def match_theme_profiles(text: str, top_k: int = 3, min_score: float = 6.0) -> list[dict[str, Any]]:
    profiles = get_all_theme_profiles()
    scored: list[dict[str, Any]] = []
    for profile_id, profile in profiles.items():
        s, matched = score_text_against_profile(text, profile)
        if s >= min_score:
            scored.append({
                "id": profile_id,
                "label": profile.get("label", profile_id),
                "score": round(s, 2),
                "matched_terms": matched,
                "summary": compact_profile_summary(profile_id, profile),
            })
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:top_k]


def compact_profile_summary(profile_id: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or get_theme_profile(profile_id)
    return {
        "id": profile_id,
        "label": profile.get("label", profile_id),
        "seed_keywords": _unique(profile.get("seed_keywords", []), 12),
        "macro_search_terms": _unique(profile.get("macro_search_terms", []), 10),
        "destination_anchor_terms": _unique(profile.get("destination_anchor_terms", []), 16),
        "micro_poi_keywords": _unique(profile.get("micro_poi_keywords", []), 16),
        "required_terms": _unique(profile.get("required_terms", []), 16),
        "generic_penalty_terms": _unique(profile.get("generic_penalty_terms", []), 10),
        "excluded_terms": _unique(profile.get("excluded_terms", []), 10),
        "subclusters": {
            key: _unique(value, 8)
            for key, value in list((profile.get("subclusters", {}) or {}).items())[:8]
        },
    }


def format_profiles_for_prompt(matches: list[dict[str, Any]]) -> str:
    if not matches:
        return "无明确候选主题。"
    lines: list[str] = []
    for idx, match in enumerate(matches, start=1):
        summary = match.get("summary") or {}
        lines.append(
            f"{idx}. id={match['id']} label={summary.get('label', match['label'])} "
            f"score={match['score']} matched={match.get('matched_terms', [])}"
        )
        lines.append(f"   宏观召回参考: {summary.get('macro_search_terms', [])[:8]}")
        lines.append(f"   强锚点参考: {summary.get('destination_anchor_terms', [])[:10]}")
        lines.append(f"   微观POI参考: {summary.get('micro_poi_keywords', [])[:10]}")
        lines.append(f"   应降权泛化词: {summary.get('generic_penalty_terms', [])[:8]}")
        lines.append(f"   应排除词: {summary.get('excluded_terms', [])[:8]}")
    return "\n".join(lines)


def build_effective_theme_profile_from_library(parsed_intent: Any) -> dict[str, Any]:
    text = " ".join([
        str(getattr(parsed_intent, "theme_label", "") or ""),
        " ".join(getattr(parsed_intent, "raw_keywords", []) or []),
        " ".join(getattr(parsed_intent, "search_keywords", []) or []),
        " ".join(getattr(parsed_intent, "micro_keywords", []) or []),
        " ".join(getattr(parsed_intent, "other_constraints", []) or []),
        " ".join(getattr(parsed_intent, "micro_poi_keywords", []) or []),
    ])
    profile_id = normalize_theme_profile_id(getattr(parsed_intent, "theme_profile", None), text)
    if not profile_id:
        return {"active": False}

    profile = get_theme_profile(profile_id)
    if not profile:
        return {"active": False}

    profile = dict(profile)
    profile["id"] = profile_id
    profile["active"] = True
    profile["official"] = True

    profile["macro_search_terms"] = _unique(
        list(profile.get("macro_search_terms", []) or []) + list(getattr(parsed_intent, "search_keywords", []) or []),
        18,
    )
    profile["micro_poi_keywords"] = _unique(
        list(profile.get("micro_poi_keywords", []) or [])
        + list(getattr(parsed_intent, "micro_poi_keywords", []) or [])
        + list(getattr(parsed_intent, "micro_keywords", []) or []),
        28,
    )
    profile["required_terms"] = _unique(
        list(profile.get("required_terms", []) or []) + list(getattr(parsed_intent, "micro_required_terms", []) or []),
        32,
    )
    profile["excluded_terms"] = _unique(
        list(profile.get("excluded_terms", []) or []) + list(getattr(parsed_intent, "micro_excluded_terms", []) or []),
        32,
    )
    profile["diversity_hint"] = _unique(
        list(profile.get("diversity_hint", []) or []) + list(getattr(parsed_intent, "micro_diversity_hint", []) or []),
        12,
    )

    # 关键修复：library json 用 macro_search_terms / micro_poi_keywords，
    # 但 Step3 读取 search_terms / micro_keywords。统一补齐别名。
    intent_micro_terms = (
        list(getattr(parsed_intent, "micro_poi_keywords", []) or [])
        + list(getattr(parsed_intent, "micro_keywords", []) or [])
    )
    profile["search_terms"] = _unique(
        list(profile.get("search_terms", []) or [])
        + list(profile.get("micro_poi_keywords", []) or [])
        + intent_micro_terms,
        18,
    )
    profile["micro_keywords"] = _unique(
        list(profile.get("micro_keywords", []) or [])
        + list(profile.get("micro_poi_keywords", []) or [])
        + intent_micro_terms,
        32,
    )

    return profile


def build_theme_recall_queries(profile: dict[str, Any], city: str, limit: int = 4) -> list[str]:
    if not profile or not profile.get("active", True):
        return []
    city_short = city[:-1] if city.endswith("市") else city
    macro = _unique(profile.get("macro_search_terms", []), 10)
    anchors = _unique(profile.get("destination_anchor_terms", []), 24)
    micro = _unique(profile.get("micro_poi_keywords", []), 12)

    queries: list[str] = []
    if macro or anchors:
        queries.append(f"{city_short} {' '.join(macro[:4])} {' '.join(anchors[:8])}")
    if anchors:
        queries.append(f"{city_short} 主题路线 推荐 {' '.join(anchors[8:18] or anchors[:10])}")
    if micro:
        queries.append(f"{city_short} 小众 高质量 {' '.join(micro[:10])}")
    for key, values in (profile.get("subclusters", {}) or {}).items():
        vals = _unique(values, 8)
        if vals:
            queries.append(f"{city_short} {profile.get('label', '')} {key} {' '.join(vals)}")
        if len(queries) >= limit:
            break
    return _unique(queries, limit)
