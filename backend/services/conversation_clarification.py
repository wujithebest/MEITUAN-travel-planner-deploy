"""Pre-planning clarification rules for underspecified travel requests.

These rules intentionally run before Step 1.  Prompt-only clarification is not
enough because Step 1 post-processing can add profile-derived search keywords
and accidentally continue into route generation.
"""

from __future__ import annotations

import re


_TRAILING_PARTICLES_RE = re.compile(r"(?:呢|吗|嘛|吧|呀|啊|啦)?$")
_GENERIC_OUTING_RE = re.compile(
    r"^(?:(?:这|本|下)?周末|今天|明天|后天)?"
    r"(?:我)?(?:想|打算|准备|要)?(?:去)?"
    r"(?:出去|出门)?(?:玩|玩玩|逛逛|走走|转转)$"
)


def _normalize(text: str) -> str:
    cleaned = re.sub(r"[\s，。,.!?！？；;、]", "", str(text or "").strip())
    return _TRAILING_PARTICLES_RE.sub("", cleaned)


def is_underspecified_outing_request(text: str) -> bool:
    """Return True only for a bare outing wish with no destination or theme."""
    return bool(_GENERIC_OUTING_RE.fullmatch(_normalize(text)))


def clarification_reply(text: str) -> str | None:
    """Return a destination-first follow-up for a bare outing request."""
    if not is_underspecified_outing_request(text):
        return None
    if "周末" in text:
        return "这个周末想去哪里玩？可以告诉我城市、区域，或者一个想去的地点。"
    return "想去哪里玩？可以告诉我城市、区域，或者一个想去的地点。"


def merge_pending_clarification(
    current_text: str,
    previous_user_messages: list[str] | None,
) -> str:
    """Carry the pending vague request into the user's next answer.

    The frontend sends previous user turns even before a route exists.  This
    turns a short answer such as ``北京`` into an actionable Step 1 request
    while retaining the original weekend context.
    """
    previous = list(previous_user_messages or [])
    if not previous or is_underspecified_outing_request(current_text):
        return current_text
    pending = previous[-1]
    if not is_underspecified_outing_request(pending):
        return current_text
    return f"{pending}；用户补充：{current_text}"
