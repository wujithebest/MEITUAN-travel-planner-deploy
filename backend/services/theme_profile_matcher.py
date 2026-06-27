from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

_LIBRARY_PATH = Path(__file__).with_name("theme_profile_library.json")

# ── 字段权重 ──────────────────────────────────────────
FIELD_WEIGHTS = {
    "exact_activity_terms": 100.0,
    "seed_keywords": 20.0,
    "destination_anchor_terms": 10.0,
    "macro_search_terms": 8.0,
    "micro_poi_keywords": 6.0,
    "required_terms": 2.0,
    "subclusters": 4.0,
    "label": 3.0,
}

# 禁止放入 exact_activity_terms 的泛词
FORBIDDEN_EXACT_TERMS: set[str] = {
    "体验", "活动", "娱乐", "放松", "有趣", "推荐", "拍照", "摄影",
    "角色扮演", "推理", "电影", "运动", "游玩", "游览", "休闲",
    "打卡", "网红", "热门", "好玩", "刺激", "安静", "舒适",
    "文化", "艺术", "历史", "自然", "科技", "创意", "设计",
}

# 英文词边界匹配模式
_ENG_WORD_PATTERN = re.compile(r'\b[a-z0-9]+\b', re.IGNORECASE)


# ── 数据结构 ──────────────────────────────────────────
@dataclass(frozen=True)
class ThemeCandidate:
    profile_id: str
    label: str
    score: float
    raw_score: float
    auxiliary_score: float
    matched_terms: tuple[str, ...]
    exact_activity_terms: tuple[str, ...]
    matched_fields: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class ThemeDecision:
    profile_id: str | None
    label: str | None
    confidence: float
    source: str
    reason: str
    llm_profile: str | None
    candidates: tuple[ThemeCandidate, ...]


@dataclass(frozen=True)
class ThemePoiEvidence:
    score: float
    accepted: bool
    positive_hits: tuple[str, ...]
    generic_penalty_hits: tuple[str, ...]
    excluded_hits: tuple[str, ...]
    source_hits: tuple[str, ...]


DIRECT_MUNICIPALITIES = {
    "北京": "北京市",
    "北京市": "北京市",
    "上海": "上海市",
    "上海市": "上海市",
    "天津": "天津市",
    "天津市": "天津市",
    "重庆": "重庆市",
    "重庆市": "重庆市",
}
_CITY_PREFIX_WITH_SUFFIX = re.compile(r"^\s*[一-龥]{2,12}市\s*")


# ── 基础工具 ──────────────────────────────────────────
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


def normalize_city_name(value: Any) -> str:
    """Normalize an authoritative administrative city label."""
    if isinstance(value, list):
        value = value[0] if value else ""
    text = str(value or "").strip()
    if not text:
        return ""
    if text in DIRECT_MUNICIPALITIES:
        return DIRECT_MUNICIPALITIES[text]
    match = re.search(r"([一-龥]{2,12}市)", text)
    if match:
        return match.group(1)
    return f"{text}市" if len(text) >= 2 else text


def city_short_name(city: str) -> str:
    normalized = normalize_city_name(city)
    return normalized[:-1] if normalized.endswith("市") else normalized


def strip_search_city_prefix(keyword: str, resolved_city: str) -> str:
    """Remove a city prefix from an LLM keyword before backend canonicalization.

    The LLM is asked to return keyword bodies, but this keeps old or malformed
    outputs safe. We only strip an authoritative current-city prefix, a direct
    municipality, or a token explicitly ending in 市; arbitrary first words are
    never removed.
    """
    body = re.sub(r"\s+", " ", str(keyword or "").strip())
    if not body:
        return ""
    normalized = normalize_city_name(resolved_city)
    short = city_short_name(normalized)
    prefixes = sorted(
        {normalized, short, *DIRECT_MUNICIPALITIES.keys()},
        key=len,
        reverse=True,
    )
    for prefix in prefixes:
        if prefix and (body == prefix or body.startswith(f"{prefix} ")):
            body = body[len(prefix):].strip()
            break
    body = _CITY_PREFIX_WITH_SUFFIX.sub("", body).strip()
    return body


def canonicalize_search_keywords(
    keywords: list[str],
    resolved_city: str,
    *,
    limit: int = 8,
) -> list[str]:
    """Build every search keyword from one authoritative city label."""
    city = city_short_name(resolved_city)
    if not city:
        return _unique([str(item).strip() for item in keywords], limit)
    bodies = _unique(
        [strip_search_city_prefix(item, resolved_city) for item in keywords],
        limit,
    )
    return [f"{city} {body}" for body in bodies if body][:limit]


def _profile_terms(profile: dict[str, Any], field_name: str) -> list[str]:
    values = profile.get(field_name, []) or []
    if isinstance(values, dict):
        return _unique([term for items in values.values() for term in (items or [])])
    return _unique(list(values))


def _poi_field(poi: Any, field_name: str) -> Any:
    if isinstance(poi, dict):
        return poi.get(field_name)
    return getattr(poi, field_name, None)


def score_poi_against_theme(
    poi: Any,
    profile: dict[str, Any],
    source_text: str = "",
) -> ThemePoiEvidence:
    """Score a POI using its own identity; web text is only weak evidence.

    A POI must contain at least one positive theme term in its own name,
    address, type or category. This prevents an article that happens to mention
    a zoo or park from turning that place into an art/culture destination.
    """
    own_text = " ".join(
        str(_poi_field(poi, field_name) or "")
        for field_name in ("name", "address", "type", "typecode", "category")
    ).lower()
    source_l = str(source_text or "").lower()

    excluded_hits = _unique([
        term for term in _profile_terms(profile, "excluded_terms")
        if term and term.lower() in own_text
    ])
    if excluded_hits:
        return ThemePoiEvidence(
            score=-100.0,
            accepted=False,
            positive_hits=(),
            generic_penalty_hits=(),
            excluded_hits=tuple(excluded_hits),
            source_hits=(),
        )

    weighted_fields = {
        "destination_anchor_terms": 16.0,
        "micro_poi_keywords": 8.0,
        "required_terms": 6.0,
        "subclusters": 4.0,
    }
    positive_weights: dict[str, float] = {}
    source_hits: list[str] = []
    for field_name, weight in weighted_fields.items():
        for term in _profile_terms(profile, field_name):
            term_l = term.lower()
            if term_l and term_l in own_text:
                positive_weights[term] = max(weight, positive_weights.get(term, 0.0))
            elif term_l and term_l in source_l:
                source_hits.append(term)

    generic_hits = _unique([
        term for term in _profile_terms(profile, "generic_penalty_terms")
        if term and term.lower() in own_text
    ])
    positive_hits = _unique(list(positive_weights))
    # Source snippets may break ties only after the POI proves its own relevance.
    source_bonus = min(4.0, len(_unique(source_hits)) * 0.5) if positive_hits else 0.0
    score = sum(positive_weights.values()) + source_bonus - len(generic_hits) * 12.0
    return ThemePoiEvidence(
        score=round(score, 2),
        accepted=bool(positive_hits) and score > 0,
        positive_hits=tuple(positive_hits),
        generic_penalty_hits=tuple(generic_hits),
        excluded_hits=(),
        source_hits=tuple(_unique(source_hits, 12)),
    )


def poi_has_competing_theme(
    poi: Any,
    current_profile_id: str,
    *,
    min_score: float = 16.0,
) -> bool:
    """Return True when a neutral POI strongly belongs to another theme."""
    for profile_id, profile in get_all_theme_profiles().items():
        if profile_id == current_profile_id:
            continue
        evidence = score_poi_against_theme(poi, profile)
        if evidence.accepted and evidence.score >= min_score:
            return True
    return False


# ── 加载 ──────────────────────────────────────────────
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


# ── 词索引 ────────────────────────────────────────────
@lru_cache(maxsize=1)
def build_term_profile_index() -> dict[str, set[str]]:
    """扫描所有主题的所有参与匹配字段，生成 关键词 → 主题ID集合 索引。"""
    profiles = get_all_theme_profiles()
    index: dict[str, set[str]] = {}
    text_fields = [
        "seed_keywords", "destination_anchor_terms", "macro_search_terms",
        "micro_poi_keywords", "required_terms", "exact_activity_terms",
    ]
    for pid, profile in profiles.items():
        for field in text_fields:
            values = profile.get(field, []) or []
            if isinstance(values, dict):
                for items in values.values():
                    for term in items or []:
                        t = str(term).strip()
                        if t:
                            index.setdefault(t, set()).add(pid)
            elif isinstance(values, list):
                for term in values:
                    t = str(term).strip()
                    if t:
                        index.setdefault(t, set()).add(pid)
        sub = profile.get("subclusters", {}) or {}
        if isinstance(sub, dict):
            for items in sub.values():
                for term in items or []:
                    t = str(term).strip()
                    if t:
                        index.setdefault(t, set()).add(pid)
    return index


# ── 文本匹配 ──────────────────────────────────────────
def term_matches(text: str, term: str) -> bool:
    """中文完整包含；英文/数字词边界匹配；不反向包含。"""
    text_s = text.strip()
    term_s = term.strip()
    if not text_s or not term_s:
        return False

    text_l = text_s.lower()
    term_l = term_s.lower()

    # 包含纯中文/中日韩字符：完整字符串包含
    if re.search(r'[一-鿿㐀-䶿豈-﫿]', term_l):
        return term_l in text_l

    # 英文/数字：单词边界匹配
    eng_words = _ENG_WORD_PATTERN.findall(term_l)
    if eng_words:
        for w in eng_words:
            if not re.search(rf'\b{re.escape(w)}\b', text_l):
                return False
        return True

    # 其他：简单包含
    return term_l in text_l


# ── 排名 ──────────────────────────────────────────────
def rank_theme_profiles(
    raw_text: str,
    auxiliary_text: str = "",
    top_k: int = 5,
) -> list[ThemeCandidate]:
    """统一文本匹配并排序主题候选。"""
    profiles = get_all_theme_profiles()
    term_index = build_term_profile_index()

    raw_l = _norm_text(raw_text)
    aux_l = _norm_text(auxiliary_text)

    text_fields = [
        "seed_keywords", "destination_anchor_terms", "macro_search_terms",
        "micro_poi_keywords", "required_terms",
    ]

    def _field_terms(profile: dict, field: str) -> list[str]:
        v = profile.get(field, []) or []
        if isinstance(v, dict):
            merged: list[str] = []
            for items in v.values():
                merged.extend(items or [])
            return merged
        return list(v)

    # 预计算每个（关键词, profile_id）的命中状态和冲突数
    # raw 命中
    raw_hit: dict[tuple[str, str], bool] = {}
    aux_hit: dict[tuple[str, str], bool] = {}
    exact_hit: dict[str, set[str]] = {}  # term -> set of profile_ids (raw only)

    for pid, profile in profiles.items():
        for term in _field_terms(profile, "exact_activity_terms"):
            t = str(term).strip()
            if t and term_matches(raw_l, t):
                exact_hit.setdefault(t, set()).add(pid)

        for field in text_fields:
            for term in _field_terms(profile, field):
                t = str(term).strip()
                key = (t, pid)
                if t and term_matches(raw_l, t):
                    raw_hit[key] = True
                if t and term_matches(aux_l, t):
                    aux_hit[key] = True

        # label
        label = str(profile.get("label", "")).lower()
        if label and any(p and p in raw_l for p in label.replace("/", " ").split()):
            raw_hit[("__label__", pid)] = True
        if label and any(p and p in aux_l for p in label.replace("/", " ").split()):
            aux_hit[("__label__", pid)] = True

    # 计算每个关键词的冲突数（用于普通字段衰减）
    term_conflict_count: dict[str, int] = {}
    for pid, profile in profiles.items():
        for field in text_fields:
            for term in _field_terms(profile, field):
                t = str(term).strip()
                if t not in term_conflict_count:
                    profiles_with_term = term_index.get(t, set())
                    term_conflict_count[t] = max(1, len(profiles_with_term))

    candidates: list[ThemeCandidate] = []
    for pid, profile in profiles.items():
        raw_score = 0.0
        aux_score = 0.0
        matched_terms: list[str] = []
        matched_fields: dict[str, list[str]] = {}
        exact_matched: list[str] = []

        # exact_activity_terms (raw only)
        for term in _field_terms(profile, "exact_activity_terms"):
            t = str(term).strip()
            if exact_hit.get(t, set()) == {pid}:
                exact_matched.append(t)
                raw_score += FIELD_WEIGHTS["exact_activity_terms"]
                matched_fields.setdefault("exact_activity_terms", []).append(t)
            elif exact_hit.get(t, set()):
                # 冲突：记录但不加分
                exact_matched.append(t)

        for field in text_fields:
            for term in _field_terms(profile, field):
                t = str(term).strip()
                key = (t, pid)
                conflict = term_conflict_count.get(t, 1)

                if raw_hit.get(key):
                    effective = FIELD_WEIGHTS[field] / max(1, conflict)
                    raw_score += effective
                    matched_terms.append(t)
                    matched_fields.setdefault(field, []).append(t)

                if aux_hit.get(key):
                    effective = FIELD_WEIGHTS[field] * 0.2 / max(1, conflict)
                    aux_score += effective
                    matched_fields.setdefault(f"{field}_aux", []).append(t)

        # subclusters
        sub = profile.get("subclusters", {}) or {}
        if isinstance(sub, dict):
            for items in sub.values():
                for term in items or []:
                    t = str(term).strip()
                    if t and term_matches(raw_l, t):
                        raw_score += FIELD_WEIGHTS["subclusters"]
                        matched_terms.append(t)
                        matched_fields.setdefault("subclusters", []).append(t)
                    if t and term_matches(aux_l, t):
                        aux_score += FIELD_WEIGHTS["subclusters"] * 0.2
                        matched_fields.setdefault("subclusters_aux", []).append(t)

        # label
        if raw_hit.get(("__label__", pid)):
            raw_score += FIELD_WEIGHTS["label"]
        if aux_hit.get(("__label__", pid)):
            aux_score += FIELD_WEIGHTS["label"] * 0.2

        total = raw_score + aux_score
        if total > 0 or exact_matched:
            candidates.append(ThemeCandidate(
                profile_id=pid,
                label=profile.get("label", pid),
                score=round(total, 2),
                raw_score=round(raw_score, 2),
                auxiliary_score=round(aux_score, 2),
                matched_terms=tuple(_unique(matched_terms, 20)),
                exact_activity_terms=tuple(exact_matched),
                matched_fields={k: tuple(v) for k, v in matched_fields.items()},
            ))

    # 排序：总分 desc → raw_score desc → 最长命中词长度 desc → profile_id
    candidates.sort(key=lambda c: (
        -c.score,
        -c.raw_score,
        -max((len(t) for t in c.matched_terms), default=0),
        c.profile_id,
    ))
    return candidates[:top_k]


# ── 决策 ──────────────────────────────────────────────
def resolve_theme_profile(
    llm_profile: str | None,
    raw_text: str,
    auxiliary_text: str = "",
) -> ThemeDecision:
    """完整主题决策：强词锁定 + 高分 + LLM辅助 + 无主题回退。"""
    candidates = rank_theme_profiles(raw_text, auxiliary_text)
    top1 = candidates[0] if candidates else None
    top2 = candidates[1] if len(candidates) > 1 else None
    margin = (top1.score - top2.score) if top2 else (top1.score if top1 else 0.0)

    # A: unique exact_activity_term
    if top1 and top1.exact_activity_terms:
        return ThemeDecision(
            profile_id=top1.profile_id,
            label=top1.label,
            confidence=1.0,
            source="rule_exact",
            reason="unique_exact_activity_term",
            llm_profile=llm_profile,
            candidates=tuple(candidates),
        )

    # B: high score + margin
    if top1 and top1.score >= 20 and margin >= 10:
        conf = min(0.99, 0.75 + margin / 100)
        return ThemeDecision(
            profile_id=top1.profile_id,
            label=top1.label,
            confidence=round(conf, 2),
            source="rule_high_confidence",
            reason="high_score_and_margin",
            llm_profile=llm_profile,
            candidates=tuple(candidates),
        )

    # C: ambiguous — LLM selects if in top 3
    if top1 and top1.score >= 8:
        top3_ids = {c.profile_id for c in candidates[:3]}
        profiles = get_all_theme_profiles()
        if llm_profile and llm_profile in profiles and llm_profile in top3_ids:
            p = profiles[llm_profile]
            return ThemeDecision(
                profile_id=llm_profile,
                label=p.get("label", llm_profile),
                confidence=0.65,
                source="llm_ambiguous",
                reason="ambiguous_rule_candidates_llm_selected",
                llm_profile=llm_profile,
                candidates=tuple(candidates),
            )
        return ThemeDecision(
            profile_id=None,
            label=None,
            confidence=0.0,
            source="generic_fallback",
            reason="ambiguous_without_valid_llm_candidate",
            llm_profile=llm_profile,
            candidates=tuple(candidates),
        )

    # D: insufficient
    return ThemeDecision(
        profile_id=None,
        label=None,
        confidence=0.0,
        source="generic_fallback",
        reason="insufficient_theme_evidence",
        llm_profile=llm_profile,
        candidates=tuple(candidates),
    )


# ── 兼容包装 ──────────────────────────────────────────
def normalize_theme_profile_id(value: str | None, text: str = "") -> str | None:
    """只负责 ID 和别名规范化，不自行决策主题。"""
    raw = (value or "").strip()
    if not raw:
        return None
    profiles = get_all_theme_profiles()
    if raw in profiles:
        return raw

    alias: dict[str, str] = {
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
    return None


# ── 向后兼容函数 ──────────────────────────────────────
def score_text_against_profile(text: str, profile: dict[str, Any]) -> tuple[float, list[str]]:
    """旧版打分（保留兼容）。"""
    candidates = rank_theme_profiles(raw_text=text, auxiliary_text="", top_k=1)
    for c in candidates:
        if c.profile_id == profile.get("id", ""):
            return c.raw_score, list(c.matched_terms)
    return 0.0, []


def match_theme_profiles(text: str, top_k: int = 3, min_score: float = 6.0) -> list[dict[str, Any]]:
    """旧版匹配接口（保留兼容）。"""
    candidates = rank_theme_profiles(raw_text=text, auxiliary_text="", top_k=top_k)
    result: list[dict[str, Any]] = []
    for c in candidates:
        if c.score >= min_score:
            result.append({
                "id": c.profile_id,
                "label": c.label,
                "score": c.score,
                "matched_terms": list(c.matched_terms),
                "summary": compact_profile_summary(c.profile_id),
            })
    return result


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
    """兼容包装：从 parsed_intent 构建主题配置。"""
    profile_id = getattr(parsed_intent, "theme_profile", None)
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
    city_short = city_short_name(city)
    macro = _unique(profile.get("macro_search_terms", []), 10)
    micro = _unique(profile.get("micro_poi_keywords", []), 12)
    required = _unique(profile.get("required_terms", []), 12)

    queries: list[str] = []
    if macro:
        queries.append(f"{city_short} {' '.join(macro[:4])} 推荐")
    if len(macro) > 4:
        queries.append(f"{city_short} {' '.join(macro[4:8])} 推荐")
    if micro:
        queries.append(f"{city_short} 小众 高质量 {' '.join(micro[:8])}")
    elif required:
        queries.append(f"{city_short} 主题路线 {' '.join(required[:8])}")
    for key, values in (profile.get("subclusters", {}) or {}).items():
        vals = _unique(values, 8)
        if vals:
            queries.append(f"{city_short} {' '.join(vals)} 推荐")
        if len(queries) >= limit:
            break
    return _unique(queries, limit)


# ── 主题库审计 ────────────────────────────────────────
def audit_theme_profile_library() -> list[dict[str, Any]]:
    """审计主题库结构问题，返回问题列表。"""
    issues: list[dict[str, Any]] = []
    profiles = get_all_theme_profiles()

    # 1. exact_activity_term 跨主题冲突
    exact_map: dict[str, list[str]] = {}
    for pid, p in profiles.items():
        for term in p.get("exact_activity_terms", []) or []:
            t = str(term).strip()
            if t:
                exact_map.setdefault(t, []).append(pid)
    for term, pids in exact_map.items():
        if len(pids) > 1:
            issues.append({
                "type": "duplicate_exact_activity_term",
                "term": term,
                "profile_ids": pids,
                "detail": f"exact_activity_term '{term}' appears in {pids}",
            })

    # 2. 普通关键词跨主题（仅记录高频冲突，>3个主题）
    all_terms: dict[str, int] = {}
    for pid, p in profiles.items():
        seen: set[str] = set()
        for field in ["seed_keywords", "destination_anchor_terms", "macro_search_terms",
                       "micro_poi_keywords", "required_terms"]:
            for term in p.get(field, []) or []:
                t = str(term).strip()
                if t and t not in seen:
                    all_terms[t] = all_terms.get(t, 0) + 1
                    seen.add(t)
    for term, count in all_terms.items():
        if count > 3:
            issues.append({
                "type": "widely_shared_term",
                "term": term,
                "profile_count": count,
                "detail": f"term '{term}' appears in {count} profiles",
            })

    # 3. required/excluded 冲突
    for pid, p in profiles.items():
        required_set = set(str(t).strip() for t in p.get("required_terms", []) or [])
        excluded_set = set(str(t).strip() for t in p.get("excluded_terms", []) or [])
        overlap = required_set & excluded_set
        for t in overlap:
            if t:
                issues.append({
                    "type": "required_excluded_conflict",
                    "profile_id": pid,
                    "term": t,
                    "detail": f"'{t}' in both required_terms and excluded_terms of {pid}",
                })

    # 4. exact_activity_terms 长度<2 的中文词
    for pid, p in profiles.items():
        for term in p.get("exact_activity_terms", []) or []:
            t = str(term).strip()
            if len(t) < 2 and re.search(r'[一-鿿]', t):
                issues.append({
                    "type": "short_exact_term",
                    "profile_id": pid,
                    "term": t,
                    "detail": f"exact_activity_term '{t}' is too short",
                })

    # 5. exact_activity_terms 含禁止泛词
    for pid, p in profiles.items():
        for term in p.get("exact_activity_terms", []) or []:
            t = str(term).strip()
            if t in FORBIDDEN_EXACT_TERMS:
                issues.append({
                    "type": "forbidden_exact_term",
                    "profile_id": pid,
                    "term": t,
                    "detail": f"exact_activity_term '{t}' is a forbidden generic term",
                })

    # 6. 缺少 label
    for pid, p in profiles.items():
        if not p.get("label"):
            issues.append({
                "type": "missing_label",
                "profile_id": pid,
                "detail": f"profile {pid} missing label",
            })

    # 7. 字段类型问题
    for pid, p in profiles.items():
        for field in ["seed_keywords", "macro_search_terms", "destination_anchor_terms",
                       "micro_poi_keywords", "required_terms", "exact_activity_terms"]:
            v = p.get(field, None)
            if v is not None and not isinstance(v, list):
                issues.append({
                    "type": "invalid_field_type",
                    "profile_id": pid,
                    "field": field,
                    "detail": f"{field} should be list, got {type(v).__name__}",
                })

    return issues
