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
from .day_template import load_day_template
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
            data.setdefault("block_edits", [])
            return data
    return {"date": today.isoformat(), "dropped": [], "boosted": [], "block_edits": []}


def save_state(root: Path, state: dict) -> None:
    _state_path(root).write_text(
        yaml.safe_dump(state, sort_keys=False, allow_unicode=True), encoding="utf-8")


def reset_state(root: Path, today: date) -> dict:
    state = {"date": today.isoformat(), "dropped": [], "boosted": [], "block_edits": []}
    save_state(root, state)
    return state


# --- Per-day block edits (manual reshuffle of the structure itself) ---------
# The day template (schedule/template.yaml) is the standing skeleton. Some days
# the user wants a one-off change — skip lunch, push a block later, extend one.
# Those edits live in today-state.yaml under `block_edits` and are applied on
# top of the template inside build_result, so they evaporate at the next reset
# (next morning) without ever touching the Cowork-owned source of truth.
#
# Each edit is one of:
#   {"op": "drop", "name": <block name>}                      remove for today
#   {"op": "set",  "name": <block name>, "start"|"end": "HH:MM"}  retime today
# Names match case-insensitively; edits for names not in the template are
# ignored (the template may have changed since the edit was recorded).

def resolve_block(blocks: list[dict], query: str):
    """Resolve a user's block query to a canonical block name.

    Returns (name, matches): an exact/unique match yields (name, [name]); an
    ambiguous query yields (None, [several]); no match yields (None, []).
    """
    q = (query or "").strip().lower()
    if not q:
        return None, []
    for b in blocks:
        if b["name"].lower() == q:
            return b["name"], [b["name"]]
    matches = [b["name"] for b in blocks if q in b["name"].lower()]
    return (matches[0], matches) if len(matches) == 1 else (None, matches)


def apply_block_edits(blocks: list[dict], edits) -> list[dict]:
    """Apply per-day drop/retime edits to a template block list.

    Returns a new, start-sorted block list; the input is not mutated.
    """
    out = [dict(b) for b in blocks]
    for e in edits or []:
        op = e.get("op")
        name = (e.get("name") or "").lower()
        if op == "drop":
            out = [b for b in out if b["name"].lower() != name]
        elif op == "set":
            for b in out:
                if b["name"].lower() == name:
                    if e.get("start"):
                        b["start"] = e["start"]
                    if e.get("end"):
                        b["end"] = e["end"]
    out.sort(key=lambda x: x["start"])
    return out


def _to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _from_min(m: int) -> str:
    m = max(0, min(m, 24 * 60 - 1))
    return f"{m // 60:02d}:{m % 60:02d}"


def find_overlaps(blocks: list[dict]) -> list[tuple[str, str, int]]:
    """Return every overlapping pair as (earlier_name, later_name, minutes).

    Walks blocks in start order and reports each (a, b) with overlap. Reports
    every later block a long edit engulfs — not just the first — so the user
    sees the full collision when skipping conflicting neighbours. Overlap is
    the intersection length: min(a_end, b_end) − b_start.
    """
    out: list[tuple[str, str, int]] = []
    ordered = sorted(blocks, key=lambda x: x["start"])
    for i, a in enumerate(ordered):
        a_end = _to_min(a["end"])
        for b in ordered[i + 1:]:
            b_start = _to_min(b["start"])
            if b_start >= a_end:
                break  # ordered by start: nothing later can collide with a
            overlap = min(a_end, _to_min(b["end"])) - b_start
            out.append((a["name"], b["name"], overlap))
    return out


def cascade_shift_edits(template_blocks: list[dict],
                        pending_edit: dict) -> tuple[list[dict], bool]:
    """Compute the edit list needed to push later blocks out of the way.

    Returns (edits, ran_past_midnight). The first edit is `pending_edit`
    itself; any further `set` edits push subsequent blocks forward by exactly
    the overlap delta. `ran_past_midnight` is True if a shift would have run
    past 23:59 (and was capped) — the caller can warn the user.
    """
    blocks = apply_block_edits(template_blocks, [pending_edit])
    ordered = sorted(blocks, key=lambda x: x["start"])
    edits: list[dict] = [pending_edit]
    ran_past = False
    for i in range(len(ordered) - 1):
        a = ordered[i]
        b = ordered[i + 1]
        a_end = _to_min(a["end"])
        b_start = _to_min(b["start"])
        if b_start < a_end:
            delta = a_end - b_start
            new_start = a_end
            new_end = _to_min(b["end"]) + delta
            if new_end >= 24 * 60:
                ran_past = True
                new_end = 24 * 60 - 1
            ordered[i + 1] = dict(b, start=_from_min(new_start), end=_from_min(new_end))
            edits.append({
                "op": "set", "name": b["name"],
                "start": _from_min(new_start), "end": _from_min(new_end),
            })
    return edits, ran_past


def skip_conflict_edits(template_blocks: list[dict],
                        pending_edit: dict) -> list[dict]:
    """Edits that apply the move plus drop every block it directly collides with."""
    blocks = apply_block_edits(template_blocks, [pending_edit])
    overlaps = find_overlaps(blocks)
    moved_name = pending_edit["name"].lower()
    edits: list[dict] = [pending_edit]
    seen: set[str] = set()
    for earlier, later, _delta in overlaps:
        # drop whichever side of the pair *isn't* the block we just moved
        victim = later if earlier.lower() == moved_name else earlier
        if victim.lower() != moved_name and victim.lower() not in seen:
            edits.append({"op": "drop", "name": victim})
            seen.add(victim.lower())
    return edits


def toggle_drop_block(state: dict, name: str) -> str:
    """Add or remove a 'drop' edit for `name`. Returns 'dropped' | 'restored'."""
    edits = state.setdefault("block_edits", [])
    existing = [e for e in edits if e.get("op") == "drop"
                and (e.get("name") or "").lower() == name.lower()]
    if existing:
        for e in existing:
            edits.remove(e)
        return "restored"
    edits.append({"op": "drop", "name": name})
    return "dropped"


def set_block_time(state: dict, name: str, start: str | None, end: str | None) -> None:
    """Record a retime edit for `name`, replacing any prior retime for it."""
    edits = state.setdefault("block_edits", [])
    edit = {"op": "set", "name": name}
    if start:
        edit["start"] = start
    if end:
        edit["end"] = end
    state["block_edits"] = [
        e for e in edits
        if not (e.get("op") == "set" and (e.get("name") or "").lower() == name.lower())
    ] + [edit]


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
    blocks, _source = load_day_template(root)
    blocks = apply_block_edits(blocks, state.get("block_edits"))
    result = schedule(
        tasks, today, blocks=blocks,
        exclude_ids=excluded, boost_ids=set(state.get("boosted", [])),
    )
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
