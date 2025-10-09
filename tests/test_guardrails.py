from datetime import date
from social_agent_ai.services.guardrails import is_allowed_event


def test_minor_blocked_adult():
    assert not is_allowed_event(
        user_birthday=date(2010, 1, 1), event_tags={"kink"})


def test_adult_allowed():
    assert is_allowed_event(user_birthday=date(
        1990, 1, 1), event_tags={"kink"})
