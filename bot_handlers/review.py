"""Messy-review capture — tailored prompt out, raw brain-dump in, append-only.

First module of the bot package split (architecture-review Tier-1C; spec in
skills-era.md §B.8). The bot sends an evening (daily) and Sunday (weekly)
review prompt whose considerations are DETERMINISTICALLY rendered from the
day's actual data — no AI at capture time. The user's freeform replies are
appended verbatim to ``daily/reviews/YYYY-MM-DD.md`` (append-only, timestamped
stanzas, born on the fileio layer). The daily/weekly review SKILLS drain and
integrate them later, with the user in the loop.

Capture must never block: if rendering the considerations fails for any
reason, a generic prompt is sent instead.

Layering: pure/deterministic functions up top (unit-tested); thin
telegram-facing factories at the bottom (bot.py injects its own auth/root
helpers, so this module never imports from bot.py).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

from scheduler.fileio import file_lock

logger = logging.getLogger(__name__)

# Prompt times — adjust here. The daily prompt aligns with the evening
# wind-down; the weekly fires Sunday afternoon.
REVIEW_DAILY_TIME = "21:00"
REVIEW_WEEKLY_TIME = "17:00"
REVIEW_WEEKLY_WEEKDAY = 6          # Sunday (date.weekday())

_FALLBACK_PROMPT = (
    "🌙 Evening review — how did today actually go?\n"
    "Reply to this message (or use /review <text>) with a messy brain-dump: "
    "what happened, what didn't, anything for tomorrow. It all gets captured."
)


# --- pure: when to fire ------------------------------------------------------

def _at(today: date, hhmm: str) -> datetime:
    h, m = hhmm.split(":")
    return datetime.combine(today, datetime.min.time()).replace(hour=int(h), minute=int(m))


def review_fire_times(today: date, now: datetime) -> list:
    """[(kind, datetime)] for today's review prompts, filtered to the future."""
    jobs = []
    daily = _at(today, REVIEW_DAILY_TIME)
    if daily > now:
        jobs.append(("daily", daily))
    if today.weekday() == REVIEW_WEEKLY_WEEKDAY:
        weekly = _at(today, REVIEW_WEEKLY_TIME)
        if weekly > now:
            jobs.append(("weekly", weekly))
    return jobs


# --- pure: what to say -------------------------------------------------------

def render_review_prompt(root, today: date | None = None,
                         weekly: bool = False) -> str:
    """Deterministic prompt with today's considerations. Never raises."""
    today = today or date.today()
    try:
        return _render(Path(root), today, weekly)
    except Exception as e:           # capture must never block on rendering
        logger.warning("review prompt rendering failed (%s); using fallback", e)
        return _FALLBACK_PROMPT


def _render(root: Path, today: date, weekly: bool) -> str:
    from scheduler.compile_queue import load_queue
    from scheduler.goals import split_goals
    from scheduler.logs import domain_of, read_log_entries
    from scheduler.mode import load_mode

    lines = [f"🌙 Evening review — {today.isoformat()}", ""]

    # What today was supposed to be (mode-aware).
    mode = load_mode(root)
    if mode["plan_mode"] == "goals":
        tasks, _lint, _gen = load_queue(root)
        anchors, live, _waiting, _blocked = split_goals(tasks, today)
        if live:
            lines.append("Today's live goals were:")
            for t in live[:8]:
                lines.append(f"  • {t.domain or '—'}: {t.title}")
            if len(live) > 8:
                lines.append(f"  … and {len(live) - 8} more")
        if anchors:
            lines.append("Anchors: " + "; ".join(t.title for t in anchors))
    else:
        from scheduler.day import build_result
        result, _state = build_result(root, today)
        placed = [a for a in result.assignments if a.task]
        if placed:
            lines.append("Today's scheduled tasks were:")
            for a in placed[:8]:
                lines.append(f"  • {a.block['start']} {a.task.title}")
        if result.carried:
            lines.append(f"Carried forward: {len(result.carried)} task(s)")

    # What actually got logged.
    entries = [e for e in read_log_entries(root) if e.date == today]
    if entries:
        done = sum(1 for e in entries if e.outcome == "done")
        partial = sum(1 for e in entries if e.outcome == "partial")
        domains = sorted({d for d in (domain_of(e) for e in entries) if d})
        lines.append(f"Logged today: {len(entries)} entr"
                     f"{'y' if len(entries) == 1 else 'ies'} — "
                     f"{done} done, {partial} partial"
                     + (f" ({', '.join(domains)})" if domains else ""))
    else:
        lines.append("Nothing logged yet today.")

    # Weekly: the week in numbers, from the metrics layer.
    if weekly:
        from metrics.aggregate import all_domains_summary
        lines += ["", f"📅 Week in numbers (through {today.isoformat()}):"]
        for row in all_domains_summary(root, days=7, today=today):
            c = row["totals"]["completions"]
            if c == 0 and row["streak"] in (None, 0):
                continue
            streak = f", streak {row['streak']}" if row["streak"] else ""
            lines.append(f"  • {row['domain']}: {c} completion(s){streak}")

    lines += [
        "",
        "Reply to this message (or /review <text>) with a messy brain-dump:",
        "what happened, what didn't, how it felt, anything for tomorrow.",
        "Multiple messages are fine — it all gets captured for the next review.",
    ]
    return "\n".join(lines)


# --- pure: where it lands ----------------------------------------------------

_FILE_HEADER = """\
<!-- APPEND-ONLY review capture. Raw, messy, timestamped stanzas from the
     Telegram /review flow. Machines only append here; the daily/weekly
     review skills drain + integrate stanzas with the user in the loop. -->
# Reviews — {date}

"""


def append_review(root, text: str, kind: str = "daily",
                  now: datetime | None = None) -> Path:
    """Append one raw stanza to today's review file. Returns the path."""
    now = now or datetime.now()
    path = Path(root) / "daily" / "reviews" / f"{now:%Y-%m-%d}.md"
    stanza = f"## {now:%H:%M} · {kind}\n\n{text.strip()}\n\n"
    with file_lock(path):            # header-check + append must be one unit
        is_new = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as f:
            if is_new:
                f.write(_FILE_HEADER.format(date=f"{now:%Y-%m-%d}"))
            f.write(stanza)
            f.flush()
            import os
            os.fsync(f.fileno())
    return path


# --- telegram-facing factories (thin; bot.py injects its helpers) ------------

# message_id -> kind, for routing bare replies to the right capture kind.
# Single-process bot; survives until restart, which is fine — /review always works.
PROMPT_IDS: dict = {}


def build_send_review_prompt(get_token, get_chat_id, root_fn):
    """APScheduler job coroutine: send the (daily|weekly) prompt."""
    async def send_review_prompt(kind: str) -> None:
        from telegram import Bot
        text = render_review_prompt(root_fn(), weekly=(kind == "weekly"))
        bot = Bot(token=get_token())
        async with bot:
            msg = await bot.send_message(chat_id=get_chat_id(), text=text)
        PROMPT_IDS[msg.message_id] = kind
    return send_review_prompt


def build_cmd_review(is_authorized, root_fn):
    """/review <text> — capture a stanza directly."""
    async def cmd_review(update, context) -> None:
        if not is_authorized(update):
            return
        text = " ".join(context.args or [])
        if not text:
            await update.message.reply_text(
                "Usage: /review <anything, as messy as you like>\n"
                "Or just reply to an evening/weekly review prompt.")
            return
        path = append_review(root_fn(), text, kind="daily")
        await update.message.reply_text(f"🗒 Captured → {path.name}")
    return cmd_review


def build_review_reply_capture(is_authorized, root_fn):
    """MessageHandler callback: replies to a review prompt become stanzas."""
    async def review_reply_capture(update, context) -> None:
        if not is_authorized(update):
            return
        msg = update.message
        if not msg or not msg.reply_to_message or not msg.text:
            return
        kind = PROMPT_IDS.get(msg.reply_to_message.message_id)
        if kind is None:
            return                    # a reply to something else — not ours
        append_review(root_fn(), msg.text, kind=kind)
        await msg.reply_text("🗒 Captured. Keep going if there's more.")
    return review_reply_capture
