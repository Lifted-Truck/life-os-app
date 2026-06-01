"""Tests for R5 — immutable blocks + /shift day cascade.

Covers:
  • Template loader accepts `immutable: true` (default false).
  • shift_day_edits leaves past blocks and immutable blocks alone.
  • Collisions with immutable blocks surface for the caller's conflict menu.
  • V1 default: no template block flagged immutable -> /shift cascades the
    whole skeleton, dormant collision path.
"""
import pytest

from scheduler.day import apply_block_edits, shift_day_edits
from scheduler.day_template import parse_blocks


TEMPLATE = [
    {"name": "Morning Pages", "start": "07:00", "end": "08:00", "slot": None},
    {"name": "Deep Work 1",   "start": "09:00", "end": "11:00", "slot": "deep-work"},
    {"name": "Lunch",         "start": "12:30", "end": "13:30", "slot": None},
    {"name": "Admin",         "start": "15:00", "end": "16:30", "slot": "admin"},
]


# --- loader ----------------------------------------------------------------

def test_loader_accepts_immutable_field():
    blocks = parse_blocks({"blocks": [
        {"name": "Morning Pages", "start": "07:00", "end": "08:00",
         "slot": None, "immutable": True},
        {"name": "Deep Work 1", "start": "09:00", "end": "11:00",
         "slot": "deep-work"},
    ]})
    assert blocks[0]["immutable"] is True
    assert blocks[1]["immutable"] is False   # defaulted


def test_loader_defaults_immutable_false_when_omitted():
    blocks = parse_blocks({"blocks": [
        {"name": "Deep Work 1", "start": "09:00", "end": "11:00",
         "slot": "deep-work"},
    ]})
    assert blocks[0]["immutable"] is False


# --- shift_day_edits -------------------------------------------------------

def test_shift_pushes_all_future_blocks_by_n():
    edits, collisions = shift_day_edits(TEMPLATE, [], 30, now_hhmm="08:30")
    # Morning Pages (07:00) is past; the rest shift +30 min
    moved = {e["name"]: (e["start"], e["end"]) for e in edits}
    assert "Morning Pages" not in moved
    assert moved["Deep Work 1"] == ("09:30", "11:30")
    assert moved["Lunch"] == ("13:00", "14:00")
    assert moved["Admin"] == ("15:30", "17:00")
    assert collisions == []


def test_shift_steps_over_immutable_blocks():
    template = [dict(b) for b in TEMPLATE]
    template[2]["immutable"] = True   # Lunch is immutable
    edits, collisions = shift_day_edits(template, [], 30, now_hhmm="08:30")
    moved = {e["name"]: (e["start"], e["end"]) for e in edits}
    assert "Lunch" not in moved      # immutable -> not in edit list
    assert moved["Deep Work 1"] == ("09:30", "11:30")
    # Deep Work 1's new window (09:30-11:30) doesn't touch Lunch (12:30-13:30)
    assert collisions == []


def test_shift_collision_surfaces_immutable_name():
    template = [dict(b) for b in TEMPLATE]
    template[2]["immutable"] = True   # Lunch immutable
    # Shift +120 min -> Deep Work 1 becomes 11:00-13:00 which collides with Lunch (12:30-13:30)
    edits, collisions = shift_day_edits(template, [], 120, now_hhmm="08:30")
    assert "Lunch" in collisions


def test_shift_respects_existing_edits():
    """If today already has a /move applied, /shift composes on top of it."""
    edits, _c = shift_day_edits(
        TEMPLATE,
        [{"op": "set", "name": "Admin", "start": "14:00", "end": "15:30"}],
        30,
        now_hhmm="08:30",
    )
    moved = {e["name"]: (e["start"], e["end"]) for e in edits}
    assert moved["Admin"] == ("14:30", "16:00")   # shifted from the edited time


def test_shift_does_not_modify_past_blocks():
    edits, _c = shift_day_edits(TEMPLATE, [], 30, now_hhmm="10:00")
    names = {e["name"] for e in edits}
    # Morning Pages (07:00) and Deep Work 1 (09:00) are both past
    assert "Morning Pages" not in names
    assert "Deep Work 1" not in names
    assert "Lunch" in names and "Admin" in names


def test_shift_caps_at_midnight():
    edits, _c = shift_day_edits(
        [{"name": "Late", "start": "22:00", "end": "23:00", "slot": None}],
        [], 240, now_hhmm="08:00",
    )
    late = next(e for e in edits if e["name"] == "Late")
    assert late["start"] == "23:59"
    assert late["end"] == "23:59"


def test_shift_returns_empty_when_nothing_left_in_day():
    edits, collisions = shift_day_edits(TEMPLATE, [], 30, now_hhmm="20:00")
    assert edits == []
    assert collisions == []
