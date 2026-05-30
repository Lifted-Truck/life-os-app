"""Integration tests for scheduler.day — the reshuffle state model the bot drives.

These exercise the same code paths as the Telegram handlers (check-in reshuffle,
/behind drop, /add pin) without needing Telegram itself.
"""
from datetime import date

from scheduler.compile_queue import compile_to_file
from scheduler.day import (
    build_result,
    done_ids_today,
    load_state,
    reshuffle_and_write,
    reset_state,
    save_state,
    task_in_block,
)


TODAY = date(2026, 6, 1)


def _placed_ids(result):
    return {t.id for t in result.placed}


def test_morning_then_build_matches(life_os):
    compile_to_file(life_os, TODAY)
    reset_state(life_os, TODAY)
    result, state = build_result(life_os, TODAY)
    assert state["dropped"] == [] and state["boosted"] == []
    assert len(result.placed) > 0


def test_drop_removes_task_and_promotes_carried(life_os):
    compile_to_file(life_os, TODAY)
    reset_state(life_os, TODAY)
    before, state = build_result(life_os, TODAY)
    # the admin slot has more eligible tasks than blocks, so one admin task is
    # carried. Drop the placed admin task -> the carried one takes the slot.
    admin_task = task_in_block(before, "Admin / Career")
    assert admin_task is not None
    carried_ids = {t.id for t in before.carried}
    assert carried_ids  # the fixture overflows at least one slot

    state["dropped"].append(admin_task.id)
    save_state(life_os, state)
    after, _ = build_result(life_os, TODAY)

    assert admin_task.id not in _placed_ids(after)
    # a previously-carried task now occupies the freed admin slot
    new_admin = task_in_block(after, "Admin / Career")
    assert new_admin is not None
    assert new_admin.id in carried_ids


def test_pin_forces_carried_task_in(life_os):
    compile_to_file(life_os, TODAY)
    reset_state(life_os, TODAY)
    before, state = build_result(life_os, TODAY)
    carried = before.carried
    assert carried, "fixture should produce at least one carried task"
    pick = carried[0]

    state["boosted"].append(pick.id)
    save_state(life_os, state)
    after, _ = build_result(life_os, TODAY)
    assert pick.id in _placed_ids(after)


def test_checkin_done_excludes_via_log(life_os):
    compile_to_file(life_os, TODAY)
    reset_state(life_os, TODAY)
    before, _ = build_result(life_os, TODAY)
    deep = task_in_block(before, "Deep Work 1")
    assert deep is not None

    # simulate the check-in writing a done log entry with the task id
    (life_os / "daily" / "logs" / f"{TODAY.isoformat()}.md").write_text(
        f"## {TODAY.isoformat()}\n\n- **outcome:** done\n- **task:** {deep.id}\n",
        encoding="utf-8")
    assert deep.id in done_ids_today(life_os, TODAY)

    after, _ = build_result(life_os, TODAY)
    assert deep.id not in _placed_ids(after)


def test_state_resets_on_new_day(life_os):
    save_state(life_os, {"date": "2026-05-01", "dropped": ["x"], "boosted": ["y"]})
    state = load_state(life_os, TODAY)   # different day -> fresh
    assert state["dropped"] == [] and state["boosted"] == []


def test_reshuffle_writes_readme(life_os):
    compile_to_file(life_os, TODAY)
    reset_state(life_os, TODAY)
    reshuffle_and_write(life_os, TODAY)
    readme = (life_os / "daily" / "README.md").read_text(encoding="utf-8")
    assert "# Daily Plan" in readme
    assert "## Today's Blocks" in readme
