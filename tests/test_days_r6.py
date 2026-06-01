"""Tests for R6 — day-of-week conditional placement.

Covers the pure ``scheduler/days`` helpers, the parser, compile_queue's
domain-level inheritance and as-scheduled+days nudge, urgency's
eligible-day cadence accrual, and schedule()'s off-day filter.
"""
from datetime import date, timedelta

import pytest

from scheduler.compile_queue import _normalize_thresholds, compile_queue
from scheduler.days import (
    eligible_days_in_window,
    expand_days,
    is_eligible_today,
    today_token,
)
from scheduler.models import Placement, Task
from scheduler.schedule import schedule
from scheduler.urgency import cadence_debt_urgency


SAT = date(2026, 5, 30)   # Saturday
SUN = date(2026, 5, 31)   # Sunday
MON = date(2026, 6, 1)    # Monday


# --- pure helpers -----------------------------------------------------------

def test_expand_explicit_days_passthrough():
    assert expand_days(["mon", "fri"]) == ["mon", "fri"]


def test_expand_sugar_weekday_weekend():
    assert expand_days(["weekday"]) == ["mon", "tue", "wed", "thu", "fri"]
    assert expand_days(["weekend"]) == ["sat", "sun"]


def test_expand_mixes_and_dedupes_in_order():
    assert expand_days(["weekend", "sat", "fri"]) == ["sat", "sun", "fri"]


def test_expand_empty_returns_empty():
    assert expand_days([]) == []
    assert expand_days(None) == []


def test_expand_unknown_raises():
    with pytest.raises(ValueError):
        expand_days(["funday"])


def test_today_token_maps_weekday():
    assert today_token(SAT) == "sat"
    assert today_token(MON) == "mon"


def test_is_eligible_today_empty_means_any_day():
    assert is_eligible_today([], SAT) is True
    assert is_eligible_today([], MON) is True


def test_is_eligible_today_constrained():
    assert is_eligible_today(["sat", "sun"], SAT) is True
    assert is_eligible_today(["sat", "sun"], MON) is False


def test_eligible_days_in_window_counts_only_matches():
    # Sat 5/30 .. next Sun 6/7 inclusive = 9 days; 2 Sat (5/30, 6/6) + 2 Sun (5/31, 6/7) = 4
    n = eligible_days_in_window(["sat", "sun"], SAT, date(2026, 6, 7))
    assert n == 4


def test_eligible_days_window_empty_is_calendar_count():
    n = eligible_days_in_window([], SAT, date(2026, 6, 7))
    assert n == 9


# --- urgency: cadence-debt skips off-days for daily --------------------------

def test_daily_with_days_accrues_only_on_eligible_days():
    # Done Sat. Today next Sat (7 cal days later). Eligible days since (Sun, Sat) = 2.
    # daily cycle = 1, so ratio = 2 -> debt = 100.
    u = cadence_debt_urgency("daily", SAT, date(2026, 6, 6), days=["sat", "sun"])
    assert u == pytest.approx(100.0)


def test_daily_with_days_freezes_meter_on_off_days():
    """On an off-day the meter doesn't TICK — but already-accrued debt stays.

    Done Sat. Today Mon. Eligible days in (Sun..Mon) = {Sun} = 1. So the
    meter ticked once on Sun and hasn't ticked again. Debt = 1 cycle = 50.
    """
    u = cadence_debt_urgency("daily", SAT, MON, days=["sat", "sun"])
    assert u == pytest.approx(50.0)


def test_daily_with_days_debt_unchanged_between_consecutive_off_days():
    """Two consecutive off-days = same debt value (meter frozen)."""
    mon = cadence_debt_urgency("daily", SAT, MON, days=["sat", "sun"])
    tue = cadence_debt_urgency("daily", SAT, MON + timedelta(days=1), days=["sat", "sun"])
    assert mon == tue


def test_daily_without_days_unchanged():
    """Regression: existing daily-cadence tasks see no change."""
    u_before = cadence_debt_urgency("daily", SAT, MON, days=None)
    u_after = cadence_debt_urgency("daily", SAT, MON, days=[])
    assert u_before == u_after
    # 2 cal days since, daily cycle = 1, debt = 2 * 50 = 100.
    assert u_before == pytest.approx(100.0)


def test_weekly_with_days_uses_calendar_cycle():
    """Cowork said weekly+days only changes completion validity, not accrual."""
    u = cadence_debt_urgency("weekly", SAT, date(2026, 6, 6), days=["sat", "sun"])
    # 7 cal days since / 7 = 1 cycle = 50 urgency.
    assert u == pytest.approx(50.0)


# --- schedule(): off-day filter --------------------------------------------

def _task(domain="career", days=None, urgency=100.0):
    return Task(
        id=f"{domain}-001",
        title=f"{domain} task",
        type=3,
        source="tasks",
        domain=domain,
        importance="normal",
        urgency=urgency,
        eligible=True,
        placement=Placement(
            cls="floating", slots=["admin"], min_block=30,
            days=days or [],
        ),
    )


def test_schedule_blocks_off_day_task_with_reason():
    blocks = [{"name": "Admin", "start": "09:00", "end": "10:00", "slot": "admin"}]
    weekend_task = _task(domain="chores", days=["sat", "sun"])
    everyday_task = _task(domain="career", days=[])
    result = schedule([weekend_task, everyday_task], today=MON, blocks=blocks)
    # weekend task surfaces as off-day; only the everyday task is placed
    assert weekend_task in result.blocked
    assert weekend_task.blocked_reason and "off-day" in weekend_task.blocked_reason
    assert weekend_task not in result.placed
    assert everyday_task in result.placed


def test_schedule_places_when_today_matches():
    blocks = [{"name": "Admin", "start": "09:00", "end": "10:00", "slot": "admin"}]
    weekend_task = _task(domain="chores", days=["sat", "sun"])
    result = schedule([weekend_task], today=SAT, blocks=blocks)
    assert weekend_task in result.placed
    assert weekend_task not in result.blocked


# --- compile: as-scheduled + days = light recurring nudge -------------------

def test_normalize_thresholds_skips_as_scheduled_without_days():
    """Pre-R6 behavior preserved: as-scheduled alone = event-driven, no Type 4 emitted."""
    lint = []
    tasks = _normalize_thresholds(
        {"upkeep": {"cadence": "as-scheduled"}}, lint, {})
    assert tasks == []


def test_normalize_thresholds_emits_low_urgency_nudge_with_days():
    lint = []
    tasks = _normalize_thresholds(
        {"upkeep": {"cadence": "as-scheduled"}},
        lint,
        {"upkeep": ["sat", "sun"]},
    )
    assert len(tasks) == 1
    t = tasks[0]
    assert t.domain == "upkeep"
    assert t.importance == "low"
    assert t.placement.days == ["sat", "sun"]
    assert t.placement.slots == ["admin"]
    # Cadence stays as-scheduled so cadence_debt_urgency returns 0.
    assert t.cadence == "as-scheduled"


def test_normalize_thresholds_passes_days_to_normal_cadence():
    lint = []
    tasks = _normalize_thresholds(
        {"music-practice": {"cadence": "daily", "unit": "minutes",
                            "target": 30, "min": 10}},
        lint,
        {"music-practice": ["mon", "tue"]},
    )
    assert tasks[0].placement.days == ["mon", "tue"]


# --- end-to-end: compile_queue with upkeep + days ---------------------------

def test_compile_queue_surfaces_upkeep_with_days(life_os):
    # life_os fixture omits upkeep; inject one with days to verify the chain.
    (life_os / "thresholds.yaml").write_text(
        "upkeep:\n  cadence: as-scheduled\n  days: [sat, sun]\n",
        encoding="utf-8",
    )
    tasks, _lint = compile_queue(life_os, SAT)
    upkeep = next((t for t in tasks if t.domain == "upkeep"), None)
    assert upkeep is not None
    assert upkeep.placement.days == ["sat", "sun"]
    assert upkeep.importance == "low"


def test_compile_queue_inherits_domain_days_into_tasks_md(life_os):
    """A Type 3 task with no placement.days inherits its domain's days."""
    (life_os / "thresholds.yaml").write_text(
        "career:\n  cadence: daily\n  unit: minutes\n  target: 30\n  days: [mon, tue, wed, thu, fri]\n",
        encoding="utf-8",
    )
    tasks, _lint = compile_queue(life_os, MON)
    career_tasks = [t for t in tasks if t.domain == "career" and t.source == "tasks"]
    assert career_tasks, "fixture has career tasks.md"
    for t in career_tasks:
        # Each Type 3 career task inherits weekday days from the domain.
        assert t.placement.days == ["mon", "tue", "wed", "thu", "fri"]
