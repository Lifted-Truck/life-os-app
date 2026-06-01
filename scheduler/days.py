"""Day-of-week vocabulary, sugar expansion, and eligibility helpers (R6).

Tasks and Type 4 thresholds may carry an optional ``placement.days`` (or
``days`` at the domain level) constraining which weekdays they can be
scheduled on. Sugar tokens ``weekday`` and ``weekend`` are expanded here at
parse time so the engine only ever sees explicit ``[mon..sun]`` lists.

The pure helpers in this module are imported by ``scheduler.tasks_parser``,
``scheduler.compile_queue``, ``scheduler.urgency``, and ``scheduler.schedule``.
"""
from __future__ import annotations

from datetime import date, timedelta

VALID_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Sugar tokens accepted at authoring time, expanded at parse time.
SUGAR = {
    "weekday": ("mon", "tue", "wed", "thu", "fri"),
    "weekend": ("sat", "sun"),
}

# date.weekday() returns 0=Mon..6=Sun
_INDEX_TO_TOKEN = {i: d for i, d in enumerate(VALID_DAYS)}


def today_token(today: date) -> str:
    """Three-letter weekday string for a date, in our canonical vocab."""
    return _INDEX_TO_TOKEN[today.weekday()]


def expand_days(values) -> list[str]:
    """Expand a list that may contain sugar tokens into canonical days.

    `[mon, weekend]` -> `['mon', 'sat', 'sun']`. Duplicates removed,
    insertion order preserved. Empty/None input returns `[]`. Unknown
    tokens raise ``ValueError`` so the parser can surface a lint entry.
    """
    if not values:
        return []
    out: list[str] = []
    for v in values:
        t = str(v).strip().lower()
        if t in SUGAR:
            out.extend(SUGAR[t])
        elif t in VALID_DAYS:
            out.append(t)
        else:
            raise ValueError(
                f"unknown day token '{v}' "
                f"(allowed: {', '.join(VALID_DAYS)} / weekday / weekend)"
            )
    seen: set[str] = set()
    deduped: list[str] = []
    for d in out:
        if d not in seen:
            seen.add(d)
            deduped.append(d)
    return deduped


def is_eligible_today(days, today: date) -> bool:
    """A task with no ``days`` is eligible any day; otherwise must match today."""
    if not days:
        return True
    return today_token(today) in days


def eligible_days_in_window(days, start: date, end: date) -> int:
    """Count weekdays in [start, end] inclusive that satisfy ``days``.

    With empty ``days`` returns the full calendar count (so callers can use
    this as a drop-in for ``(end - start).days + 1``).
    """
    if start > end:
        return 0
    if not days:
        return (end - start).days + 1
    n = 0
    d = start
    while d <= end:
        if today_token(d) in days:
            n += 1
        d = d + timedelta(days=1)
    return n
