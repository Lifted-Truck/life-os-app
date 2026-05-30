"""Pure, deterministic urgency functions (frozen for v1).

urgency = deadline-proximity contribution (Type 2) + cadence-debt contribution
(Type 4). No randomness, no clock beyond the `today` argument, no AI.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from .constants import (
    CADENCE_DAYS,
    CADENCE_OVERDUE_CYCLE_CAP,
    CADENCE_URGENCY_PER_CYCLE,
    DEADLINE_OVERDUE_PER_DAY,
    DEADLINE_URGENCY_AT_DUE,
    DEADLINE_URGENCY_CAP,
    SOFT_DEADLINE_FACTOR,
)


def deadline_urgency(deadline: Optional[date], deadline_type: Optional[str], today: date) -> float:
    """Urgency from deadline proximity. Closer / overdue => higher."""
    if deadline is None:
        return 0.0
    days = (deadline - today).days
    if days < 0:
        u = DEADLINE_URGENCY_AT_DUE + abs(days) * DEADLINE_OVERDUE_PER_DAY
    else:
        u = DEADLINE_URGENCY_AT_DUE / (1 + days)
    u = min(u, DEADLINE_URGENCY_CAP)
    if deadline_type == "soft":
        u *= SOFT_DEADLINE_FACTOR
    return u


def cadence_debt_urgency(cadence: Optional[str], last_completion: Optional[date], today: date) -> float:
    """Urgency that accrues the longer a recurring item goes past its cadence.

    A never-completed item is treated as exactly one cycle overdue (due now),
    not infinitely overdue, so a fresh system doesn't explode with urgency.
    """
    cycle = CADENCE_DAYS.get(cadence)
    if not cycle:                       # as-scheduled / unknown => no cadence-debt
        return 0.0
    if last_completion is None:
        days_since = cycle
    else:
        days_since = (today - last_completion).days
    ratio = max(0.0, days_since / cycle)
    ratio = min(ratio, CADENCE_OVERDUE_CYCLE_CAP)
    return ratio * CADENCE_URGENCY_PER_CYCLE
