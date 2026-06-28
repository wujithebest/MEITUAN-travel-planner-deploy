"""Step2 recall precision tests — using fixed mock candidates, no live API, no real cities."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.poi_relevance import score_poi_against_intent, recall_audit_log
from services.poi_typecodes import matches_typecode, split_typecodes


def _load_cases():
    fixture = Path(__file__).with_name("fixtures") / "step2_recall_precision_cases.json"
    with open(fixture, "r", encoding="utf-8") as f:
        return json.load(f)["cases"]


def _make_intent(case):
    intent = MagicMock()
    intent.primary_query = case["primary_query"]
    intent.poi_query_type = case["poi_query_type"]
    intent.primary_required_terms = case.get("primary_required_terms", [])
    intent.primary_excluded_terms = case.get("primary_excluded_terms", [])
    intent.allowed_typecode_prefixes = case.get("allowed_typecode_prefixes", [])
    intent.excluded_typecode_prefixes = case.get("excluded_typecode_prefixes", [])
    intent.explicit_meal_intent = case.get("explicit_meal_intent", False)
    return intent


CASES = _load_cases()


def _run_case(case):
    """Run all candidates through score_poi_against_intent and return results."""
    intent = _make_intent(case)
    results = []
    for cand in case["candidates"]:
        evidence = score_poi_against_intent(
            poi=cand, parsed_intent=intent,
            matched_query=case["primary_query"],
        )
        log = recall_audit_log(case["primary_query"], case["poi_query_type"], cand, evidence)
        print(log)
        results.append((cand, evidence))
    return results, case


# ── Antique market tests ──
def test_antique_market_accepts_collectibles():
    case = next(c for c in CASES if c["id"] == "antique_market")
    results, case = _run_case(case)
    accepted_names = set(case["expected"]["accepted"])
    rejected_names = set(case["expected"]["rejected"])

    for cand, evidence in results:
        if cand["name"] in accepted_names:
            assert evidence.accepted, f"{cand['name']} should be accepted but was rejected: {evidence.rejection_reasons}"
        elif cand["name"] in rejected_names:
            assert not evidence.accepted, f"{cand['name']} should be rejected but was accepted"
    print("✅ antique_market: precision correct")


def test_antique_market_no_irrelevant_top3():
    """古玩市场不得返回故宫、普通景点或餐厅 — 验证接受项排在最前"""
    case = next(c for c in CASES if c["id"] == "antique_market")
    results, case = _run_case(case)
    results.sort(key=lambda x: -x[1].score)
    accepted_names = set(case["expected"]["accepted"])
    rejected_names = set(case["expected"]["rejected"])
    # All accepted items must be ranked above all rejected items
    for accepted_name in accepted_names:
        acc_score = next(s for n, s in zip([r[0]["name"] for r in results], [r[1].score for r in results]) if n == accepted_name)
        for rejected_name in rejected_names:
            rej_score = next(s for n, s in zip([r[0]["name"] for r in results], [r[1].score for r in results]) if n == rejected_name)
            assert acc_score > rej_score, f"Accepted {accepted_name} (score={acc_score}) must rank above rejected {rejected_name} (score={rej_score})"
    top3_names = [r[0]["name"] for r in results[:3]]
    print(f"✅ antique_market Top3: {top3_names} — accepted ranked above rejected")


def test_antique_market_no_restaurant_takeover():
    """古玩市场无餐饮意图时，餐厅应全部被拒绝"""
    case = next(c for c in CASES if c["id"] == "antique_market_no_restaurant_takeover")
    results, case = _run_case(case)
    for cand, evidence in results:
        assert not evidence.accepted, f"Restaurant {cand['name']} should be rejected in non-meal antique query"
    print("✅ antique_market_no_restaurant_takeover: all restaurants rejected")


# ── Handcraft intangible tests ──
def test_handcraft_intangible_accepts_craft_workshops():
    case = next(c for c in CASES if c["id"] == "handcraft_intangible")
    results, case = _run_case(case)
    accepted_names = set(case["expected"]["accepted"])
    rejected_names = set(case["expected"]["rejected"])

    for cand, evidence in results:
        if cand["name"] in accepted_names:
            assert evidence.accepted, f"{cand['name']} should be accepted: {evidence.rejection_reasons}"
        elif cand["name"] in rejected_names:
            assert not evidence.accepted, f"{cand['name']} should be rejected"
    print("✅ handcraft_intangible: correct")


def test_handcraft_no_unrelated_museum():
    """非遗手作不得返回无关博物馆"""
    case = next(c for c in CASES if c["id"] == "handcraft_intangible")
    results, case = _run_case(case)
    for cand, evidence in results:
        if cand["name"] == "城市博物馆":
            assert not evidence.accepted, "Unrelated museum should not be accepted for handcraft query"
    print("✅ handcraft_intangible: museum rejected")


# ── Flower market tests ──
def test_flower_market_accepts_flower_shops():
    case = next(c for c in CASES if c["id"] == "flower_market")
    results, case = _run_case(case)
    accepted_names = set(case["expected"]["accepted"])
    rejected_names = set(case["expected"]["rejected"])

    for cand, evidence in results:
        if cand["name"] in accepted_names:
            assert evidence.accepted, f"{cand['name']} should be accepted: {evidence.rejection_reasons}"
        elif cand["name"] in rejected_names:
            assert not evidence.accepted, f"{cand['name']} should be rejected"
    print("✅ flower_market: correct")


# ── Wood craft tests ──
def test_wood_craft_accepts_wood_workshops():
    """木材工作坊只能返回木工相关地点"""
    case = next(c for c in CASES if c["id"] == "wood_craft")
    results, case = _run_case(case)
    accepted_names = set(case["expected"]["accepted"])
    rejected_names = set(case["expected"]["rejected"])

    for cand, evidence in results:
        if cand["name"] in accepted_names:
            assert evidence.accepted, f"{cand['name']} should be accepted: {evidence.rejection_reasons}"
        elif cand["name"] in rejected_names:
            assert not evidence.accepted, f"{cand['name']} should be rejected"
    print("✅ wood_craft: correct")


# ── Convenience store tests ──
def test_convenience_store_accepts_0602xx():
    """附近便利店优先返回 060200/060201 或名称明确为便利店的候选"""
    case = next(c for c in CASES if c["id"] == "convenience_store")
    results, case = _run_case(case)
    accepted_names = set(case["expected"]["accepted"])
    rejected_names = set(case["expected"]["rejected"])

    for cand, evidence in results:
        if cand["name"] in accepted_names:
            assert evidence.accepted, f"{cand['name']} should be accepted: {evidence.rejection_reasons}"
        elif cand["name"] in rejected_names:
            assert not evidence.accepted, f"{cand['name']} should be rejected"
    print("✅ convenience_store: correct")


def test_convenience_store_rejects_bookstore():
    """便利店查询应拒绝 060400 书店"""
    case = next(c for c in CASES if c["id"] == "convenience_store")
    results, case = _run_case(case)
    for cand, evidence in results:
        if cand["name"] == "新华书店":
            assert not evidence.accepted, "060400 bookstore should not be accepted as convenience store"
    print("✅ convenience_store: rejects 060400 bookstore")


# ── Composite typecode test ──
def test_composite_typecode_match():
    """061202|080500 能正确匹配"""
    assert matches_typecode("061202|080500", ["0612"]), "061202|080500 should match 0612 prefix"
    assert matches_typecode("061202|080500", ["0805"]), "061202|080500 should also match 0805 prefix"
    assert not matches_typecode("061202|080500", ["05"]), "061202|080500 should NOT match 05 prefix"
    print("✅ composite_typecode_match: matches_typecode works for compound codes")


def test_composite_typecode_score():
    """复合编码候选应通过 scoring"""
    case = next(c for c in CASES if c["id"] == "composite_typecode_match")
    results, case = _run_case(case)
    for cand, evidence in results:
        assert evidence.accepted, f"Composite typecode {cand['typecode']} should be accepted: {evidence.rejection_reasons}"
    print("✅ composite_typecode_match: both accepted via scoring")


# ── Split typecodes unit test ──
def test_split_typecodes():
    assert split_typecodes("061202|080500") == ["061202", "080500"]
    assert split_typecodes("061202") == ["061202"]
    assert split_typecodes("061202,080500;061100") == ["061202", "080500", "061100"]
    assert split_typecodes(None) == []
    assert split_typecodes("") == []
    assert split_typecodes(["061202", "080500"]) == ["061202", "080500"]
    print("✅ split_typecodes: all cases pass")


# ── No meal takeover test ──
def test_no_meal_intent_rejects_restaurants():
    """无明确用餐需求时，所有 05xxxx 餐厅应被拒绝"""
    # Check across all non-meal cases
    for case in CASES:
        if case.get("explicit_meal_intent", False):
            continue
        if case["poi_query_type"] != "poi_category":
            continue
        results, _ = _run_case(case)
        for cand, evidence in results:
            tc = cand.get("typecode", "")
            if matches_typecode(tc, ["05"]):
                assert not evidence.accepted, \
                    f"Restaurant {cand['name']} (tc={tc}) should be rejected in non-meal query '{case['primary_query']}'"
    print("✅ no_meal_intent: all 05xxxx rejected across non-meal cases")
