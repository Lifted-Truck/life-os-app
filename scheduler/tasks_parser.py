"""Parser/validator for domains/<domain>/tasks.md (DOMAIN-FORMAT.md §7.1).

A tasks.md file is:

    <!-- comment -->
    next-id: 7

    # <Domain> — Task Records

    ```yaml
    - id: career-006
      ...
    ```

This module extracts the `next-id` counter and the fenced YAML record list, and
validates each record structurally. Cross-record checks (dangling depends-on) are
done later in compile() once all ids across all domains are known.

Returns (next_id, tasks, issues) and never raises on bad content — malformed
records become LintIssues so compile() can surface them rather than crash.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yaml

from .days import expand_days

from .constants import (
    DEADLINE_TYPES,
    IMPORTANCE_TIERS,
    PLACEMENT_CLASSES,
    SLOT_VOCAB,
    TYPE3_SUBTYPES,
    VALID_TYPES,
    VALID_UNITS,
)
from .models import LintIssue, Placement, Task

_NEXT_ID_RE = re.compile(r"^next-id:\s*(\d+)\s*$", re.MULTILINE)
_FENCE_RE = re.compile(r"```ya?ml\s*\n(.*?)```", re.DOTALL)


def _parse_date(value, where: str, field: str, issues: list) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        issues.append(LintIssue("error", where, f"{field}: invalid date '{value}' (expected YYYY-MM-DD)"))
        return None


def parse_tasks_text(text: str, domain: str, source_name: str = "") -> tuple[int, list, list]:
    """Parse the contents of a tasks.md file for `domain`.

    Returns (next_id, tasks, issues). next_id defaults to 1 if absent (with an issue).
    """
    where = source_name or f"domains/{domain}/tasks.md"
    issues: list = []

    m = _NEXT_ID_RE.search(text)
    if m:
        next_id = int(m.group(1))
    else:
        next_id = 1
        issues.append(LintIssue("error", where, "missing 'next-id:' counter"))

    fence = _FENCE_RE.search(text)
    if not fence:
        # No YAML block at all — treat as empty but flag it.
        issues.append(LintIssue("warning", where, "no fenced ```yaml block found; treating as empty"))
        return next_id, [], issues

    try:
        raw = yaml.safe_load(fence.group(1))
    except yaml.YAMLError as e:
        issues.append(LintIssue("error", where, f"YAML parse error: {e}"))
        return next_id, [], issues

    if raw is None:
        raw = []
    if not isinstance(raw, list):
        issues.append(LintIssue("error", where, "task block is not a YAML list"))
        return next_id, [], issues

    id_re = re.compile(rf"^{re.escape(domain)}-(\d{{3}})$")
    tasks: list = []
    seen_ids: set = set()

    for idx, rec in enumerate(raw):
        rloc = f"{where}[{idx}]"
        if not isinstance(rec, dict):
            issues.append(LintIssue("error", rloc, "record is not a mapping"))
            continue

        rid = rec.get("id")
        if not rid:
            issues.append(LintIssue("error", rloc, "record missing required 'id'"))
            continue
        rloc = f"{where}:{rid}"

        idm = id_re.match(str(rid))
        if not idm:
            issues.append(LintIssue("error", rloc, f"id '{rid}' does not match ^{domain}-NNN$"))
        else:
            num = int(idm.group(1))
            if num >= next_id:
                issues.append(LintIssue("error", rloc, f"id '{rid}' >= next-id ({next_id}); counter not incremented"))
        if rid in seen_ids:
            issues.append(LintIssue("error", rloc, f"duplicate id '{rid}'"))
        seen_ids.add(rid)

        # type
        ttype = rec.get("type")
        if ttype not in VALID_TYPES:
            issues.append(LintIssue("error", rloc, f"type '{ttype}' not in {VALID_TYPES}"))
            ttype = ttype if isinstance(ttype, int) else 3

        # importance
        importance = rec.get("importance")
        if importance is None:
            issues.append(LintIssue("warning", rloc, "missing 'importance'; defaulting to normal"))
            importance = "normal"
        elif importance not in IMPORTANCE_TIERS:
            issues.append(LintIssue("error", rloc, f"importance '{importance}' not in {IMPORTANCE_TIERS}"))
            importance = "normal"

        # subtype (type 3 only)
        subtype = rec.get("subtype")
        if ttype == 3:
            if subtype is None:
                issues.append(LintIssue("warning", rloc, "type 3 record missing 'subtype'"))
            elif subtype not in TYPE3_SUBTYPES:
                issues.append(LintIssue("error", rloc, f"subtype '{subtype}' not in {TYPE3_SUBTYPES}"))
        elif subtype is not None:
            issues.append(LintIssue("warning", rloc, f"subtype set on non-type-3 record (type {ttype})"))

        # target / unit — required for type 3
        target = rec.get("target")
        unit = rec.get("unit")
        if ttype == 3 and (target is None or unit is None):
            issues.append(LintIssue("warning", rloc, "type 3 record should declare target and unit"))
        if unit is not None and unit not in VALID_UNITS:
            issues.append(LintIssue("warning", rloc, f"unit '{unit}' not in {VALID_UNITS}"))

        # placement
        pl = rec.get("placement") or {}
        if not isinstance(pl, dict):
            issues.append(LintIssue("error", rloc, "placement is not a mapping"))
            pl = {}
        cls = pl.get("class", "floating")
        if cls not in PLACEMENT_CLASSES:
            issues.append(LintIssue("error", rloc, f"placement.class '{cls}' not in {PLACEMENT_CLASSES}"))
            cls = "floating"
        slots = pl.get("slots") or []
        if not isinstance(slots, list):
            issues.append(LintIssue("error", rloc, "placement.slots is not a list"))
            slots = []
        for s in slots:
            if s not in SLOT_VOCAB:
                issues.append(LintIssue("error", rloc, f"unknown slot '{s}' (controlled vocab: {SLOT_VOCAB})"))
        days_raw = pl.get("days") or []
        if not isinstance(days_raw, list):
            issues.append(LintIssue("error", rloc, "placement.days is not a list"))
            days_raw = []
        try:
            days = expand_days(days_raw)
        except ValueError as e:
            issues.append(LintIssue("error", rloc, f"placement.{e}"))
            days = []
        placement = Placement(
            cls=cls,
            slots=[s for s in slots if s in SLOT_VOCAB],
            min_block=pl.get("min-block"),
            window=pl.get("window"),
            energy=pl.get("energy"),
            days=days,
        )

        # deadline (Type 2)
        deadline = _parse_date(rec.get("deadline"), rloc, "deadline", issues)
        deadline_type = rec.get("deadline-type")
        if deadline_type is not None and deadline_type not in DEADLINE_TYPES:
            issues.append(LintIssue("error", rloc, f"deadline-type '{deadline_type}' not in {DEADLINE_TYPES}"))
            deadline_type = None

        depends_on = rec.get("depends-on") or []
        if not isinstance(depends_on, list):
            issues.append(LintIssue("error", rloc, "depends-on is not a list"))
            depends_on = []

        task = Task(
            id=str(rid),
            title=str(rec.get("title", rid)),
            type=int(ttype) if isinstance(ttype, int) else 3,
            source="tasks",
            domain=domain,
            goal=str(rec.get("goal", "") or ""),
            subtype=subtype,
            importance=importance,
            duration=rec.get("duration"),
            target=target,
            unit=unit,
            min=rec.get("min"),
            not_before=_parse_date(rec.get("not-before"), rloc, "not-before", issues),
            depends_on=[str(d) for d in depends_on],
            waiting=bool(rec.get("waiting", False)),
            placement=placement,
            deadline=deadline,
            deadline_type=deadline_type,
        )
        tasks.append(task)

    return next_id, tasks, issues


def parse_tasks_file(path: Path, domain: str) -> tuple[int, list, list]:
    """Parse a tasks.md file from disk. Missing file => empty (no error)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return 1, [], []
    return parse_tasks_text(text, domain, source_name=str(path))
