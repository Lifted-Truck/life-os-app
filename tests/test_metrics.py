"""Progress-metrics aggregation — pure functions + tree-reading wrappers."""
from datetime import date, timedelta

from scheduler.logs import LogEntry
from metrics.aggregate import (
    adherence,
    all_domains_summary,
    domain_progress,
    series,
    streak,
    totals,
)

T = date(2026, 6, 18)   # a Thursday
DAY = timedelta(days=1)


def E(d, domain=None, outcome="done", amount=None, unit=None, task_id=None):
    return LogEntry(date=d, domain=domain, outcome=outcome,
                    amount=amount, unit=unit, task_id=task_id)


# --- pure functions --------------------------------------------------------

def test_totals_sums_amount_and_infers_unit():
    es = [E(T, "music-practice", amount=30, unit="minutes"),
          E(T - DAY, "music-practice", amount=20, unit="minutes"),
          E(T, "novel", amount=500, unit="words")]
    t = totals(es, "music-practice", T - 7 * DAY, T)
    assert t["amount"] == 50 and t["unit"] == "minutes"
    assert t["completions"] == 2 and t["entries"] == 2


def test_totals_amount_none_when_unrecorded():
    t = totals([E(T, "fitness", amount=None)], "fitness", T - DAY, T)
    assert t["amount"] is None and t["completions"] == 1


def test_series_day_buckets_zero_filled():
    s = series([E(T, "x", amount=30, unit="minutes")], "x", T - 2 * DAY, T, "day")
    assert len(s["points"]) == 3
    assert s["points"][0]["amount"] is None      # two days ago, no entry
    assert s["points"][-1]["amount"] == 30        # today
    assert s["unit"] == "minutes"


def test_series_week_bucket_groups_same_week():
    es = [E(T, "x", amount=1, unit="sessions"), E(T - DAY, "x", amount=1, unit="sessions")]
    s = series(es, "x", T - DAY, T, "week")
    assert len(s["points"]) == 1 and s["points"][0]["amount"] == 2


def test_streak_daily_counts_consecutive():
    es = [E(T, "x"), E(T - DAY, "x"), E(T - 2 * DAY, "x")]
    assert streak(es, "x", T, "daily") == 3
    assert streak([E(T, "x"), E(T - 2 * DAY, "x")], "x", T, "daily") == 1   # gap


def test_streak_weekly_and_none_for_as_scheduled():
    assert streak([E(T, "x")], "x", T, "weekly") == 1
    assert streak([E(T, "x")], "x", T, "as-scheduled") is None


def test_adherence_daily_ratio():
    a = adherence([E(T, "x"), E(T - DAY, "x")], "x", T - 3 * DAY, T, "daily")
    assert a == 0.5                                # 2 completions / 4 days
    assert adherence([E(T, "x")], "x", T - 3 * DAY, T, "as-scheduled") is None


def test_domain_resolved_from_task_id_prefix():
    e = E(T, domain=None, task_id="music-practice-003", amount=15, unit="minutes")
    t = totals([e], "music-practice", T - DAY, T)
    assert t["completions"] == 1 and t["amount"] == 15


# --- tree-reading wrappers (use the conftest fixture) ----------------------

def _log(root, body):
    (root / "daily" / "logs" / f"{T.isoformat()}.md").write_text(
        f"## {T.isoformat()}\n\n{body}\n", encoding="utf-8")


def test_domain_progress_reads_tree(life_os):
    _log(life_os, "- **duration:** 30 min\n- **outcome:** done\n"
                  "- **domain:** music-practice")
    p = domain_progress(life_os, "music-practice", days=7, today=T)
    assert p["cadence"] == "daily" and p["unit"] == "minutes"
    assert p["totals"]["amount"] == 30 and p["totals"]["completions"] == 1
    assert p["streak"] == 1
    assert len(p["series"]) == 7 and p["series"][-1]["amount"] == 30


def test_all_domains_summary_includes_logless_domains(life_os):
    _log(life_os, "- **duration:** 30 min\n- **outcome:** done\n"
                  "- **domain:** music-practice")
    rows = all_domains_summary(life_os, days=7, today=T)
    mp = next(r for r in rows if r["domain"] == "music-practice")
    assert mp["totals"]["completions"] == 1 and mp["cadence"] == "daily"
    assert any(r["domain"] == "novel" for r in rows)   # from thresholds, no logs
