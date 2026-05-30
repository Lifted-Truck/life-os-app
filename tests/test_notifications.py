"""Tests for the T-5 fire-time computation.

The APScheduler wiring itself is intentionally thin — the testable bit is
notifications.plan_fire_times: given today's plan and 'now', return the
notify and check-in fire times filtered to the future.
"""
from datetime import date, datetime
from types import SimpleNamespace

from notifications import plan_fire_times
from scheduler.schedule import Assignment, ScheduleResult


def _result(blocks_with_task):
    """blocks_with_task = [(block_dict, task_or_None), ...]"""
    r = ScheduleResult()
    r.assignments = [Assignment(block=b, task=t) for b, t in blocks_with_task]
    return r


B_MORNING = {"name": "Morning Pages & Coffee", "start": "07:00", "end": "08:00", "slot": None}
B_DEEP = {"name": "Deep Work 1", "start": "08:00", "end": "10:00", "slot": "deep-work"}
B_LUNCH = {"name": "Lunch", "start": "12:30", "end": "13:30", "slot": None}
TASK = SimpleNamespace(id="novel-001", title="novel")
TODAY = date(2026, 5, 30)


def test_notify_fires_five_min_before_start():
    notify, _ = plan_fire_times(
        _result([(B_DEEP, TASK)]), TODAY, now=datetime(2026, 5, 30, 6, 0))
    assert notify == [("Deep Work 1", datetime(2026, 5, 30, 7, 55))]


def test_checkin_fires_five_min_before_end_only_with_task():
    _, checkin = plan_fire_times(
        _result([(B_DEEP, TASK), (B_LUNCH, None)]),
        TODAY, now=datetime(2026, 5, 30, 6, 0))
    # check-in only on task-bearing blocks — Lunch (slot=None, no task) is skipped
    assert checkin == [("Deep Work 1", datetime(2026, 5, 30, 9, 55))]


def test_past_fire_times_are_dropped():
    notify, checkin = plan_fire_times(
        _result([(B_MORNING, None), (B_DEEP, TASK)]),
        TODAY, now=datetime(2026, 5, 30, 8, 30))  # mid-Deep-Work
    # Morning's 06:55 notify and Deep Work's 07:55 notify are both in the past
    assert notify == []
    # Deep Work's 09:55 check-in is still in the future
    assert checkin == [("Deep Work 1", datetime(2026, 5, 30, 9, 55))]


def test_notify_covers_fixed_blocks_too():
    """Lunch has slot=None but the user still wants the 'starting in 5' ping."""
    notify, _ = plan_fire_times(
        _result([(B_LUNCH, None)]), TODAY, now=datetime(2026, 5, 30, 6, 0))
    assert notify == [("Lunch", datetime(2026, 5, 30, 12, 25))]


def test_custom_lead_minutes():
    notify, _ = plan_fire_times(
        _result([(B_DEEP, TASK)]), TODAY,
        now=datetime(2026, 5, 30, 6, 0), lead_min=15)
    assert notify == [("Deep Work 1", datetime(2026, 5, 30, 7, 45))]
