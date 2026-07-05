from services.conversation_clarification import (
    clarification_reply,
    is_underspecified_outing_request,
    merge_pending_clarification,
)


def test_weekend_outing_asks_for_destination():
    text = "周末想出去玩"
    assert is_underspecified_outing_request(text)
    assert clarification_reply(text) == (
        "这个周末想去哪里玩？可以告诉我城市、区域，或者一个想去的地点。"
    )


def test_weekend_outing_with_particle_asks_for_destination():
    assert is_underspecified_outing_request("周末出去玩呢")
    assert clarification_reply("周末出去玩呢") is not None


def test_concrete_request_does_not_trigger_clarification():
    assert not is_underspecified_outing_request("周末想去北京玩")
    assert clarification_reply("周末想去北京玩") is None


def test_next_turn_retains_pending_weekend_context():
    assert merge_pending_clarification("北京", ["周末想出去玩"]) == (
        "周末想出去玩；用户补充：北京"
    )


def test_unrelated_history_is_not_merged():
    assert merge_pending_clarification("北京", ["你好"]) == "北京"
