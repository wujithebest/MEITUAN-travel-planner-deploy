"""Step2 recall precision tests — using fixed mock candidates, no live API."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.poi_relevance import score_poi_against_intent, recall_audit_log


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


def test_antique_market_accepts_collectibles():
    case = next(c for c in CASES if c["id"] == "antique_market")
    intent = _make_intent(case)
    accepted_names = case["expected"]["accepted"]
    rejected_names = case["expected"]["rejected"]

    for cand in case["candidates"]:
        evidence = score_poi_against_intent(
            poi=cand, parsed_intent=intent,
            matched_query=case["primary_query"],
        )
        log = recall_audit_log(case["primary_query"], case["poi_query_type"], cand, evidence)
        print(log)

        if cand["name"] in accepted_names:
            assert evidence.accepted, f"{cand['name']} should be accepted but was rejected: {evidence.rejection_reasons}"
        elif cand["name"] in rejected_names:
            assert not evidence.accepted, f"{cand['name']} should be rejected but was accepted"
    print("✅ antique_market: precision correct")


def test_art_route_rejects_zoo():
    case = next(c for c in CASES if c["id"] == "art_route")
    intent = _make_intent(case)

    for cand in case["candidates"]:
        evidence = score_poi_against_intent(
            poi=cand, parsed_intent=intent,
            matched_query=case["primary_query"],
        )
        if cand["name"] == "动物园":
            assert not evidence.accepted, "动物园 should be rejected from art route"
        if cand["name"] == "普通餐厅":
            assert not evidence.accepted or len(evidence.rejection_reasons) > 0, \
                "普通餐厅 should not pass in non-meal art route"
    print("✅ art_route: zoo/reject correct")


def test_script_kill_rejects_landmarks():
    case = next(c for c in CASES if c["id"] == "script_kill")
    intent = _make_intent(case)

    for cand in case["candidates"]:
        evidence = score_poi_against_intent(
            poi=cand, parsed_intent=intent,
            matched_query=case["primary_query"],
        )
        if cand["name"] in ("火车站广场", "故宫", "普通餐厅"):
            assert not evidence.accepted, f"{cand['name']} should be rejected"
    print("✅ script_kill: rejects landmarks/restaurants")


def test_flower_market_accepts_flower():
    case = next(c for c in CASES if c["id"] == "flower_market")
    intent = _make_intent(case)

    for cand in case["candidates"]:
        evidence = score_poi_against_intent(
            poi=cand, parsed_intent=intent,
            matched_query=case["primary_query"],
        )
        if cand["name"] == "普通餐厅":
            assert not evidence.accepted, "普通餐厅 should be rejected"
        if cand["name"] in ("花鸟鱼虫市场", "鲜花批发"):
            assert evidence.accepted, f"{cand['name']} should be accepted"
    print("✅ flower_market: passes flower shops, rejects restaurants")


def test_all_antique_market_top3_no_irrelevant():
    case = next(c for c in CASES if c["id"] == "antique_market")
    intent = _make_intent(case)
    scored = []
    for cand in case["candidates"]:
        evidence = score_poi_against_intent(
            poi=cand, parsed_intent=intent,
            matched_query=case["primary_query"],
        )
        scored.append((cand, evidence))

    scored.sort(key=lambda x: -x[1].score)
    top3 = [s[0]["name"] for s in scored[:3]]
    expected_irrelevant = case["expected"]["irrelevant_in_top3"]
    irrelevant = [n for n in top3 if n in case["expected"]["rejected"]]
    assert len(irrelevant) == expected_irrelevant, \
        f"Top3 should have {expected_irrelevant} irrelevant, got {irrelevant}"
    print(f"✅ antique_market Top3: {top3} — irrelevant in top3={len(irrelevant)}")
