"""schedule() — deterministic placement of tasks into the day's blocks.

Consumes the computed task list (from queue.yaml) and produces the day plan.
NO AI. Conflict-resolution policy, in fixed order (SYSTEM.md -> Scheduling Layer):

  1. Place `fixed` anchors at their pinned times.
  2. Protect `mandatory-weekly` floors (unmet recurring minimums).
  3. Fill remaining blocks by effective priority (importance weight + urgency),
     honoring slots / min-block / window; tie-break earliest-deadline then id.
  4. Demote what no longer fits to carry-forward.
  5. Surface everything dropped / blocked.

v1 places at most one task per block and uses urgency frozen at compile time.
Reshuffle = re-running schedule() over a restricted set of blocks with some
tasks excluded (already done/pinned); urgency is not recomputed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .constants import DEFAULT_BLOCKS, IMPORTANCE_WEIGHT


def _to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _block_minutes(block: dict) -> int:
    return _to_min(block["end"]) - _to_min(block["start"])


def _windows_overlap(block: dict, window) -> bool:
    if not window:
        return True
    bs, be = _to_min(block["start"]), _to_min(block["end"])
    ws, we = _to_min(window[0]), _to_min(window[1])
    return bs < we and ws < be


@dataclass
class Assignment:
    block: dict
    task: Optional[object] = None     # Task or None (open slot)


@dataclass
class ScheduleResult:
    assignments: list = field(default_factory=list)   # one per block, in time order
    fixed_anchors: list = field(default_factory=list)  # fixed tasks w/o a standard block
    placed: list = field(default_factory=list)
    carried: list = field(default_factory=list)        # eligible, no capacity
    blocked: list = field(default_factory=list)        # ineligible (waiting/deps/not-before)

    def placed_ids(self) -> set:
        return {t.id for t in self.placed}


# A boosted ("pinned in" via /add) task always wins its slot over normal fill.
BOOST_WEIGHT = 10_000


def _make_sort_key(boost_ids: set):
    def _sort_key(task):
        """Higher effective priority first; tie-break earliest deadline, then id."""
        eff = task.effective_priority(IMPORTANCE_WEIGHT)
        if task.id in boost_ids:
            eff += BOOST_WEIGHT
        deadline_ord = task.deadline.toordinal() if task.deadline else 10**9
        return (-eff, deadline_ord, task.id)
    return _sort_key


def _required_block(task) -> int:
    if task.placement.min_block:
        return task.placement.min_block
    if task.duration:
        return int(task.duration)
    return 0


def _fits(task, block: dict) -> bool:
    if block["slot"] is None:
        return False
    if block["slot"] not in task.placement.slots:
        return False
    if _required_block(task) > _block_minutes(block):
        return False
    if not _windows_overlap(block, task.placement.window):
        return False
    return True


def schedule(tasks: list, today: Optional[date] = None,
             blocks: Optional[list] = None, exclude_ids: Optional[set] = None,
             boost_ids: Optional[set] = None) -> ScheduleResult:
    """Place tasks into blocks deterministically.

    `blocks`/`exclude_ids` support reshuffle (restrict to remaining blocks, drop
    completed/removed task ids). `boost_ids` forces a task to win its slot
    (the /add "pin it" interaction). No AI; same inputs -> same plan.
    """
    today = today or date.today()
    blocks = blocks if blocks is not None else DEFAULT_BLOCKS
    exclude_ids = exclude_ids or set()
    boost_ids = boost_ids or set()
    _sort_key = _make_sort_key(boost_ids)

    result = ScheduleResult()
    # initialize one assignment slot per block, in time order
    result.assignments = [Assignment(block=b) for b in blocks]
    used_block_idx: set = set()

    candidates = [t for t in tasks if t.id not in exclude_ids]

    # Surface ineligible tasks (blocked) and exclude waiting/ineligible from placement
    schedulable = []
    for t in candidates:
        if t.waiting or not t.eligible:
            result.blocked.append(t)
        else:
            schedulable.append(t)

    def first_open_block(task) -> Optional[int]:
        for i, asn in enumerate(result.assignments):
            if i in used_block_idx:
                continue
            if _fits(task, asn.block):
                return i
        return None

    # Phase 1 — fixed anchors
    fixed = [t for t in schedulable if t.placement.cls == "fixed"]
    floating = [t for t in schedulable if t.placement.cls != "fixed"]
    for t in sorted(fixed, key=_sort_key):
        idx = first_open_block(t)
        if idx is not None:
            result.assignments[idx].task = t
            used_block_idx.add(idx)
            result.placed.append(t)
        else:
            # no standard block matches its clock window — keep as explicit anchor
            result.fixed_anchors.append(t)
            result.placed.append(t)

    # Phase 2 — mandatory-weekly floors, then Phase 3 — priority fill.
    mandatory = sorted([t for t in floating if t.mandatory_due], key=_sort_key)
    regular = sorted([t for t in floating if not t.mandatory_due], key=_sort_key)
    for t in mandatory + regular:
        idx = first_open_block(t)
        if idx is not None:
            result.assignments[idx].task = t
            used_block_idx.add(idx)
            result.placed.append(t)
        else:
            result.carried.append(t)   # Phase 4 — demote losers

    return result


# --- Rendering: ScheduleResult -> daily/README.md body ---------------------

def _type_label(t) -> str:
    return f"T{t.type}"


def render_daily_readme_body(result: ScheduleResult, today: Optional[date] = None) -> str:
    today = today or date.today()
    lines: list = []

    # Available Time Today
    open_slots = sum(1 for a in result.assignments
                     if a.block["slot"] is not None and a.task is None)
    work_blocks = sum(1 for a in result.assignments if a.block["slot"] is not None)
    lines.append("## Available Time Today")
    lines.append("")
    lines.append(
        f"{work_blocks} schedulable blocks; {len(result.placed)} task(s) placed, "
        f"{open_slots} open."
    )
    lines.append("")

    # Today's Blocks
    lines.append("## Today's Blocks")
    lines.append("")
    lines.append("| Time | Block | Domain | Task | Type | Duration | Status |")
    lines.append("|------|-------|--------|------|------|----------|--------|")
    for a in result.assignments:
        b = a.block
        time = f"{b['start']}–{b['end']}"
        dur = f"{_block_minutes(b)} min"
        if a.task is not None:
            t = a.task
            lines.append(
                f"| {time} | {b['name']} | {t.domain or '—'} | {t.title} | "
                f"{_type_label(t)} | {dur} | planned |"
            )
        elif b["slot"] is None:
            lines.append(f"| {time} | {b['name']} | — | — | — | {dur} | — |")
        else:
            lines.append(
                f"| {time} | {b['name']} | — | _open ({b['slot']})_ | — | {dur} | open |"
            )
    lines.append("")

    # Non-Negotiables Today
    lines.append("## Non-Negotiables Today")
    lines.append("")
    floors = [t for t in result.placed if getattr(t, "mandatory_due", False)]
    anchors = result.fixed_anchors
    if floors or anchors:
        for t in floors:
            lines.append(f"- {t.domain or t.title} — mandatory-weekly floor (placed)")
        for t in anchors:
            win = t.placement.window
            when = f" @ {win[0]}" if win else ""
            lines.append(f"- {t.title}{when} — fixed anchor")
    else:
        lines.append("None flagged.")
    lines.append("")

    # Carried Forward
    lines.append("## Carried Forward")
    lines.append("")
    if result.carried or result.blocked:
        for t in result.carried:
            lines.append(f"- {t.title} ({t.id}) — no capacity today")
        for t in result.blocked:
            reason = t.blocked_reason or ("waiting" if t.waiting else "ineligible")
            lines.append(f"- {t.title} ({t.id}) — blocked: {reason}")
    else:
        lines.append("None.")
    lines.append("")

    return "\n".join(lines)
