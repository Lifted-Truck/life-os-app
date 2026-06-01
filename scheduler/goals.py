"""Goals-mode output — flat, untimed goal list for the logging experiment.

Replaces the timed block schedule with a goals-only view: which domains are
live today, plus any anchored (Type 2) events with their times. The
deterministic core picks WHICH goals are live (eligibility / cadence-debt /
days), WHEN reminders fire (anchored events + life-skeleton blocks), and
the canonical ordering. An optional Haiku pass in bot.py phrases the
rendered text — it does not change selection or order.
"""
from __future__ import annotations

from datetime import date


def _is_anchored_today(t, today: date) -> bool:
    """Type 2 / fixed-class anchor scheduled for today.

    A `deadline` is the event's date; when present, it must equal today.
    Type 2 fixed anchors without an explicit deadline (legacy schedule/
    entries) are treated as today's anchor.
    """
    if t.placement.cls != "fixed" or not t.placement.window:
        return False
    if t.deadline is not None:
        return t.deadline == today
    return t.type == 2


def _anchor_time(t) -> str:
    if t.placement.window:
        return t.placement.window[0]
    return ""


def split_goals(tasks, today: date) -> tuple[list, list, list, list]:
    """Partition the queue.yaml tasks into the four goals-output buckets.

    Returns (anchors, live_by_domain_order, waiting, blocked).
    * anchors  — Type 2 fixed anchors for today, sorted by clock time.
    * live     — eligible, not-waiting, not-anchored goals, sorted by
                 (descending urgency, importance tier, title).
    * waiting  — `waiting: true` tasks (explicitly parked).
    * blocked  — ineligible non-waiting tasks (deps not met, off-day, etc.).
    """
    importance_rank = {"critical": 0, "high": 1, "normal": 2, "low": 3}
    anchors: list = []
    live: list = []
    waiting: list = []
    blocked: list = []
    for t in tasks:
        if _is_anchored_today(t, today):
            anchors.append(t)
        elif t.waiting:
            waiting.append(t)
        elif not t.eligible:
            blocked.append(t)
        else:
            live.append(t)
    anchors.sort(key=lambda t: _anchor_time(t))
    live.sort(key=lambda t: (
        -t.urgency,
        importance_rank.get(t.importance, 9),
        t.title.lower(),
    ))
    waiting.sort(key=lambda t: t.title.lower())
    blocked.sort(key=lambda t: t.title.lower())
    return anchors, live, waiting, blocked


def render_goals_text(tasks, today: date) -> str:
    """Plain-text goals output for /plan (Telegram). No Markdown."""
    anchors, live, waiting, blocked = split_goals(tasks, today)
    lines: list[str] = [f"🎯 Today's goals — {today.isoformat()}", ""]

    if anchors:
        lines.append("Anchors:")
        for t in anchors:
            when = _anchor_time(t) or "—"
            lines.append(f"  • {when}  {t.title}")
        lines.append("")

    if live:
        lines.append("Live today:")
        # Group by domain in the order they first appear (already urgency-sorted)
        seen_domains: list[str] = []
        by_domain: dict[str, list] = {}
        for t in live:
            d = t.domain or "—"
            if d not in by_domain:
                by_domain[d] = []
                seen_domains.append(d)
            by_domain[d].append(t)
        for d in seen_domains:
            lines.append(f"  {d}:")
            for t in by_domain[d]:
                lines.append(f"    • {t.title}")
        lines.append("")
    else:
        lines.append("Live today: (nothing eligible — fresh day)")
        lines.append("")

    if waiting:
        lines.append("Waiting:")
        for t in waiting:
            lines.append(f"  • {t.title}")
        lines.append("")

    if blocked:
        lines.append("Blocked:")
        for t in blocked:
            reason = t.blocked_reason or "ineligible"
            lines.append(f"  • {t.title} — {reason}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_goals_readme_body(tasks, today: date) -> str:
    """Markdown body for daily/README.md when plan_mode = goals."""
    anchors, live, waiting, blocked = split_goals(tasks, today)
    lines: list[str] = []

    lines.append("## Today's Goals (untimed)")
    lines.append("")
    if live:
        # Group by domain
        seen: list[str] = []
        groups: dict[str, list] = {}
        for t in live:
            d = t.domain or "—"
            if d not in groups:
                groups[d] = []
                seen.append(d)
            groups[d].append(t)
        for d in seen:
            lines.append(f"### {d}")
            for t in groups[d]:
                lines.append(f"- {t.title}")
            lines.append("")
    else:
        lines.append("_Nothing eligible today — fresh day._")
        lines.append("")

    lines.append("## Today's Anchors")
    lines.append("")
    if anchors:
        lines.append("| Time | Event |")
        lines.append("|------|-------|")
        for t in anchors:
            when = _anchor_time(t) or "—"
            lines.append(f"| {when} | {t.title} |")
    else:
        lines.append("None scheduled.")
    lines.append("")

    if waiting:
        lines.append("## Waiting")
        lines.append("")
        for t in waiting:
            lines.append(f"- {t.title}")
        lines.append("")

    if blocked:
        lines.append("## Blocked")
        lines.append("")
        for t in blocked:
            reason = t.blocked_reason or "ineligible"
            lines.append(f"- {t.title} — {reason}")
        lines.append("")

    return "\n".join(lines)
