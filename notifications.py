"""T-5 notify / check-in scheduling — in-process, deterministic.

The Telegram bot already has `send_notify(block)` and `send_checkin(block)`
(originally exposed for cron on the VPS). This module computes *when* to fire
them from today's plan and (re)arms an APScheduler so they happen automatically
while the bot is running locally — no Windows Task Scheduler, no cron required.

Re-armed on every `/plan` reshuffle (so block_edits flow through) and at
startup. A daily 00:05 wake-up re-arms for the new day without manual input.

The pure helper `plan_fire_times` does the arithmetic with no APScheduler
dependency so it can be unit-tested without runtime side effects.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable

NOTIFY_LEAD_MIN = 5


def _block_dt(today: date, hhmm: str) -> datetime:
    h, m = hhmm.split(":")
    return datetime.combine(today, datetime.min.time()).replace(hour=int(h), minute=int(m))


def plan_fire_times(result, today: date, now: datetime,
                    lead_min: int = NOTIFY_LEAD_MIN
                    ) -> tuple[list[tuple[str, datetime]], list[tuple[str, datetime]]]:
    """Return (notify_jobs, checkin_jobs) for today's plan, filtered to the future.

    notify fires lead_min before each block's start (every block — including
    fixed life-rituals like meals, since the user still wants the heads-up).
    check-in fires lead_min before each end, but only for task-bearing blocks
    (no point in a 'how did Lunch go?' prompt).
    """
    notify: list[tuple[str, datetime]] = []
    checkin: list[tuple[str, datetime]] = []
    for a in result.assignments:
        b = a.block
        start_at = _block_dt(today, b["start"]) - timedelta(minutes=lead_min)
        end_at = _block_dt(today, b["end"]) - timedelta(minutes=lead_min)
        if start_at > now:
            notify.append((b["name"], start_at))
        if end_at > now and a.task is not None:
            checkin.append((b["name"], end_at))
    return notify, checkin


def goals_mode_fire_times(template_blocks: list[dict], queue_tasks: list,
                          today: date, now: datetime,
                          lead_min: int = NOTIFY_LEAD_MIN
                          ) -> list[tuple[str, datetime]]:
    """Reminders for goals mode: only fixed life-skeleton blocks + anchored
    Type 2 events for today. NO check-ins, NO per-goal reminders.

    Per the 2026-05-31 handoff: "Reminders fire ONLY for genuinely timed
    things: the fixed life-skeleton anchors already in template.yaml
    (wake/meals/etc.) and anchored events created via /add."
    """
    notify: list[tuple[str, datetime]] = []
    # Life-skeleton anchors: every slot:None template block.
    for b in template_blocks:
        if b.get("slot") is None:
            when = _block_dt(today, b["start"]) - timedelta(minutes=lead_min)
            if when > now:
                notify.append((b["name"], when))
    # Anchored Type 2 events for today (placement.cls=='fixed' + window time).
    for t in queue_tasks:
        if t.placement.cls != "fixed" or not t.placement.window:
            continue
        if t.deadline is not None and t.deadline != today:
            continue
        when = _block_dt(today, t.placement.window[0]) - timedelta(minutes=lead_min)
        if when > now:
            notify.append((t.title, when))
    return notify


def arm(scheduler, build_result_fn: Callable, root,
        send_notify_fn: Callable, send_checkin_fn: Callable,
        rearm_fn: Callable, *, today: date | None = None,
        now: datetime | None = None, lead_min: int = NOTIFY_LEAD_MIN) -> int:
    """(Re)arm today's notify/check-in jobs on the given APScheduler.

    Wipes any prior jobs in our id-namespace first (so /plan reshuffles drop
    stale jobs), then schedules from the current plan, and queues one midnight
    rearm for tomorrow. Returns the count of jobs armed.

    Branches on `plan_mode` from schedule/mode.yaml:
      blocks — T-5 notify per block + T-5 check-in per task-bearing block
      goals  — T-5 notify for life-skeleton (slot:null) blocks + Type 2
               anchored events for today; no check-ins
    """
    today = today or date.today()
    now = now or datetime.now()

    for job in list(scheduler.get_jobs()):
        if job.id.startswith(("nf:", "ci:")) or job.id == "midnight-rearm":
            scheduler.remove_job(job.id)

    # Local imports keep notifications.py free of bot-runtime deps in tests.
    from scheduler.mode import load_mode
    mode = load_mode(root)

    armed = 0
    if mode["plan_mode"] == "goals":
        from scheduler.day_template import load_day_template
        from scheduler.compile_queue import load_queue
        template, _src = load_day_template(root)
        try:
            tasks, _lint, _gen = load_queue(root)
        except (OSError, FileNotFoundError):
            tasks = []
        notify = goals_mode_fire_times(template, tasks, today, now, lead_min)
        for name, when in notify:
            scheduler.add_job(send_notify_fn, "date", run_date=when, args=[name],
                              id=f"nf:{when:%H%M}:{name[:40]}",
                              replace_existing=True)
        armed = len(notify)
    else:
        result, _state = build_result_fn(root, today)
        notify, checkin = plan_fire_times(result, today, now, lead_min)
        for name, when in notify:
            scheduler.add_job(send_notify_fn, "date", run_date=when, args=[name],
                              id=f"nf:{when:%H%M}:{name}", replace_existing=True)
        for name, when in checkin:
            scheduler.add_job(send_checkin_fn, "date", run_date=when, args=[name],
                              id=f"ci:{when:%H%M}:{name}", replace_existing=True)
        armed = len(notify) + len(checkin)

    midnight = datetime.combine(today, datetime.min.time()) + timedelta(days=1, minutes=5)
    scheduler.add_job(rearm_fn, "date", run_date=midnight, id="midnight-rearm",
                      replace_existing=True)

    return armed
