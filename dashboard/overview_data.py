"""Overview payload — computed ONCE, rendered by two surfaces.

The server-rendered `/overview` page and the JSON `GET /api/overview` both call
`build_overview()`, so the Jinja hub and the React client (life-os-web) cannot
drift. Requested as BR-1/BR-2 in life-os-web/BACKEND-REQUESTS.md, which asked
precisely for this shared-helper shape.

Everything here is READ-ONLY derivation over the data tree plus the umbrella
overlay. No scheduling decisions are made or reinterpreted: row `state`,
`cadence` and the completion counts are reported as the deterministic core and
the walkthrough tracker already recorded them.
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path

import yaml

from dashboard.groups import load_umbrellas
from metrics.aggregate import series
from scheduler.compile_queue import load_queue
from scheduler.domains import list_domains, read_thresholds
from scheduler.logs import read_log_entries
from scheduler.mode import load_mode

BASE = Path(__file__).resolve().parent

SPARK_DAYS = 21
SYNC_STALE_SECONDS = 1200

# populated → started → untouched, then name (the order the page shows).
_STATE_ORDER = {"populated": 0, "started": 1, "untouched": 2}


def sync_heartbeat_path() -> Path:
    """Where sync-data-tree.sh records its last fully-successful cycle."""
    return Path.home() / ".cache" / "life-os" / "last-sync"


def sync_age_seconds():
    """Seconds since the data-tree sync last succeeded, or None if unknown."""
    try:
        last = int(sync_heartbeat_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return max(0, int(time.time()) - last)


def read_rev() -> str:
    """Best-effort short git SHA of the running checkout."""
    try:
        head = BASE.parent / ".git" / "HEAD"
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref: "):
            return (BASE.parent / ".git" / ref[5:]).read_text(encoding="utf-8").strip()[:8]
        return ref[:8]
    except OSError:
        return "unknown"


def age_label(sec) -> str:
    if sec is None:
        return "unknown"
    if sec < 90:
        return f"{sec}s ago"
    if sec < 5400:
        return f"{sec // 60} min ago"
    return f"{sec // 3600}h ago"


def walkthrough_status(root: Path) -> dict:
    """domain -> 'populated' | 'started' from dev/walkthrough-state.yaml."""
    try:
        data = yaml.safe_load(
            (root / "dev" / "walkthrough-state.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    out = {}
    for dom, rec in (data or {}).items():
        if not isinstance(rec, dict):
            continue
        status = str(rec.get("status", ""))
        done = rec.get("scopes_done") or []
        out[dom] = "populated" if status.upper().startswith("POPULATED") or len(done) >= 5 \
            else "started"
    return out


def logging_streak(entries, today: date) -> int:
    """Consecutive days up to `today` with any done/partial completion."""
    logged = {e.date for e in entries if e.outcome in ("done", "partial")}
    streak, probe = 0, today
    while probe in logged:
        streak += 1
        probe -= timedelta(days=1)
    return streak


def build_overview(root: Path, today: date | None = None,
                   spark_days: int = SPARK_DAYS) -> dict:
    """The whole Overview payload: pulse + umbrellas + ordered domain rows.

    Pure derivation, parameterized on `today` so it is testable without freezing
    the clock. `rows` arrive in DISPLAY order — the client must not re-sort.
    """
    today = today or date.today()
    entries = read_log_entries(root)
    th = read_thresholds(root)
    walk = walkthrough_status(root)
    umbrella_of = {d: u["key"] for u in load_umbrellas(root)
                   for d in (u["domains"] or [])}

    rows = []
    for d in list_domains(root):
        ser = series(entries, d, today - timedelta(days=spark_days - 1), today, "day")
        counts = [p["completions"] for p in ser["points"]]
        cfg = th.get(d, {})
        rows.append({
            "domain": d,
            "umbrella": umbrella_of.get(d),      # key, not label; None = ungrouped
            "state": walk.get(d, "untouched"),
            "cadence": cfg.get("cadence"),
            "spark": counts,
            "recent": sum(counts[-7:]),
        })
    rows.sort(key=lambda r: (_STATE_ORDER[r["state"]], r["domain"]))

    try:
        _tasks, lint, _generated = load_queue(root)
    except OSError:
        lint = []
    age = sync_age_seconds()
    return {
        "date": today.isoformat(),
        "spark_days": spark_days,
        "pulse": {
            "populated": sum(1 for r in rows if r["state"] == "populated"),
            "total": len(rows),
            "plan_mode": load_mode(root)["plan_mode"],
            "streak": logging_streak(entries, today),
            "lint_err": sum(1 for i in lint if i.level == "error"),
            "lint_warn": sum(1 for i in lint if i.level == "warning"),
            "sync_age_seconds": age,
            "sync_ok": age is not None and age <= SYNC_STALE_SECONDS,
            "rev": read_rev(),
        },
        "umbrellas": [{"key": u["key"], "label": u["label"],
                       "domains": list(u["domains"] or [])}
                      for u in load_umbrellas(root)],
        "rows": rows,
    }
