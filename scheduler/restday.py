"""Screen-free / rest-day policy — a deterministic protected-day primitive.

Policy lives in `thresholds.yaml` `config` (user-tunable DATA; the mechanism is
here):

    config:
      screen-free-days:  [sun]                                  # weekday tokens / sugar
      screen-free-slots: [deep-work, admin, practice-creative]  # optional; screen-bound default
      screen-free-mode:  screen-free                            # 'screen-free' (default) | 'full'

On a screen-free day the listed slots are CLOSED. A task whose EVERY slot is
closed is surfaced as blocked (`screen-free (<day>)`); a task with an open slot
(e.g. `exercise`) or NO slot (anchored appointments, inbox items) is unaffected —
an appointment still stands on a screen-free day. `full` mode closes every slot
(a complete day off).

No AI: a weekly deterministic constraint, computed at compile time and refreshed
by the daily recompile exactly like off-day (`days:`) and cadence. Reuses the
day vocabulary in `days.py` and the `SLOT_VOCAB` in `constants.py`.
"""
from __future__ import annotations

from datetime import date

from .constants import SLOT_VOCAB
from .days import expand_days, today_token


def closed_slots_today(config: dict | None, today: date) -> set:
    """Slots closed today by the screen-free-day policy (empty set = none).

    Tolerant of a missing/partial/malformed `config`: any problem yields no
    closure rather than raising, so a bad edit degrades to "normal day".
    """
    cfg = config or {}
    raw_days = cfg.get("screen-free-days") or []
    if not raw_days:
        return set()
    try:
        days = set(expand_days(raw_days))
    except (ValueError, TypeError):
        return set()
    if today_token(today) not in days:
        return set()
    if str(cfg.get("screen-free-mode", "screen-free")).strip().lower() == "full":
        return set(SLOT_VOCAB)
    slots = cfg.get("screen-free-slots") or ("deep-work", "admin", "practice-creative")
    return {s for s in slots if s in SLOT_VOCAB}


def is_screen_free_blocked(slots, closed: set) -> bool:
    """True iff every one of the task's slots is closed today.

    Empty `slots` (anchored Type-2 events, inbox items) are NEVER blocked.
    """
    if not closed or not slots:
        return False
    return all(s in closed for s in slots)
