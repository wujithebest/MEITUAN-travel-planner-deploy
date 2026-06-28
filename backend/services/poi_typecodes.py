"""Unified Gaode typecode handling — composite codes, prefix matching, category rules."""

from __future__ import annotations

import re
from typing import Any


# ── Split & match ──────────────────────────────────────
def split_typecodes(raw: Any) -> list[str]:
    """Parse a single or composite typecode string into individual codes.

    Accepts ``'061202'``, ``'061202|080500'``, ``['061202','080500']``.
    """
    if isinstance(raw, list):
        codes: list[str] = []
        for item in raw:
            codes.extend(split_typecodes(item))
        return codes
    text = str(raw or "").strip()
    if not text:
        return []
    return [c.strip() for c in re.split(r"[|,;]+", text) if c.strip()]


def matches_typecode(raw: Any, prefixes: list[str]) -> bool:
    """True if ANY individual code matches ANY prefix.

    Uses per-code ``startswith``, not ``typecode[:6]`` on the raw string.
    """
    codes = split_typecodes(raw)
    if not codes:
        return False
    for code in codes:
        for prefix in prefixes:
            if code.startswith(prefix):
                return True
    return False


# ── Category rules (data-driven, no city/POI names) ─────────────────────
# Each entry maps a category family to:
#   - allowed: list of typecode prefixes that represent the correct class
#   - semantic_terms: name/category text that must also be present (>0 means required)
#   - excluded: typecode prefixes that are always wrong for this family
#   - wide_fallback: broader prefix for initial wide recall (still needs semantic check)
#   - note: human-readable explanation

CATEGORY_RULES: dict[str, dict[str, Any]] = {
    "convenience_store": {
        "label": "便利店",
        "allowed": ["060200", "060201"],  # Gaode: 0602xx = 便利店/小卖部
        "wide_fallback": ["060000"],
        "semantic_terms": ["便利店", "便利", "超市", "小卖部", "士多", "杂货"],
        "excluded": ["050000", "110000"],
        # 060400 is primarily bookstore/stationery — only accept if name has convenience terms
        "conditional_allow": {
            "060400": ["便利店", "便利", "超市", "小卖部", "士多"],
        },
        "note": "060400 is bookstore/stationery; only accept if name contains convenience terms",
    },
    "antique_market": {
        "label": "古玩/收藏品市场",
        "allowed": ["061200", "190700"],
        "wide_fallback": ["060000"],
        "semantic_terms": ["古玩", "文玩", "旧货", "收藏品", "古董", "钱币", "邮票", "古玩城", "收藏品市场"],
        "excluded": ["050000", "110000", "080000"],
        "note": "typecode 0612 must be accompanied by name/category evidence",
    },
    "handcraft_intangible": {
        "label": "非遗手作/手工艺",
        "allowed": ["080500", "061202"],
        "wide_fallback": ["080000", "060000"],
        "semantic_terms": ["非遗", "手作", "手工", "工坊", "体验坊", "手工艺", "传统工艺", "DIY", "陶艺", "扎染", "木版", "刺绣"],
        "excluded": ["050000", "110000"],
        "note": "typecode alone insufficient; need name/category match",
    },
    "flower_market": {
        "label": "花艺/鲜花市场",
        "allowed": ["061100"],  # 花鸟鱼虫市场
        "wide_fallback": ["060000"],
        "semantic_terms": ["花店", "花市", "花艺", "鲜花", "花卉", "花鸟", "盆栽", "插花", "花坊"],
        "excluded": ["050000", "110000", "080000"],
        # Also accept flower-related shopping typecodes if name matches
        "conditional_allow": {
            "061000": ["花店", "花市", "花艺", "鲜花", "花卉", "花坊"],
        },
    },
    "wood_craft": {
        "label": "木材工作坊/木艺",
        "allowed": ["080500", "061200"],
        "wide_fallback": ["080000", "060000"],
        "semantic_terms": ["木工坊", "木作", "木艺", "木工体验", "木工", "木器", "木制品", "木艺工作室", "木工工作室"],
        "excluded": ["050000", "110000"],
        "note": "strict name check required; do not accept general craft shops without wood terms",
    },
    "bookstore": {
        "label": "书店/文具",
        "allowed": ["061205"],  # Gaode: 061205 = 书店 (actual bookstore code, NOT 060400)
        "wide_fallback": ["060000"],
        "semantic_terms": ["书店", "书局", "书城", "城市书房", "独立书店", "概念书店", "图书馆"],
        "excluded": ["050000", "080500"],
        "note": "061205 is the correct Gaode code for bookstores; 060400 is general stationery/cultural supplies",
    },
    "restaurant": {
        "label": "餐饮",
        "allowed": ["050000"],
        "wide_fallback": ["050000"],
        "semantic_terms": ["餐厅", "饭馆", "饭店", "美食", "小吃", "火锅", "川菜", "粤菜", "面馆"],
        "excluded": [],
        "note": "only used when explicit_meal_intent=True",
    },
}


def category_for_query(query: str) -> str | None:
    """Given a primary_query like '古玩市场', return the best-matching category rule id."""
    q = query.lower()
    best: tuple[int, str] | None = None
    for cat_id, rule in CATEGORY_RULES.items():
        if cat_id == "restaurant":
            continue
        for term in rule.get("semantic_terms", []):
            if term.lower() in q:
                score = len(term)
                if best is None or score > best[0]:
                    best = (score, cat_id)
                # Don't break — check all terms for longest match
    return best[1] if best else None


def validate_poi_category(
    poi: dict[str, Any],
    cat_id: str,
    require_two_evidence: bool = False,
) -> tuple[bool, list[str]]:
    """Check if a POI matches a category rule. Returns (pass, reasons).

    Args:
        poi: POI dict with name, typecode, category fields.
        cat_id: Category rule ID to validate against.
        require_two_evidence: If True, need at least 2 of {name, category, typecode} evidence.
    """
    rule = CATEGORY_RULES.get(cat_id)
    if not rule:
        return True, []

    reasons: list[str] = []
    name = str(poi.get("name", "") or "").lower()
    category = str(poi.get("category", "") or "").lower()
    combined = f"{name} {category}"

    # Check excluded typecodes
    raw_tc = poi.get("typecode", "")
    if matches_typecode(raw_tc, rule.get("excluded", [])):
        reasons.append(f"excluded_typecode={raw_tc}")
        return False, reasons

    # Check semantic terms in name and category
    found_semantic: list[str] = []
    for term in rule.get("semantic_terms", []):
        if term.lower() in combined:
            found_semantic.append(term)
            break  # One semantic hit is enough for the semantic check

    # Check allowed typecodes (strict allowed list)
    tc_ok = matches_typecode(raw_tc, rule.get("allowed", []))

    # Check conditional allows (e.g., 060400 only if name has "便利店")
    tc_conditional = False
    for prefix, terms in rule.get("conditional_allow", {}).items():
        if matches_typecode(raw_tc, [prefix]):
            for term in terms:
                if term.lower() in combined:
                    tc_conditional = True
                    break
            if tc_conditional:
                break

    tc_match = tc_ok or tc_conditional
    name_match = bool(found_semantic)

    # Evidence counting
    evidence_count = sum([
        1 if tc_match else 0,
        1 if name_match else 0,
        1 if category and any(t.lower() in category for t in rule.get("semantic_terms", [])) else 0,
    ])

    if require_two_evidence and evidence_count < 2:
        reasons.append(
            f"insufficient_evidence({evidence_count}/2): "
            f"tc={tc_match} name={name_match or found_semantic} cat={category[:30]}"
        )
        return False, reasons

    if not tc_match and not name_match:
        reasons.append(f"no_allowed_typecode({raw_tc})_and_no_semantic_match")
        return False, reasons

    return True, []


def get_allowed_typecode_prefixes(cat_id: str) -> list[str]:
    """Return the allowed typecode prefixes for a given category, including conditionals."""
    rule = CATEGORY_RULES.get(cat_id)
    if not rule:
        return []
    allowed = list(rule.get("allowed", []))
    for cond in rule.get("conditional_allow", {}).keys():
        allowed.append(cond)
    return allowed


def get_semantic_terms(cat_id: str) -> list[str]:
    """Return the semantic terms for a given category."""
    rule = CATEGORY_RULES.get(cat_id)
    if not rule:
        return []
    return list(rule.get("semantic_terms", []))


def get_excluded_typecode_prefixes(cat_id: str) -> list[str]:
    """Return the excluded typecode prefixes for a given category."""
    rule = CATEGORY_RULES.get(cat_id)
    if not rule:
        return []
    return list(rule.get("excluded", []))
