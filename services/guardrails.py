from __future__ import annotations

from datetime import date

ADULT_TAGS = {"kink", "bdsm", "fetish", "adult"}


def is_allowed_event(
    *, user_birthday: date | None, event_tags: set[str]
) -> bool:
    if user_birthday is None:
        return True  # unknown age → do not filter (can change policy)
    # simple age calc
    today = date.today()
    age = today.year - user_birthday.year - (
        (today.month, today.day) < (user_birthday.month, user_birthday.day)
    )
    if age < 18 and (ADULT_TAGS & event_tags):
        return False
    return True
