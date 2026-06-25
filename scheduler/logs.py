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
    # Quantitative amount of work logged, parsed from the canonical `duration:`
    # field (DOMAIN-FORMAT.md §2: "X min | X words | X pages | X sessions"). The
    # unit is read from the value; hours/minutes normalize to "minutes". None
    # when the entry records no amount (older / freeform entries). (L0 — metrics.)
    amount: Optional[float] = None
    unit: Optional[str] = None


# Unit vocabulary accepted inside a `duration:` value → canonical unit name.
_UNIT_WORDS = {
    "min": "minutes", "mins": "minutes", "minute": "minutes",
    "minutes": "minutes", "m": "minutes",
    "h": "hours", "hr": "hours", "hrs": "hours", "hour": "hours", "hours": "hours",
    "word": "words", "words": "words", "w": "words",
    "page": "pages", "pages": "pages", "p": "pages",
    "session": "sessions", "sessions": "sessions", "sess": "sessions",
}


def _parse_amount(value: str) -> tuple:
    """Parse a `duration:` value into (amount, unit).

    Reads the unit word from the value — '60 min'→(60,'minutes'),
    '500 words'→(500,'words'), '1.5 h'→(90,'minutes'), '3 pages'→(3,'pages').
    A bare number yields (n, None) (unit unknown from the entry alone). Returns
    (None, None) when no leading number is found.
    """
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]+)?", value.strip())
    if not m:
        return None, None
    n = float(m.group(1))
    word = (m.group(2) or "").lower()
    unit = _UNIT_WORDS.get(word) if word else None
    if unit == "hours":
        return n * 60, "minutes"
    return n, unit


def domain_of(entry: LogEntry) -> Optional[str]:
    """Resolve a log entry's domain — explicit `domain:`, else the task-id prefix."""
    if entry.domain:
        return entry.domain
    if entry.task_id and "-" in entry.task_id:
        return entry.task_id.rsplit("-", 1)[0]
    return None


_domain_of = domain_of   # internal alias (kept for existing call sites)


def parse_log_text(text: str, file_date: date) -> list:
    """Extract completion entries from one daily log file."""
    entries: list = []
    current: Optional[dict] = None

    def flush():
        if current and (current.get("task") or current.get("outcome")):
            amount, unit = (_parse_amount(current["duration"])
                            if current.get("duration") else (None, None))
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
            if key in ("task", "outcome", "domain", "duration"):
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
