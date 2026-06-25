"""Progress metrics — deterministic aggregation over the daily-log event stream.

Pure, unit-aware functions turn a list of ``LogEntry`` (from
``scheduler.logs.read_log_entries``) into per-domain progress: time series,
totals, streaks, and cadence adherence. These power three surfaces from one
computation — hub charts, the REST ``/api/metrics`` endpoints, and the MCP
server — so the math lives here once.

No AI, no scheduling decisions: this only *measures* logged behavior.

The core functions take an entry list + explicit params (fully testable). The
``domain_progress`` / ``all_domains_summary`` convenience wrappers read the log
and ``thresholds.yaml`` from a root path for the callers.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import yaml

from scheduler.logs import _domain_of, read_log_entries

COMPLETED = ("done", "partial")


# --- bucketing helpers -----------------------------------------------------

def _bucket_key(d: date, bucket: str) -> date:
    """Day bucket → the date itself; week bucket → that week's Monday."""
    if bucket == "week":
        return d - timedelta(days=d.weekday())
    return d


def _iter_buckets(start: date, end: date, bucket: str):
    """Yield each contiguous bucket key from start..end inclusive."""
    if bucket == "week":
        cur, step = _bucket_key(start, "week"), timedelta(days=7)
    else:
        cur, step = start, timedelta(days=1)
    while cur <= end:
        yield cur
        cur += step


def _domain_entries(entries: list, domain: str) -> list:
    return [e for e in entries if _domain_of(e) == domain]


def _sole_unit(entries: list) -> Optional[str]:
    units = {e.unit for e in entries if e.unit}
    return units.pop() if len(units) == 1 else None


# --- core (pure) metrics ---------------------------------------------------

def totals(entries: list, domain: str, start: date, end: date) -> dict:
    """Summed amount + completion count for a domain over [start, end]."""
    es = [e for e in _domain_entries(entries, domain) if start <= e.date <= end]
    has_amount = any(e.amount is not None for e in es)
    return {
        "amount": round(sum(e.amount for e in es if e.amount is not None), 2)
        if has_amount else None,
        "unit": _sole_unit(es),
        "completions": sum(1 for e in es if e.outcome in COMPLETED),
        "entries": len(es),
    }


def series(entries: list, domain: str, start: date, end: date,
           bucket: str = "day") -> dict:
    """Time-bucketed amount + completions, with contiguous (zero-filled) buckets."""
    es = [e for e in _domain_entries(entries, domain) if start <= e.date <= end]
    acc: dict = {}
    for e in es:
        key = _bucket_key(e.date, bucket)
        b = acc.setdefault(key, {"amount": 0.0, "completions": 0, "has_amount": False})
        if e.amount is not None:
            b["amount"] += e.amount
            b["has_amount"] = True
        if e.outcome in COMPLETED:
            b["completions"] += 1
    points = []
    for key in _iter_buckets(start, end, bucket):
        b = acc.get(key)
        points.append({
            "date": key.isoformat(),
            "amount": round(b["amount"], 2) if (b and b["has_amount"]) else None,
            "completions": b["completions"] if b else 0,
        })
    return {"bucket": bucket, "unit": _sole_unit(es), "points": points}


def streak(entries: list, domain: str, today: date,
           cadence: Optional[str]) -> Optional[int]:
    """Consecutive cadence periods up to `today` with a completion.

    daily → consecutive days; weekly → consecutive ISO weeks; otherwise None
    (streak isn't meaningful for as-scheduled / unconfigured cadence)."""
    done_dates = {e.date for e in _domain_entries(entries, domain)
                  if e.outcome in COMPLETED}
    if cadence == "daily":
        n, d = 0, today
        while d in done_dates:
            n, d = n + 1, d - timedelta(days=1)
        return n
    if cadence == "weekly":
        done_weeks = {_bucket_key(d, "week") for d in done_dates}
        n, wk = 0, _bucket_key(today, "week")
        while wk in done_weeks:
            n, wk = n + 1, wk - timedelta(days=7)
        return n
    return None


def adherence(entries: list, domain: str, start: date, end: date,
              cadence: Optional[str]) -> Optional[float]:
    """completions ÷ cadence-expected over [start, end]. None for as-scheduled.

    Can exceed 1.0 (over-cadence is informative, not an error)."""
    completions = sum(
        1 for e in _domain_entries(entries, domain)
        if start <= e.date <= end and e.outcome in COMPLETED
    )
    if cadence == "daily":
        expected = (end - start).days + 1
    elif cadence == "weekly":
        expected = sum(1 for _ in _iter_buckets(start, end, "week"))
    else:
        return None
    return round(completions / expected, 3) if expected > 0 else None


# --- convenience wrappers (read log + thresholds from a root) ---------------

def _thresholds(root) -> dict:
    try:
        return yaml.safe_load((Path(root) / "thresholds.yaml").read_text(
            encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def domain_progress(root, domain: str, days: int = 30, bucket: str = "day",
                    today: Optional[date] = None) -> dict:
    """Full progress payload for one domain — the REST/MCP unit of recall."""
    today = today or date.today()
    start = today - timedelta(days=days - 1)
    entries = read_log_entries(Path(root))
    cfg = _thresholds(root).get(domain, {})
    cadence = cfg.get("cadence")
    ser = series(entries, domain, start, today, bucket)
    unit = ser["unit"] or cfg.get("unit")
    return {
        "domain": domain,
        "range": {"start": start.isoformat(), "end": today.isoformat(), "days": days},
        "cadence": cadence,
        "unit": unit,
        "totals": totals(entries, domain, start, today),
        "streak": streak(entries, domain, today, cadence),
        "adherence": adherence(entries, domain, start, today, cadence),
        "series": ser["points"],
    }


def all_domains_summary(root, days: int = 30,
                        today: Optional[date] = None) -> list:
    """Per-domain summary (no full series) — the metrics index."""
    today = today or date.today()
    start = today - timedelta(days=days - 1)
    entries = read_log_entries(Path(root))
    th = _thresholds(root)
    names = {k for k in th if k != "config"}
    names |= {_domain_of(e) for e in entries if _domain_of(e)}
    out = []
    for domain in sorted(n for n in names if n):
        cfg = th.get(domain, {})
        cadence = cfg.get("cadence")
        t = totals(entries, domain, start, today)
        out.append({
            "domain": domain,
            "cadence": cadence,
            "unit": t["unit"] or cfg.get("unit"),
            "totals": t,
            "streak": streak(entries, domain, today, cadence),
            "adherence": adherence(entries, domain, start, today, cadence),
        })
    return out
