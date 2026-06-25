"""Read completion history from daily/logs/*.md.

compile() needs this for two computed fields:
  - eligibility: a depends-on id is satisfied when it appears `done` in a log.
  - urgency (cadence-debt): how long since a Type 4 domain was last completed.

Log entry format (DOMAIN-FORMAT.md §2 / utils.append_log_entry):

    ## YYYY-MM-DD

    - **duration:** 60 min
    - **covered:** ...
    - **outcome:** done
    - **task:** career-003
    - **domain:** career        # optional, future-proofing

The file is named daily/logs/YYYY-MM-DD.md; that filename date is the canonical
completion date (inner `## DATE` headers vary and are not trusted for dating).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

_FILE_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\.md$")
_HEADER_RE = re.compile(r"^##\s+")
_FIELD_RE = re.compile(r"^- \*\*([\w-]+):\*\*\s*(.*)$")


@dataclass
class LogEntry:
    date: date
    task_id: Optional[str] = None
    outcome: Optional[str] = None
    domain: Optional[str] = None
    # Quantitative amount of work logged, when recorded. `duration` is normalized
    # to minutes (unit "minutes"); an explicit `amount:`/`unit:` pair is taken as
    # written. None when the entry carries no structured amount. (L0 — progress
    # metrics; older entries and freeform /log entries leave these None.)
    amount: Optional[float] = None
    unit: Optional[str] = None


def _parse_duration_minutes(s: str) -> Optional[float]:
    """Best-effort minutes from a `duration:` value: '60 min', '90', '1.5 h'."""
    s = s.strip().lower()
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    n = float(m.group(1))
    # treat an hours marker (and no minutes marker) as hours
    if ("h" in s) and ("min" not in s):
        return n * 60
    return n


def _amount_unit(d: dict) -> tuple:
    """Derive (amount, unit) from a parsed entry's fields. Structured `amount:`
    wins; otherwise normalize `duration:` to minutes. Returns (None, None) when
    no quantitative value is present."""
    if d.get("amount"):
        try:
            return float(d["amount"]), (d.get("unit") or None)
        except (TypeError, ValueError):
            return None, (d.get("unit") or None)
    if d.get("duration"):
        mins = _parse_duration_minutes(d["duration"])
        if mins is not None:
            return mins, "minutes"
    return None, None


def _domain_of(entry: LogEntry) -> Optional[str]:
    if entry.domain:
        return entry.domain
    if entry.task_id and "-" in entry.task_id:
        return entry.task_id.rsplit("-", 1)[0]
    return None


def parse_log_text(text: str, file_date: date) -> list:
    """Extract completion entries from one daily log file."""
    entries: list = []
    current: Optional[dict] = None

    def flush():
        if current and (current.get("task") or current.get("outcome")):
            amount, unit = _amount_unit(current)
            entries.append(LogEntry(
                date=file_date,
                task_id=current.get("task"),
                outcome=current.get("outcome"),
                domain=current.get("domain"),
                amount=amount,
                unit=unit,
            ))

    for line in text.splitlines():
        if _HEADER_RE.match(line):
            flush()
            current = {}
            continue
        m = _FIELD_RE.match(line)
        if m and current is not None:
            key, val = m.group(1).strip().lower(), m.group(2).strip()
            if key in ("task", "outcome", "domain", "duration", "amount", "unit"):
                current[key] = val or None
    flush()
    return entries


def read_log_entries(root: Path) -> list:
    """Parse every daily/logs/YYYY-MM-DD.md under root. Sorted by date."""
    logs_dir = root / "daily" / "logs"
    if not logs_dir.is_dir():
        return []
    out: list = []
    for path in sorted(logs_dir.glob("*.md")):
        m = _FILE_DATE_RE.search(path.name)
        if not m:
            continue
        fdate = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        out.extend(parse_log_text(path.read_text(encoding="utf-8"), fdate))
    out.sort(key=lambda e: e.date)
    return out


# --- Query helpers ---------------------------------------------------------

def done_task_ids(entries: list) -> set:
    """Ids that appear with outcome 'done' (dependency satisfaction)."""
    return {e.task_id for e in entries if e.task_id and e.outcome == "done"}


def last_completion_for_task(entries: list, task_id: str) -> Optional[date]:
    dates = [e.date for e in entries if e.task_id == task_id and e.outcome in ("done", "partial")]
    return max(dates) if dates else None


def last_completion_for_domain(entries: list, domain: str) -> Optional[date]:
    dates = [e.date for e in entries
             if _domain_of(e) == domain and e.outcome in ("done", "partial")]
    return max(dates) if dates else None


def completions_this_week(entries: list, domain: str, today: date) -> int:
    """Count done/partial completions for a domain in the current ISO week."""
    monday = today - timedelta(days=today.weekday())
    return sum(
        1 for e in entries
        if _domain_of(e) == domain
        and e.outcome in ("done", "partial")
        and monday <= e.date <= today
    )
