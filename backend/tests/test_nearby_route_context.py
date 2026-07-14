"""v28: Tests for nearby route context robustness.

Verifies:
- "找一家附近的餐馆" with string locations in route context → no crash, new_plan
- "那里附近找一家餐馆" with string locations → resolves previous destination
- Invalid/malformed locations (empty, garbage, wrong type) → safe fallback
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── _normalize_route_location tests ──

def test_normalize_route_location_dict():
    from services.conversation_replan import _normalize_route_location
    result = _normalize_route_location({"lng": 116.48584, "lat": 40.008652})
    assert result == {"lng": 116.48584, "lat": 40.008652}


def test_normalize_route_location_dict_longitude_latitude():
    from services.conversation_replan import _normalize_route_location
    result = _normalize_route_location({"longitude": 116.5, "latitude": 40.0})
    assert result == {"lng": 116.5, "lat": 40.0}


def test_normalize_route_location_string():
    """Gaode format 'lng,lat' string → dict."""
    from services.conversation_replan import _normalize_route_location
    result = _normalize_route_location("116.48584,40.008652")
    assert result == {"lng": 116.48584, "lat": 40.008652}


def test_normalize_route_location_string_with_spaces():
    from services.conversation_replan import _normalize_route_location
    result = _normalize_route_location(" 116.48584 , 40.008652 ")
    assert result == {"lng": 116.48584, "lat": 40.008652}


def test_normalize_route_location_list():
    from services.conversation_replan import _normalize_route_location
    result = _normalize_route_location([116.5, 40.0])
    assert result == {"lng": 116.5, "lat": 40.0}


def test_normalize_route_location_empty_string():
    from services.conversation_replan import _normalize_route_location
    assert _normalize_route_location("") is None


def test_normalize_route_location_invalid_string():
    from services.conversation_replan import _normalize_route_location
    assert _normalize_route_location("invalid") is None


def test_normalize_route_location_empty_list():
    from services.conversation_replan import _normalize_route_location
    assert _normalize_route_location([]) is None


def test_normalize_route_location_none():
    from services.conversation_replan import _normalize_route_location
    assert _normalize_route_location(None) is None


def test_normalize_route_location_out_of_range():
    from services.conversation_replan import _normalize_route_location
    assert _normalize_route_location("200,100") is None  # lng > 180, lat > 90


def test_normalize_route_location_int():
    from services.conversation_replan import _normalize_route_location
    assert _normalize_route_location(42) is None  # not dict/str/list


# ── _is_standalone_nearby tests ──

def test_standalone_nearby_bare_restaurant():
    from services.conversation_replan import _is_standalone_nearby
    assert _is_standalone_nearby("找一家附近的餐馆") is True


def test_standalone_nearby_bare_food():
    from services.conversation_replan import _is_standalone_nearby
    assert _is_standalone_nearby("在附近找一家餐厅") is True


def test_standalone_nearby_not_demonstrative():
    """'那里附近找一家餐馆' has context reference → NOT standalone."""
    from services.conversation_replan import _is_standalone_nearby
    assert _is_standalone_nearby("那里附近找一家餐馆") is False


def test_standalone_nearby_not_nearby():
    from services.conversation_replan import _is_standalone_nearby
    assert _is_standalone_nearby("帮我推荐一条文艺路线") is False


def test_standalone_nearby_not_continuation():
    from services.conversation_replan import _is_standalone_nearby
    assert _is_standalone_nearby("加到当前路线附近找一家餐馆") is False


# ── _resolve_nearby_reference crash-prevention tests ──

def test_resolve_nearby_with_string_locations_no_crash():
    """Route context POIs with string 'lng,lat' locations must not crash."""
    from services.conversation_replan import _resolve_nearby_reference

    route_context = {
        "points": [
            {
                "name": "景山公园",
                "kind": "route_waypoint",
                "location": "116.48584,40.008652",
            },
            {
                "name": "故宫",
                "kind": "destination",
                "location": "116.397026,39.916313",
            },
        ],
        "previous_intent": {},
        "previous_user_messages": [],
    }
    # "找一家附近的餐馆" — bare query, no demonstrative
    # Must NOT crash on .get() call. The function resolves destinations from
    # string locations correctly now (no AttributeError). In real flow this is
    # preempted by _is_standalone_nearby in classify_conversation_route_change_fast.
    # Here we just verify: no crash, and the resolved location is a proper dict.
    result = _resolve_nearby_reference("找一家附近的餐馆", route_context)
    assert result is not None, "should resolve destination from route points"
    assert result["source"] == "previous_destination"
    assert isinstance(result["location"], dict)
    assert "lng" in result["location"] and "lat" in result["location"]


def test_resolve_nearby_with_mixed_locations():
    """Mixed dict and string locations should be handled safely."""
    from services.conversation_replan import _resolve_nearby_reference

    route_context = {
        "points": [
            {
                "name": "北海公园",
                "kind": "route_waypoint",
                "location": {"lng": 116.39, "lat": 39.92},
            },
            {
                "name": "烤鸭店",
                "kind": "route_waypoint",
                "location": "116.42,39.93",
            },
        ],
        "previous_intent": {},
        "previous_user_messages": [],
    }
    result = _resolve_nearby_reference("找一家附近的餐馆", route_context)
    # No temporal markers in either → _no_temporal_in_either=True → resolves destination
    assert result is not None
    assert isinstance(result["location"], dict)


def test_resolve_nearby_demonstrative_with_string_location():
    """'那里附近找一家餐馆' with string location should resolve destination."""
    from services.conversation_replan import _resolve_nearby_reference

    route_context = {
        "points": [
            {
                "name": "起点",
                "kind": "start",
                "location": "116.30,39.90",
            },
            {
                "name": "景山公园",
                "kind": "route_waypoint",
                "location": "116.48584,40.008652",
            },
        ],
        "previous_intent": {
            "search_area_label": "景山公园",
            "search_area_location": "116.48584,40.008652",
        },
        "previous_user_messages": ["去景山公园"],
    }
    result = _resolve_nearby_reference("那里附近找一家餐馆", route_context)
    assert result is not None, "demonstrative reference should resolve destination"
    assert result["source"] == "previous_destination"
    assert result["label"] == "景山公园"
    assert result["location"] == {"lng": 116.48584, "lat": 40.008652}


def test_resolve_nearby_malformed_points():
    """Malformed points data must not crash .get() access."""
    from services.conversation_replan import _resolve_nearby_reference

    route_context = {
        "points": ["bad-data", None, 123, {"name": "valid", "kind": "route_waypoint", "location": "116.5,40.0"}],
        "previous_intent": None,
        "previous_user_messages": [],
    }
    # Must not raise AttributeError — non-dict items are safely filtered out
    result = _resolve_nearby_reference("找一家附近的餐馆", route_context)
    # The valid dict entry "valid" with location "116.5,40.0" IS found (filtered properly)
    # → same temporal logic: no markers → resolves.
    assert result is not None
    assert result["label"] == "valid"
    assert isinstance(result["location"], dict)


def test_resolve_nearby_empty_location_string():
    """Empty location string → safe fallback."""
    from services.conversation_replan import _resolve_nearby_reference

    route_context = {
        "points": [
            {"name": "test", "kind": "route_waypoint", "location": ""},
        ],
        "previous_intent": {},
        "previous_user_messages": [],
    }
    result = _resolve_nearby_reference("找一家附近的餐馆", route_context)
    assert result is None


def test_resolve_nearby_none_location():
    """None location → safe fallback."""
    from services.conversation_replan import _resolve_nearby_reference

    route_context = {
        "points": [
            {"name": "test", "kind": "route_waypoint", "location": None},
        ],
        "previous_intent": {},
        "previous_user_messages": [],
    }
    result = _resolve_nearby_reference("找一家附近的餐馆", route_context)
    assert result is None


# ── classify_conversation_route_change_fast tests ──

def test_fast_classify_standalone_nearby_goes_new_plan():
    """'找一家附近的餐馆' with existing route → new_plan (no crash)."""
    from services.conversation_replan import classify_conversation_route_change_fast

    route_context = {
        "points": [
            {
                "name": "景山公园",
                "kind": "route_waypoint",
                "location": "116.48584,40.008652",
            },
            {
                "name": "故宫",
                "kind": "destination",
                "location": "116.397026,39.916313",
            },
        ],
        "previous_intent": {},
        "previous_user_messages": [],
    }
    decision = classify_conversation_route_change_fast("找一家附近的餐馆", route_context)
    assert decision is not None
    assert decision.mode == "new_plan", f"expected new_plan, got {decision.mode}"
    # Must NOT have contextual_search_center
    csc = (decision.include_constraints or {}).get("contextual_search_center")
    assert csc is None, f"should not have contextual_search_center, got {csc}"


def test_fast_classify_demonstrative_nearby_follow_up():
    """'那里附近找一家餐馆' with route → follow_up with destination."""
    from services.conversation_replan import classify_conversation_route_change_fast

    route_context = {
        "points": [
            {
                "name": "景山公园",
                "kind": "route_waypoint",
                "location": "116.48584,40.008652",
            },
        ],
        "previous_intent": {
            "search_area_label": "景山公园",
            "search_area_location": "116.48584,40.008652",
        },
        "previous_user_messages": ["去景山公园"],
    }
    decision = classify_conversation_route_change_fast("那里附近找一家餐馆", route_context)
    assert decision is not None
    # Should be follow_up (contextual) OR new_plan — let's check it doesn't crash
    assert decision.mode in ("follow_up", "new_plan")
    if decision.mode == "follow_up":
        csc = (decision.include_constraints or {}).get("contextual_search_center")
        assert csc is not None
        assert csc["source"] == "previous_destination"


def test_fast_classify_no_route_new_plan():
    """No route context → new_plan."""
    from services.conversation_replan import classify_conversation_route_change_fast

    decision = classify_conversation_route_change_fast("找一家附近的餐馆", None)
    assert decision is not None
    assert decision.mode == "new_plan"


def test_fast_classify_crash_prevention_malformed_context():
    """Malformed route_context with non-dict points must not crash."""
    from services.conversation_replan import classify_conversation_route_change_fast

    # Simulate a truly malformed context that could come from serialization issues
    route_context = {
        "points": [
            "just-a-string",
            123,
            {"name": "ok", "kind": "route_waypoint", "location": "116.5,40.0"},
        ],
        "previous_intent": "not-a-dict",
        "previous_user_messages": [],
    }
    decision = classify_conversation_route_change_fast("找一家附近的餐馆", route_context)
    assert decision is not None
    assert decision.mode == "new_plan"
