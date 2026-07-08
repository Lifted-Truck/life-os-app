"""Screen-free / rest-day primitive + its compile-time effect on both plan modes."""
from datetime import date

import yaml

from scheduler.restday import closed_slots_today, is_screen_free_blocked
from scheduler.compile_queue import compile_queue
from scheduler.goals import split_goals

SUN = date(2026, 7, 12)   # Sunday
MON = date(2026, 7, 13)   # Monday


# --- unit: closed_slots_today -------------------------------------------------

def test_no_config_no_closure():
    assert closed_slots_today(None, SUN) == set()
    assert closed_slots_today({}, SUN) == set()
    assert closed_slots_today({"ramp": 0.25}, SUN) == set()


def test_screen_free_day_closes_default_screen_slots():
    cfg = {"screen-free-days": ["sun"]}
    assert closed_slots_today(cfg, SUN) == {"deep-work", "admin", "practice-creative"}
    assert closed_slots_today(cfg, MON) == set()   # not the configured day


def test_sugar_and_custom_slots():
    cfg = {"screen-free-days": ["weekend"], "screen-free-slots": ["deep-work"]}
    assert closed_slots_today(cfg, SUN) == {"deep-work"}


def test_full_mode_closes_everything():
    cfg = {"screen-free-days": ["sun"], "screen-free-mode": "full"}
    got = closed_slots_today(cfg, SUN)
    assert "exercise" in got and "deep-work" in got


def test_malformed_config_degrades_to_normal_day():
    assert closed_slots_today({"screen-free-days": "notalist"}, SUN) == set()


# --- unit: is_screen_free_blocked --------------------------------------------

def test_blocked_only_when_all_slots_closed():
    closed = {"deep-work", "admin", "practice-creative"}
    assert is_screen_free_blocked(["deep-work", "admin"], closed) is True   # all closed
    assert is_screen_free_blocked(["exercise"], closed) is False            # open slot
    assert is_screen_free_blocked(["deep-work", "exercise"], closed) is False  # one open
    assert is_screen_free_blocked([], closed) is False                      # anchors: never
    assert is_screen_free_blocked(["deep-work"], set()) is False            # normal day


# --- integration: compile marks the right tasks, both modes honor it ----------

def _write_root(root):
    """A minimal tree: career (screen slots) + fitness (exercise), screen-free Sun."""
    (root / "domains" / "career").mkdir(parents=True, exist_ok=True)
    (root / "domains" / "fitness").mkdir(parents=True, exist_ok=True)
    for d in ("career", "fitness"):
        (root / "domains" / d / "tasks.md").write_text(
            "next-id: 1\n```yaml\n[]\n```\n", encoding="utf-8")
    (root / "thresholds.yaml").write_text(yaml.safe_dump({
        "config": {"ramp": 0.25, "screen-free-days": ["sun"]},
        "career": {"min": 30, "aspirational": 60, "unit": "minutes", "cadence": "daily"},
        "fitness": {"floor": 1, "aspirational": 3, "unit": "sessions", "cadence": "weekly"},
    }), encoding="utf-8")


def _by_id(tasks):
    return {t.id: t for t in tasks}


def test_compile_blocks_screen_recurring_but_not_exercise_on_sunday(tmp_path):
    _write_root(tmp_path)
    tasks, _lint = compile_queue(tmp_path, today=SUN)
    by = _by_id(tasks)
    # career-recurring lives in screen slots [deep-work, admin] -> blocked
    assert by["career-recurring"].eligible is False
    assert "screen-free" in (by["career-recurring"].blocked_reason or "")
    # fitness-recurring lives in [exercise] -> stays eligible
    assert by["fitness-recurring"].eligible is True
    assert "screen-free" not in (by["fitness-recurring"].blocked_reason or "")


def test_normal_day_unaffected(tmp_path):
    _write_root(tmp_path)
    tasks, _lint = compile_queue(tmp_path, today=MON)
    by = _by_id(tasks)
    assert by["career-recurring"].eligible is True
    assert "screen-free" not in (by["career-recurring"].blocked_reason or "")


def test_goals_mode_moves_screen_tasks_to_blocked_on_sunday(tmp_path):
    _write_root(tmp_path)
    tasks, _lint = compile_queue(tmp_path, today=SUN)
    _anchors, live, _waiting, blocked = split_goals(tasks, SUN)
    live_ids = {t.id for t in live}
    blocked_ids = {t.id for t in blocked}
    assert "career-recurring" in blocked_ids and "career-recurring" not in live_ids
    assert "fitness-recurring" in live_ids   # exercise stays live
