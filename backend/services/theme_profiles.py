from __future__ import annotations

from typing import Any

from .theme_profile_matcher import (
    build_effective_theme_profile_from_library,
    get_all_theme_profiles,
    normalize_theme_profile_id,
)


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


# Runtime theme definitions have one source of truth. Concrete city POIs and
# legacy recall query templates must never be merged into this mapping.
OFFICIAL_THEME_PROFILES: dict[str, dict[str, Any]] = {
    profile_id: dict(profile)
    for profile_id, profile in get_all_theme_profiles().items()
}


def normalize_theme_profile(value: str | None, text: str = "") -> str | None:
    """Compatibility wrapper for ID/alias normalization only."""
    return normalize_theme_profile_id(value, text)


def build_effective_theme_profile(parsed_intent: Any) -> dict[str, Any]:
    """Build an execution profile without re-inferring a missing theme."""
    lib_profile = build_effective_theme_profile_from_library(parsed_intent)
    if lib_profile.get("active"):
        return lib_profile

    if not getattr(parsed_intent, "theme_profile", None):
        return {"active": False}

    custom = getattr(parsed_intent, "custom_theme_profile", {}) or {}
    confidence = float(
        getattr(parsed_intent, "theme_confidence", 0.0)
        or custom.get("confidence")
        or 0.0
    )
    if not custom or confidence < 0.6:
        return {"active": False}

    return {
        "id": "custom",
        "official": False,
        "active": True,
        "label": str(
            custom.get("theme_label")
            or getattr(parsed_intent, "theme_label", "")
            or "自定义主题"
        ),
        "search_terms": _unique(
            list(custom.get("micro_poi_keywords", []))
            + list(custom.get("search_terms", [])),
            8,
        ),
        "micro_keywords": _unique(list(custom.get("micro_poi_keywords", [])), 16),
        "required_terms": _unique(list(custom.get("micro_required_terms", [])), 16),
        "generic_penalty_terms": _unique(
            list(custom.get("generic_penalty_terms", [])),
            12,
        ),
        "excluded_terms": _unique(list(custom.get("micro_excluded_terms", [])), 16),
        "typecode_prefixes": [],
        "excluded_typecode_prefixes": [],
        "diversity_hint": _unique(list(custom.get("micro_diversity_hint", [])), 8),
    }
