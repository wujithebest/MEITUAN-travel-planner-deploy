"""v26: Tests for guest profile input normalization.

Verify that build_profile_from_guest handles bad input shapes
(label=[], lat=NaN, missing fields, etc.) without throwing
Pydantic ValidationError.
"""
from __future__ import annotations

import sys
import os

# Ensure backend is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_label_is_empty_list():
    """home_location.label = [] must not crash build_profile_from_guest."""
    from services.mock_profile import build_profile_from_guest

    guest = {
        "home_location": {"lat": 39.9, "lng": 116.4, "label": []},
    }
    profile = build_profile_from_guest(guest)
    hl = profile.home_location
    assert hl is not None
    assert isinstance(hl["label"], str), f"label is {type(hl['label'])}: {hl['label']!r}"
    assert len(hl["label"]) > 0
    assert isinstance(hl["lat"], (int, float))
    assert isinstance(hl["lng"], (int, float))


def test_label_is_number():
    """home_location.label = 123 (number) must fallback."""
    from services.mock_profile import build_profile_from_guest

    guest = {
        "home_location": {"lat": 39.9, "lng": 116.4, "label": 123},
    }
    profile = build_profile_from_guest(guest)
    hl = profile.home_location
    assert isinstance(hl["label"], str)
    assert len(hl["label"]) > 0
    assert hl["label"] != "123"


def test_label_is_list_of_strings():
    """home_location.label = ['name1', 'name2'] should pick first string."""
    from services.mock_profile import build_profile_from_guest

    guest = {
        "home_location": {"lat": 31.2, "lng": 121.5, "label": ["上海家", "备用名"]},
    }
    profile = build_profile_from_guest(guest)
    hl = profile.home_location
    assert isinstance(hl["label"], str)
    assert hl["label"] == "上海家"


def test_home_location_not_a_dict():
    """home_location = 'not_a_dict' must not crash."""
    from services.mock_profile import build_profile_from_guest

    guest = {"home_location": "not_a_dict"}
    profile = build_profile_from_guest(guest)
    hl = profile.home_location
    assert hl is not None
    assert isinstance(hl["lat"], (int, float))
    assert isinstance(hl["lng"], (int, float))
    assert isinstance(hl["label"], str)


def test_home_location_None():
    """home_location = None must not crash."""
    from services.mock_profile import build_profile_from_guest

    guest = {"home_location": None}
    profile = build_profile_from_guest(guest)
    hl = profile.home_location
    assert hl is not None
    assert isinstance(hl["label"], str)


def test_bad_lat_lng():
    """lat and lng as list/string/NaN must fallback."""
    from services.mock_profile import build_profile_from_guest

    guest = {
        "home_location": {
            "lat": [39.9],
            "lng": "not_a_number",
            "label": "测试",
        },
    }
    profile = build_profile_from_guest(guest)
    hl = profile.home_location
    assert isinstance(hl["lat"], (int, float))
    assert isinstance(hl["lng"], (int, float))
    assert abs(float(hl["lat"]) - 31.2809) < 0.001
    assert abs(float(hl["lng"]) - 121.5011) < 0.001
    assert hl["label"] == "测试"


def test_permanent_city_coord_bad_type():
    """permanent_city_coord as list or bad lat/lng must fallback to home_location."""
    from services.mock_profile import build_profile_from_guest

    guest = {
        "home_location": {"lat": 39.9, "lng": 116.4, "label": "北京家"},
        "permanent_city_coord": ["bad", "data"],
    }
    profile = build_profile_from_guest(guest)
    pcc = profile.permanent_city_coord
    assert pcc is not None
    assert isinstance(pcc["lat"], (int, float))
    assert isinstance(pcc["lng"], (int, float))
    assert abs(float(pcc["lat"]) - 39.9) < 0.001
    assert abs(float(pcc["lng"]) - 116.4) < 0.001


def test_permanent_city_coord_NaN():
    """permanent_city_coord with NaN lat/lng must fallback."""
    from services.mock_profile import build_profile_from_guest

    guest = {
        "home_location": {"lat": 31.2, "lng": 121.5, "label": "上海"},
        "permanent_city_coord": {"lat": float("nan"), "lng": float("inf")},
    }
    profile = build_profile_from_guest(guest)
    pcc = profile.permanent_city_coord
    assert abs(float(pcc["lat"]) - 31.2) < 0.001
    assert abs(float(pcc["lng"]) - 121.5) < 0.001


def test_full_guest_profile_integration():
    """Complete guest profile with mixed good/bad data must not crash."""
    from services.mock_profile import build_profile_from_guest

    guest = {
        "nickname": "游客测试",
        "gender": "女",
        "age": 25,
        "activity_pref_tag": ["文艺", "咖啡"],
        "food_pref_tag": ["川菜"],
        "home_location": {
            "lat": 39.9042,
            "lng": 116.4074,
            "label": "北京朝阳区",
            "city": "北京市",
            "district": "朝阳区",
            "source": "manual",
        },
        "permanent_city_coord": {"lat": 39.9042, "lng": 116.4074},
        "budget_per_capita": 150,
    }
    profile = build_profile_from_guest(guest)
    assert profile.nickname == "游客测试"
    assert profile.gender == "女"
    assert profile.age == 25
    assert profile.activity_pref_tag == ["文艺", "咖啡"]
    assert profile.food_pref_tag == ["川菜"]
    assert profile.budget_per_capita == 150.0
    hl = profile.home_location
    assert hl["label"] == "北京朝阳区"
    assert abs(float(hl["lat"]) - 39.9042) < 0.001
    assert abs(float(hl["lng"]) - 116.4074) < 0.001


def test_budget_bad_type():
    """budget_per_capita as list/string must fallback to 100."""
    from services.mock_profile import build_profile_from_guest

    guest = {
        "home_location": {"lat": 31.2, "lng": 121.5},
        "budget_per_capita": ["not", "a", "number"],
    }
    profile = build_profile_from_guest(guest)
    assert profile.budget_per_capita == 100.0


def test_activity_pref_tag_bad_type():
    """activity_pref_tag as string must be converted to list[str]."""
    from services.mock_profile import build_profile_from_guest

    guest = {
        "home_location": {"lat": 31.2, "lng": 121.5},
        "activity_pref_tag": "文艺",
    }
    profile = build_profile_from_guest(guest)
    assert isinstance(profile.activity_pref_tag, list)
    assert len(profile.activity_pref_tag) > 0
    assert all(isinstance(t, str) for t in profile.activity_pref_tag)


def test_empty_home_location_dict():
    """Empty home_location dict must not crash."""
    from services.mock_profile import build_profile_from_guest

    guest = {"home_location": {}}
    profile = build_profile_from_guest(guest)
    hl = profile.home_location
    assert isinstance(hl["label"], str)
    assert len(hl["label"]) > 0
    assert isinstance(hl["lat"], (int, float))
    assert isinstance(hl["lng"], (int, float))


def test_metadata_fields_not_leaking_bad_types():
    """city/cityname/district in home_location that are lists must not leak."""
    from services.mock_profile import build_profile_from_guest

    guest = {
        "home_location": {
            "lat": 39.9,
            "lng": 116.4,
            "label": "家",
            "city": ["北京市"],
            "cityname": {"name": "bad"},
            "district": 100,
        },
    }
    profile = build_profile_from_guest(guest)
    hl = profile.home_location
    assert "city" not in hl or isinstance(hl.get("city"), str)
    assert "cityname" not in hl or isinstance(hl.get("cityname"), str)
