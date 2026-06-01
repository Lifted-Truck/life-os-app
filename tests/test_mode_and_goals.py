"""Tests for the goals-mode infrastructure.

scheduler/mode.py  — read/write persistence with safe defaults.
scheduler/goals.py — deterministic partition + rendering of the queue.
notifications.goals_mode_fire_times — life-skeleton + anchored events only.

Goals output is structure-tested: every eligible task surfaces, anchors are
sorted by clock time, ineligible items aren't dropped silently. The Haiku
phrasing pass is integration-only (no test — it's a wrapper that returns the
deterministic original on any failure).
"""
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from scheduler.goals import (
    render_goals_readme_body,
    render_goals_text,
    split_goals,
)
from scheduler.mode import (
    DEFAULT_MODE,
    VALID_PLAN_MODES,
    load_mode,
    save_mode,
    set_haiku_phrasing,
    set_plan_mode,
)
from scheduler.models import Placement, Task
from notifications import goals_mode_fire_times


TODAY = date(2026, 5, 31)


def _task(**kw):
    """Build a Task with sensible defaults for these tests."""
    defaults = dict(
        id=kw.get("id", "x-001"),
        title=kw.get("title", "X"),
        type=kw.get("type", 3),
        source=kw.get("source", "tasks"),
        domain=kw.get("domain", "career"),
        importance=kw.get("importance", "normal"),
        urgency=kw.get("urgency", 0.0),
        eligible=kw.get("eligible", True),
        waiting=kw.get("waiting", False),
        placement=kw.get("placement", Placement()),
    )
    for k in ("deadline", "deadline_type", "cadence", "blocked_reason"):
        if k in kw:
            defaults[k] = kw[k]
    return Task(**defaults)


# --- mode persistence -------------------------------------------------------

def test_load_mode_defaults_when_file_missing(tmp_path):
    m = load_mode(tmp_path)
    assert m == DEFAULT_MODE
    assert m["plan_mode"] == "blocks"
    assert m["haiku_phrasing"] is False


def test_save_and_reload_roundtrips(tmp_path):
    save_mode(tmp_path, {"plan_mode": "goals", "haiku_phrasing": True})
    m = load_mode(tmp_path)
    assert m["plan_mode"] == "goals" and m["haiku_phrasing"] is True


def test_invalid_plan_mode_falls_back_to_default(tmp_path):
    (tmp_path / "schedule").mkdir()
    (tmp_path / "schedule" / "mode.yaml").write_text(
        "plan_mode: enchiladas\nhaiku_phrasing: true\n", encoding="utf-8")
    m = load_mode(tmp_path)
    assert m["plan_mode"] == "blocks"   # invalid → default
    assert m["haiku_phrasing"] is True  # valid bool survives


def test_set_plan_mode_rejects_unknown(tmp_path):
    with pytest.raises(ValueError):
        set_plan_mode(tmp_path, "siesta")


def test_set_haiku_phrasing_persists(tmp_path):
    set_haiku_phrasing(tmp_path, True)
    assert load_mode(tmp_path)["haiku_phrasing"] is True
    set_haiku_phrasing(tmp_path, False)
    assert load_mode(tmp_path)["haiku_phrasing"] is False


# --- goals split + render ---------------------------------------------------

def test_split_partitions_into_four_buckets():
    anchor = _task(
        title="Dentist", type=2, domain="upkeep",
        deadline=TODAY,
        placement=Placement(cls="fixed", window=["14:00", "15:00"]),
    )
    live = _task(title="Draft resume", urgency=80.0)
    waiting = _task(title="Email landlord", waiting=True, eligible=False)
    blocked = _task(title="Phase 2", eligible=False, blocked_reason="deps unmet")
    a, l, w, b = split_goals([anchor, live, waiting, blocked], TODAY)
    assert a == [anchor]
    assert l == [live]
    assert w == [waiting]
    assert b == [blocked]


def test_live_sorted_by_urgency_desc():
    low = _task(id="a-001", title="Low", urgency=10.0)
    high = _task(id="a-002", title="High", urgency=90.0)
    _a, live, _w, _b = split_goals([low, high], TODAY)
    assert [t.title for t in live] == ["High", "Low"]


def test_anchors_sorted_by_time():
    late = _task(
        title="Late", type=2, deadline=TODAY,
        placement=Placement(cls="fixed", window=["17:00", "17:30"]),
    )
    early = _task(
        title="Early", type=2, deadline=TODAY,
        placement=Placement(cls="fixed", window=["08:00", "08:30"]),
    )
    a, _l, _w, _b = split_goals([late, early], TODAY)
    assert [t.title for t in a] == ["Early", "Late"]


def test_anchor_for_other_day_is_not_today():
    other_day = _task(
        title="Tomorrow's thing", type=2, deadline=date(2026, 6, 1),
        placement=Placement(cls="fixed", window=["09:00", "09:30"]),
    )
    a, l, _w, _b = split_goals([other_day], TODAY)
    assert a == []
    # falls through to live (it's eligible) — fine, the goals view doesn't
    # claim to be a multi-day calendar
    assert other_day in l


def test_render_goals_text_includes_every_section():
    anchor = _task(
        title="Dentist", type=2, deadline=TODAY,
        placement=Placement(cls="fixed", window=["14:00", "15:00"]),
    )
    live = _task(title="Draft resume", domain="career", urgency=80.0)
    waiting = _task(title="Email landlord", waiting=True, eligible=False)
    text = render_goals_text([anchor, live, waiting], TODAY)
    assert "Anchors:" in text
    assert "Dentist" in text and "14:00" in text
    assert "Live today:" in text and "career:" in text and "Draft resume" in text
    assert "Waiting:" in text and "Email landlord" in text


def test_render_goals_text_handles_empty_day():
    text = render_goals_text([], TODAY)
    assert "Today's goals" in text
    assert "nothing eligible" in text.lower()


def test_render_goals_readme_body_has_markdown_sections():
    live = _task(title="Draft resume", domain="career", urgency=80.0)
    body = render_goals_readme_body([live], TODAY)
    assert "## Today's Goals (untimed)" in body
    assert "### career" in body
    assert "Draft resume" in body
    assert "## Today's Anchors" in body


# --- notifications: goals-mode fire times ----------------------------------

def test_goals_mode_fires_only_for_skeleton_blocks_and_anchors():
    template = [
        {"name": "Wake / coffee", "start": "07:00", "end": "07:30", "slot": None},
        {"name": "Deep Work 1", "start": "09:00", "end": "11:00", "slot": "deep-work"},
        {"name": "Lunch",       "start": "12:30", "end": "13:30", "slot": None},
    ]
    anchor = _task(
        title="Dentist", type=2, deadline=TODAY,
        placement=Placement(cls="fixed", window=["14:00", "15:00"]),
    )
    notify = goals_mode_fire_times(
        template, [anchor], TODAY, now=datetime(2026, 5, 31, 6, 0))
    names = [name for name, _ in notify]
    assert "Wake / coffee" in names    # life skeleton
    assert "Lunch" in names            # life skeleton
    assert "Dentist" in names          # anchored Type 2 event
    assert "Deep Work 1" not in names  # work block — silent in goals mode


def test_goals_mode_skips_past_times():
    template = [{"name": "Lunch", "start": "12:30", "end": "13:30", "slot": None}]
    notify = goals_mode_fire_times(
        template, [], TODAY, now=datetime(2026, 5, 31, 14, 0))
    assert notify == []   # 12:25 already passed
