"""Tests for per-day block edits — the manual-reshuffle layer over the template.

These drive the same engine code the /skip and /move Telegram commands use:
drop a block for today, retime a block, resolve a fuzzy block name, and confirm
the edits flow through build_result and reset overnight.
"""
from datetime import date

from scheduler.compile_queue import compile_to_file
from scheduler.day import (
    apply_block_edits,
    build_result,
    cascade_shift_edits,
    find_overlaps,
    load_state,
    reset_state,
    resolve_block,
    save_state,
    set_block_time,
    skip_conflict_edits,
    toggle_drop_block,
)

TODAY = date(2026, 6, 1)

BLOCKS = [
    {"name": "Deep Work 1", "start": "08:00", "end": "10:00", "slot": "deep-work"},
    {"name": "Lunch", "start": "12:30", "end": "13:30", "slot": None},
    {"name": "Admin / Career", "start": "15:00", "end": "16:30", "slot": "admin"},
]


# --- apply_block_edits ------------------------------------------------------

def test_drop_removes_named_block():
    out = apply_block_edits(BLOCKS, [{"op": "drop", "name": "Lunch"}])
    assert [b["name"] for b in out] == ["Deep Work 1", "Admin / Career"]


def test_drop_is_case_insensitive():
    out = apply_block_edits(BLOCKS, [{"op": "drop", "name": "lunch"}])
    assert all(b["name"] != "Lunch" for b in out)


def test_set_retimes_and_resorts():
    out = apply_block_edits(
        BLOCKS, [{"op": "set", "name": "Admin / Career", "start": "07:00", "end": "07:30"}])
    # moved to the front after re-sort
    assert out[0]["name"] == "Admin / Career"
    assert out[0]["start"] == "07:00" and out[0]["end"] == "07:30"


def test_set_partial_end_only():
    out = apply_block_edits(BLOCKS, [{"op": "set", "name": "Deep Work 1", "end": "11:00"}])
    dw = next(b for b in out if b["name"] == "Deep Work 1")
    assert dw["start"] == "08:00" and dw["end"] == "11:00"


def test_unknown_name_is_ignored():
    out = apply_block_edits(BLOCKS, [{"op": "drop", "name": "Nope"}])
    assert len(out) == len(BLOCKS)


def test_input_is_not_mutated():
    apply_block_edits(BLOCKS, [{"op": "set", "name": "Lunch", "start": "01:00"}])
    assert BLOCKS[1]["start"] == "12:30"


# --- resolve_block ----------------------------------------------------------

def test_resolve_exact():
    name, matches = resolve_block(BLOCKS, "Lunch")
    assert name == "Lunch"


def test_resolve_substring_unique():
    name, _ = resolve_block(BLOCKS, "admin")
    assert name == "Admin / Career"


def test_resolve_ambiguous():
    blocks = BLOCKS + [{"name": "Deep Work 2", "start": "10:30", "end": "12:00", "slot": "deep-work"}]
    name, matches = resolve_block(blocks, "deep")
    assert name is None and set(matches) == {"Deep Work 1", "Deep Work 2"}


def test_resolve_no_match():
    name, matches = resolve_block(BLOCKS, "yoga")
    assert name is None and matches == []


# --- state helpers ----------------------------------------------------------

def test_toggle_drop_round_trips():
    state = {"block_edits": []}
    assert toggle_drop_block(state, "Lunch") == "dropped"
    assert {"op": "drop", "name": "Lunch"} in state["block_edits"]
    assert toggle_drop_block(state, "Lunch") == "restored"
    assert state["block_edits"] == []


def test_set_block_time_replaces_prior():
    state = {"block_edits": []}
    set_block_time(state, "Admin / Career", "15:00", "17:00")
    set_block_time(state, "Admin / Career", "16:00", "18:00")
    sets = [e for e in state["block_edits"] if e["op"] == "set"]
    assert len(sets) == 1 and sets[0]["start"] == "16:00" and sets[0]["end"] == "18:00"


# --- conflict resolution ----------------------------------------------------

def test_find_overlaps_none():
    assert find_overlaps(BLOCKS) == []


def test_find_overlaps_detects_adjacent_collision():
    edited = apply_block_edits(
        BLOCKS, [{"op": "set", "name": "Deep Work 1", "end": "13:00"}])
    overlaps = find_overlaps(edited)
    # Deep Work 1 (08-13) now eats into Lunch (12:30-13:30): 30-min overlap
    assert overlaps == [("Deep Work 1", "Lunch", 30)]


def test_find_overlaps_reports_every_engulfed_block():
    blocks = [
        {"name": "Long", "start": "08:00", "end": "13:00", "slot": "deep-work"},
        {"name": "B1",   "start": "10:00", "end": "10:30", "slot": None},
        {"name": "B2",   "start": "10:30", "end": "12:30", "slot": "deep-work"},
        {"name": "B3",   "start": "12:30", "end": "13:30", "slot": None},
    ]
    overlaps = find_overlaps(blocks)
    names = {(a, b) for a, b, _ in overlaps}
    # Long engulfs B1 (30m), B2 (120m), B3 partially (30m)
    assert ("Long", "B1") in names
    assert ("Long", "B2") in names
    assert ("Long", "B3") in names


def test_cascade_shift_pushes_later_blocks():
    pending = {"op": "set", "name": "Deep Work 1", "end": "13:00"}
    edits, ran_past = cascade_shift_edits(BLOCKS, pending)
    assert not ran_past
    # Lunch should be pushed by 30 min to 13:00-14:00
    lunch_edit = next(e for e in edits if e["name"] == "Lunch")
    assert lunch_edit["start"] == "13:00" and lunch_edit["end"] == "14:00"
    # Original edit stays at the front of the list
    assert edits[0] is pending


def test_cascade_warns_when_capping_at_midnight():
    pending = {"op": "set", "name": "Admin / Career", "end": "23:00"}
    blocks = BLOCKS + [{"name": "Wind-Down", "start": "20:00", "end": "21:00", "slot": "wind-down"}]
    _edits, ran_past = cascade_shift_edits(blocks, pending)
    assert ran_past is True


def test_skip_conflict_drops_the_neighbour():
    pending = {"op": "set", "name": "Deep Work 1", "end": "13:00"}
    edits = skip_conflict_edits(BLOCKS, pending)
    assert {"op": "drop", "name": "Lunch"} in edits
    assert pending in edits


# --- end-to-end through build_result ----------------------------------------

def test_dropped_block_absent_from_plan(life_os):
    compile_to_file(life_os, TODAY)
    reset_state(life_os, TODAY)
    before, state = build_result(life_os, TODAY)
    target = before.assignments[0].block["name"]

    toggle_drop_block(state, target)
    save_state(life_os, state)
    after, _ = build_result(life_os, TODAY)

    assert target not in [a.block["name"] for a in after.assignments]


def test_block_edits_reset_next_day(life_os):
    save_state(life_os, {
        "date": "2026-05-01", "dropped": [], "boosted": [],
        "block_edits": [{"op": "drop", "name": "Lunch"}],
    })
    state = load_state(life_os, TODAY)   # different day -> fresh
    assert state["block_edits"] == []
