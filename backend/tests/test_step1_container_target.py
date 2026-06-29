"""Regression tests for clause-local container-target intent parsing."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.step1_intent import _detect_poi_category_query, _parse_container_target


@pytest.mark.parametrize(
    ("text", "container", "target"),
    [
        ("商场里的电玩城", "商场", "电玩城"),
        ("想去购物中心里面找个游戏厅", "购物中心", "游戏厅"),
        ("园区中的咖啡馆", "园区", "咖啡馆"),
        ("明天去商场内部的电玩城看看", "商场", "电玩城"),
    ],
)
def test_parse_container_target_supports_bare_and_named_forms(text, container, target):
    assert _parse_container_target(text) == (container, target)


def test_container_target_does_not_cross_clause_boundary():
    assert _parse_container_target("先去公园，再找商场里的电玩城，然后吃饭") == (
        "商场",
        "电玩城",
    )


def test_container_target_uses_target_category_not_container_category():
    result = _detect_poi_category_query("商场里的电玩城")
    assert result is not None
    assert result["primary_query"] == "电玩城"
    assert result["category_id"] == "arcade"
    assert result["container_constraint"] == "商场"
    assert "080300" in result["allowed_typecode_prefixes"]


def test_unknown_target_still_preserves_container_constraint():
    result = _detect_poi_category_query("园区中的咖啡馆")
    assert result is not None
    assert result["primary_query"] == "咖啡馆"
    assert result["category_id"] is None
    assert result["container_constraint"] == "园区"


def test_unrelated_center_text_is_not_a_container_relation():
    assert _parse_container_target("购物中心今天有活动") is None
