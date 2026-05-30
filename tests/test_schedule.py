"""Unit tests for scheduler.schedule — deterministic placement."""
from datetime import date

from scheduler.constants import DEFAULT_BLOCKS
from scheduler.models import Placement, Task
from scheduler.schedule import schedule, render_daily_readme_body


TODAY = date(2026, 6, 1)


def mk(id, slots, importance="normal", urgency=0.0, cls="floating", min_block=60,
       eligible=True, waiting=False, mandatory_due=False, window=None, type=3,
       deadline=None, duration=60, domain="career", title=None):
    return Task(
        id=id, title=title or id, type=type, source="tasks", domain=domain,
        importance=importance, duration=duration, min=min_block,
        waiting=waiting, eligible=eligible, urgency=urgency, mandatory_due=mandatory_due,
        deadline=deadline,
        placement=Placement(cls=cls, slots=slots, min_block=min_block, window=window),
    )


def placed_in(result, block_name):
    for a in result.assignments:
        if a.block["name"] == block_name:
            return a.task
    return None


def test_single_task_placed_in_matching_slot():
    t = mk("career-001", ["deep-work"])
    r = schedule([t], TODAY)
    assert t in r.placed
    # earliest deep-work block is Deep Work 1
    assert placed_in(r, "Deep Work 1").id == "career-001"


def test_slot_mismatch_carried():
    t = mk("fit-001", ["exercise"], min_block=200)  # exceeds the 90-min exercise block
    r = schedule([t], TODAY)
    assert t in r.carried
    assert t not in r.placed


def test_priority_orders_into_earliest_block():
    low = mk("career-low", ["deep-work"], importance="low")
    high = mk("career-high", ["deep-work"], importance="high")
    r = schedule([low, high], TODAY)
    # higher priority gets the earliest fitting block
    assert placed_in(r, "Deep Work 1").id == "career-high"
    assert placed_in(r, "Deep Work 2").id == "career-low"


def test_urgency_promotes_across_tier():
    # a normal task with high urgency should beat a high task with none
    urgent = mk("a", ["deep-work"], importance="normal", urgency=150)
    high = mk("b", ["deep-work"], importance="high", urgency=0)
    r = schedule([urgent, high], TODAY)
    assert placed_in(r, "Deep Work 1").id == "a"


def test_ineligible_is_blocked_not_placed():
    t = mk("x", ["admin"], eligible=False)
    t.blocked_reason = "depends-on: y"
    r = schedule([t], TODAY)
    assert t in r.blocked
    assert t not in r.placed


def test_waiting_is_blocked():
    t = mk("w", ["admin"], waiting=True)
    r = schedule([t], TODAY)
    assert t in r.blocked


def test_mandatory_floor_wins_over_higher_regular():
    # mandatory normal task must take the slot over a higher-priority non-mandatory.
    # Use an explicit single-slot layout to force contention.
    one_block = [
        {"name": "Creative", "start": "13:30", "end": "15:00", "slot": "practice-creative"},
    ]
    floor = mk("mp", ["practice-creative"], importance="normal", mandatory_due=True)
    other = mk("prod", ["practice-creative"], importance="critical", urgency=0)
    r = schedule([floor, other], TODAY, blocks=one_block)
    # only one practice-creative block -> mandatory floor wins it
    assert placed_in(r, "Creative").id == "mp"
    assert other in r.carried


def test_window_restricts_placement():
    # window only overlaps the morning deep-work block
    t = mk("c", ["deep-work"], window=["08:00", "10:00"])
    r = schedule([t], TODAY)
    assert placed_in(r, "Deep Work 1").id == "c"


def test_determinism():
    tasks = [mk(f"t{i}", ["deep-work"], urgency=i) for i in range(5)]
    r1 = schedule(list(tasks), TODAY)
    r2 = schedule(list(reversed(tasks)), TODAY)
    assert [a.task.id if a.task else None for a in r1.assignments] == \
           [a.task.id if a.task else None for a in r2.assignments]


def test_reshuffle_excludes_done_and_blocks():
    t1 = mk("career-001", ["deep-work"], importance="high")
    t2 = mk("career-002", ["deep-work"], importance="normal")
    # Deep Work 1 is done (excluded block) and t1 already completed (excluded id)
    remaining_blocks = [b for b in DEFAULT_BLOCKS if b["name"] != "Deep Work 1"]
    r = schedule([t1, t2], TODAY, blocks=remaining_blocks, exclude_ids={"career-001"})
    assert placed_in(r, "Deep Work 2").id == "career-002"
    assert placed_in(r, "Deep Work 1") is None  # block not present


def test_render_has_all_sections():
    t = mk("career-001", ["deep-work"], title="Draft resume")
    body = render_daily_readme_body(schedule([t], TODAY), TODAY)
    assert "## Available Time Today" in body
    assert "## Today's Blocks" in body
    assert "## Non-Negotiables Today" in body
    assert "## Carried Forward" in body
    assert "Draft resume" in body
