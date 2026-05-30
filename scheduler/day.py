"""Shared day-plan builder used by BOTH morning.py and bot.py.

This is the single place daily/README.md is composed, so the bot never invents
scheduling logic (SYSTEM.md: both writers go through the shared engine).

Per-day mutable state (drops/boosts from bot reshuffles) lives in
schedule/today-state.yaml — a small disposable sidecar, reset each morning.
The frozen task urgencies live in schedule/queue.yaml; reshuffle re-runs
schedule() over the same queue, it does not recompile.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yaml

from .compile_queue import load_queue
from .logs import read_log_entries
from .schedule import render_daily_readme_body, schedule

DAILY_README_TEMPLATE = """\
<!-- SCRIPT-OWNED: written by morning.py (overwrite) and bot.py (reshuffle).
     Both go through scheduler.day. Do not restructure. -->

# Daily Plan

**Date:** {date}
**Generated:** {generated}

{body}"""


def _state_path(root: Path) -> Path:
    return root / "schedule" / "today-state.yaml"


def load_state(root: Path, today: date) -> dict:
    """Load today's reshuffle state, auto-resetting if it's from a previous day."""
    p = _state_path(root)
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if data.get("date") == today.isoformat():
            data.setdefault("dropped", [])
            data.setdefault("boosted", [])
            return data
    return {"date": today.isoformat(), "dropped": [], "boosted": []}


def save_state(root: Path, state: dict) -> None:
    _state_path(root).write_text(
        yaml.safe_dump(state, sort_keys=False, allow_unicode=True), encoding="utf-8")


def reset_state(root: Path, today: date) -> dict:
    state = {"date": today.isoformat(), "dropped": [], "boosted": []}
    save_state(root, state)
    return state


def done_ids_today(root: Path, today: date) -> set:
    """Task ids logged done today (excluded from the remaining-day reshuffle)."""
    return {e.task_id for e in read_log_entries(root)
            if e.date == today and e.task_id and e.outcome == "done"}


def build_result(root: Path, today: Optional[date] = None):
    """Reconstruct the current day plan from queue.yaml + today's state + log.

    Returns (result, state). Deterministic: same inputs -> same plan.
    """
    today = today or date.today()
    tasks, _lint, _gen = load_queue(root)
    state = load_state(root, today)
    excluded = done_ids_today(root, today) | set(state.get("dropped", []))
    result = schedule(tasks, today, exclude_ids=excluded, boost_ids=set(state.get("boosted", [])))
    return result, state


def write_daily_readme(root: Path, result, today: Optional[date] = None) -> None:
    today = today or date.today()
    body = render_daily_readme_body(result, today)
    content = DAILY_README_TEMPLATE.format(
        date=today.isoformat(),
        generated=datetime.now().strftime("%H:%M"),
        body=body,
    )
    (root / "daily" / "README.md").write_text(content, encoding="utf-8")


def reshuffle_and_write(root: Path, today: Optional[date] = None):
    """Rebuild the plan from current state and rewrite daily/README.md."""
    today = today or date.today()
    result, _state = build_result(root, today)
    write_daily_readme(root, result, today)
    return result


def task_in_block(result, block_name: str):
    """The Task assigned to a named block in a ScheduleResult, or None."""
    for a in result.assignments:
        if a.block["name"] == block_name:
            return a.task
    return None
