import argparse
import asyncio
import logging
import os
import sys
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from utils import (
    append_inbox,
    append_log_entry,
    get_life_os_root,
    read_file,
    read_thresholds,
    update_threshold,
    write_ingest_note,
)
from scheduler.day import (
    build_result,
    load_state,
    reshuffle_and_write,
    save_state,
    task_in_block,
)

load_dotenv(Path(__file__).parent / ".env", override=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
# httpx logs full request URLs at INFO, which include the bot token in the
# path (.../bot<TOKEN>/getUpdates). Keep that out of the logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"


def get_chat_id() -> int:
    return int(os.getenv("TELEGRAM_CHAT_ID"))


def is_authorized(update: Update) -> bool:
    return update.effective_chat.id == get_chat_id()


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    await update.message.reply_text("Life OS bot is running.")


async def cmd_evening(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return

    brief = " ".join(context.args) if context.args else ""
    if not brief:
        await update.message.reply_text(
            "Usage: /evening <brief description of your evening>"
        )
        return

    await update.message.reply_text("Synthesizing evening summary...")

    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        message = client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=(
                "You are a personal log assistant. Given a brief description of "
                "someone's evening, synthesize it into a concise log entry summary. "
                "Return only 1-3 sentences suitable for a 'covered' field in a "
                "personal log. Be factual and specific."
            ),
            messages=[{"role": "user", "content": brief}],
        )
        summary = message.content[0].text
    except Exception as e:
        logger.error("Evening API call failed: %s", e)
        await update.message.reply_text(f"Error generating summary: {e}")
        return

    append_log_entry({
        "date": date.today().isoformat(),
        "covered": summary,
        "outcome": "done",
        "notes": f"Raw brief: {brief}",
    })

    await update.message.reply_text(f"✅ Logged:\n\n{summary}")


# ---------------------------------------------------------------------------
# /domain command
# ---------------------------------------------------------------------------

async def cmd_domain(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    args = context.args or []
    if not args or args[0] == "list":
        domains = list(read_thresholds().keys())
        await update.message.reply_text("Domains:\n" + "\n".join(f"  • {d}" for d in domains))
    else:
        await update.message.reply_text("Usage: /domain list")


# ---------------------------------------------------------------------------
# /note command
# ---------------------------------------------------------------------------

def _extract_domain(words: list[str], known_domains: set[str]) -> tuple[str, str]:
    """Return (domain_tag, body). Extracts first word as domain if it matches."""
    if words and words[0].lower() in known_domains:
        return words[0].lower(), " ".join(words[1:])
    return "", " ".join(words)


async def _haiku_structure_note(text: str, known_domains: set[str]) -> tuple[str, str]:
    """Call Haiku to extract domain and clean body from freeform text."""
    domain_list = ", ".join(sorted(known_domains))
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model=MODEL,
        max_tokens=256,
        system=(
            f"You are a note-routing assistant. Given a freeform note, extract:\n"
            f"1. domain: the most relevant domain from this list, or blank if unclear: {domain_list}\n"
            f"2. body: the note content, cleaned up but faithful to the original\n\n"
            f"Return exactly two lines:\n"
            f"domain: [value or blank]\n"
            f"body: [note content]"
        ),
        messages=[{"role": "user", "content": text}],
    )
    response = message.content[0].text.strip()
    domain, body = "", text
    for line in response.splitlines():
        if line.startswith("domain:"):
            domain = line.split(":", 1)[1].strip()
        elif line.startswith("body:"):
            body = line.split(":", 1)[1].strip()
    if domain not in known_domains:
        domain = ""
    return domain, body


async def _do_ai_note(update: Update, text: str) -> None:
    """Haiku-structure freeform text into a tagged ingest note, then save it.

    Shared by /ai and the `/note ai ...` form.
    """
    text = text.strip()
    if not text:
        await update.message.reply_text(
            "Send some text after /ai, e.g. /ai call the dentist tomorrow"
        )
        return
    known_domains = set(read_thresholds().keys())
    try:
        domain, body = await _haiku_structure_note(text, known_domains)
    except Exception as e:
        await update.message.reply_text(f"Error calling AI: {e}")
        return
    if not body:
        await update.message.reply_text("Note body is empty.")
        return
    filename = write_ingest_note(domain, body)
    tag_str = f" [{domain}]" if domain else ""
    await update.message.reply_text(f"📝 Note saved{tag_str}: {filename}")


async def cmd_ai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ai <text> — freeform note; Haiku tags the domain and cleans it up."""
    if not is_authorized(update):
        return
    await _do_ai_note(update, " ".join(context.args or []))


async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/log [domain] <what you did> — record a completed entry in today's log.

    Retroactive / ad-hoc logging: for things the per-block check-in can't catch
    (a block you finished before the bot was running, morning pages, anything
    off-schedule). A leading domain tag makes it count toward that cadence.
    """
    if not is_authorized(update):
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: /log [domain] <what you did>\n"
            "Records a completed entry in today's log. Add a leading domain "
            "(e.g. /log novel wrote 500 words) so it counts toward that cadence."
        )
        return

    known_domains = set(read_thresholds().keys())
    domain, body = _extract_domain(args, known_domains)
    if not body:
        await update.message.reply_text(
            "Tell me what you did, e.g. /log morning pages done."
        )
        return

    entry = {
        "date": date.today().isoformat(),
        "covered": body,
        "outcome": "done",
    }
    if domain:
        entry["domain"] = domain
    append_log_entry(entry)
    tag = f" [{domain}]" if domain else ""
    await update.message.reply_text(f"📓 Logged{tag}: {body}")


async def cmd_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage:\n"
            "  /note [domain] <text>   — tag optional, must match a domain name\n"
            "  /ai <text>              — let Haiku tag & clean a freeform note\n"
            "  /note list              — same as /domain list"
        )
        return

    if args[0] == "ai":  # backwards-compatible alias for /ai
        await _do_ai_note(update, " ".join(args[1:]))
        return

    known_domains = set(read_thresholds().keys())
    domain, body = _extract_domain(args, known_domains)

    if not body:
        await update.message.reply_text("Note body is empty.")
        return

    filename = write_ingest_note(domain, body)
    tag_str = f" [{domain}]" if domain else ""
    await update.message.reply_text(f"📝 Note saved{tag_str}: {filename}")


# ---------------------------------------------------------------------------
# /edit command
# ---------------------------------------------------------------------------

EDIT_SYNTAX = (
    "*/edit* — programmatic edits\n\n"
    "*inbox*\n"
    "  `/edit inbox <task text>`\n"
    "  Appends a task to inbox.md\n\n"
    "*threshold*\n"
    "  `/edit threshold <domain>.<field> <value>`\n"
    "  Updates a numeric field in thresholds.yaml\n"
    "  Example: `/edit threshold novel.target 600`\n\n"
    "*/edit syntax* — show this message"
)


async def cmd_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    args = context.args or []

    if not args or args[0] == "syntax":
        await update.message.reply_text(EDIT_SYNTAX, parse_mode="Markdown")
        return

    subcommand = args[0].lower()

    if subcommand == "inbox":
        task = " ".join(args[1:])
        if not task:
            await update.message.reply_text("Provide task text after 'inbox'.")
            return
        append_inbox(task)
        await update.message.reply_text(f"✅ Added to inbox: {task}")

    elif subcommand == "threshold":
        if len(args) != 3:
            await update.message.reply_text(
                "Usage: /edit threshold <domain>.<field> <value>"
            )
            return
        key, raw_value = args[1], args[2]
        if "." not in key:
            await update.message.reply_text("Key must be in domain.field format.")
            return
        domain, field = key.split(".", 1)
        try:
            value = float(raw_value)
            value = int(value) if value == int(value) else value
        except ValueError:
            await update.message.reply_text(f"Value must be numeric, got: {raw_value}")
            return
        thresholds = read_thresholds()
        if domain not in thresholds:
            await update.message.reply_text(
                f"Unknown domain '{domain}'. Use /domain --list to see valid names."
            )
            return
        if field not in thresholds[domain]:
            await update.message.reply_text(
                f"Field '{field}' not found in domain '{domain}'."
            )
            return
        try:
            update_threshold(domain, field, value)
        except Exception as e:
            await update.message.reply_text(f"Error updating threshold: {e}")
            return
        await update.message.reply_text(
            f"✅ Updated: {domain}.{field} = {value}"
        )

    else:
        await update.message.reply_text(
            f"Unknown subcommand '{subcommand}'. Try /edit --syntax"
        )


# ---------------------------------------------------------------------------
# Check-in callback handler
# ---------------------------------------------------------------------------

async def checkin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.message.chat.id != get_chat_id():
        return

    await query.answer()

    # callback_data format: "ci:{outcome_key}:{block_name}"
    parts = query.data.split(":", 2)
    if len(parts) != 3:
        return

    _, outcome_key, block_name = parts
    outcome_map = {"done": "done", "partial": "partial", "reschedule": "rescheduled"}
    outcome = outcome_map.get(outcome_key, outcome_key)

    root = get_life_os_root()
    today = date.today()

    # Map the block to its scheduled task (if any) so the log carries `task:`
    # (DOMAIN-FORMAT.md §2) and the dependency/cadence resolvers can see it.
    result, state = build_result(root, today)
    task = task_in_block(result, block_name)
    task_id = task.id if task else None

    entry = {
        "date": today.isoformat(),
        "covered": f"{block_name} block — {task.title if task else 'no task mapped'}.",
        "outcome": outcome,
    }
    if task_id:
        entry["task"] = task_id
    append_log_entry(entry)

    # Reshuffle the remainder of the day through the shared engine.
    # 'rescheduled' drops the task from today; 'done'/'partial' conclude the block
    # (the task id is excluded via the log), freeing capacity for carried work.
    if outcome == "rescheduled" and task_id:
        if task_id not in state["dropped"]:
            state["dropped"].append(task_id)
        save_state(root, state)
    reshuffle_and_write(root, today)

    labels = {
        "done": "✅ Done",
        "partial": "⏩ Partial — logged",
        "reschedule": "🔁 Rescheduled — logged",
    }
    tail = f" ({task_id})" if task_id else ""
    await query.edit_message_text(
        f"{labels.get(outcome_key, outcome)} — {block_name}{tail}. Plan updated.")


# ---------------------------------------------------------------------------
# Reshuffle commands — bot as second writer of daily/README.md via schedule()
# ---------------------------------------------------------------------------
#
# v1 reshuffle vocabulary (fixed-block model, frozen urgency):
#   /plan            recompute + rewrite the day plan
#   /behind          deficit: numbered list -> drop a task for today
#   /add             surplus/squeeze-in: numbered list -> pin a carried task in
# All go through scheduler.day -> shared schedule(); fixed anchors stay pinned,
# mandatory floors protected, nothing scheduled below its `min`. Compress-to-min
# and explicit per-block relocation are deferred to v2 (see dev/TODO.md).


def _numbered_keyboard(items: list[tuple[str, str]], prefix: str) -> InlineKeyboardMarkup:
    """Build a numbered inline keyboard. items = [(task_id, label), ...]."""
    rows = [
        [InlineKeyboardButton(f"{i}. {label}", callback_data=f"{prefix}:{tid}")]
        for i, (tid, label) in enumerate(items, 1)
    ]
    return InlineKeyboardMarkup(rows)


def _checkin_keyboard(block_name: str) -> InlineKeyboardMarkup:
    """The done / partial / reschedule buttons for a block check-in."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Done", callback_data=f"ci:done:{block_name}"),
        InlineKeyboardButton("⏩ Partial", callback_data=f"ci:partial:{block_name}"),
        InlineKeyboardButton("🔁 Reschedule", callback_data=f"ci:reschedule:{block_name}"),
    ]])


def _now_hhmm() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M")


def _format_schedule(result) -> str:
    """A plain-text day plan suitable for a Telegram message (no Markdown)."""
    lines = ["📋 Today's plan", ""]
    for a in result.assignments:
        b = a.block
        when = f"{b['start']}-{b['end']}"
        if a.task:
            lines.append(f"{when}  {a.task.title}")
        elif b["slot"] is None:
            lines.append(f"{when}  · {b['name']}")
        else:
            lines.append(f"{when}  (open)")
    if result.carried:
        lines.append("")
        lines.append("Carried: " + ", ".join(t.title for t in result.carried))
    return "\n".join(lines)


def _current_task_block(result):
    """The task-bearing assignment whose time window contains right now, or None.

    Only a block that is actually in progress gets a check-in button — a fresh
    morning plan should show the day, not prompt a check-in for a block that
    hasn't started.
    """
    now = _now_hhmm()
    for a in result.assignments:
        if a.task and a.block["start"] <= now < a.block["end"]:
            return a
    return None


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    root = get_life_os_root()
    result = reshuffle_and_write(root, date.today())

    text = _format_schedule(result)
    cur = _current_task_block(result)
    if cur is not None:
        text += f"\n\nIn progress: {cur.block['name']} — {cur.task.title}\nCheck in 👇"
        await update.message.reply_text(
            text, reply_markup=_checkin_keyboard(cur.block["name"])
        )
    else:
        await update.message.reply_text(text)


async def cmd_behind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    root = get_life_os_root()
    result, _state = build_result(root, date.today())
    items = [(t.id, t.title) for t in result.placed]
    if not items:
        await update.message.reply_text("No scheduled tasks to drop.")
        return
    await update.message.reply_text(
        "⏳ Running behind — which task should I drop for today?",
        reply_markup=_numbered_keyboard(items, "rm"),
    )


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    root = get_life_os_root()
    result, _state = build_result(root, date.today())
    items = [(t.id, t.title) for t in result.carried]
    if not items:
        await update.message.reply_text("Nothing carried — every eligible task is already placed.")
        return
    await update.message.reply_text(
        "➕ Which task should I pin into the day?",
        reply_markup=_numbered_keyboard(items, "ad"),
    )


async def reshuffle_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles numbered-choice replies from /behind (rm) and /add (ad)."""
    query = update.callback_query
    if query.message.chat.id != get_chat_id():
        return
    await query.answer()

    action, _, task_id = query.data.partition(":")
    if not task_id:
        return

    root = get_life_os_root()
    today = date.today()
    state = load_state(root, today)

    if action == "rm":
        if task_id not in state["dropped"]:
            state["dropped"].append(task_id)
        # un-pin if it was previously added
        state["boosted"] = [b for b in state["boosted"] if b != task_id]
        verb = "Dropped"
    elif action == "ad":
        if task_id not in state["boosted"]:
            state["boosted"].append(task_id)
        state["dropped"] = [d for d in state["dropped"] if d != task_id]
        verb = "Pinned"
    else:
        return

    save_state(root, state)
    result = reshuffle_and_write(root, today)
    await query.edit_message_text(
        f"{verb} {task_id}. Plan updated: "
        f"{len(result.placed)} placed, {len(result.carried)} carried."
    )


# ---------------------------------------------------------------------------
# Cron-triggered send functions (--notify / --checkin)
# ---------------------------------------------------------------------------

def _get_block_task(block_name: str) -> str:
    """Try to pull the task for a block from today's daily README."""
    try:
        content = read_file("daily/README.md")
        for line in content.splitlines():
            if "|" in line and block_name.lower() in line.lower():
                cols = [c.strip() for c in line.split("|")]
                if len(cols) >= 4 and cols[3]:
                    return cols[3]
    except Exception:
        pass
    return ""


async def send_notify(block_name: str) -> None:
    bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
    task = _get_block_task(block_name)
    text = f"🕐 *{block_name}* is starting."
    if task:
        text += f"\nTask: {task}"
    async with bot:
        await bot.send_message(
            chat_id=get_chat_id(),
            text=text,
            parse_mode="Markdown",
        )


async def send_checkin(block_name: str) -> None:
    bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
    async with bot:
        await bot.send_message(
            chat_id=get_chat_id(),
            text=f"⏱ *{block_name}* is wrapping up. How did it go?",
            reply_markup=_checkin_keyboard(block_name),
            parse_mode="Markdown",
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_bot() -> None:
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("evening", cmd_evening))
    app.add_handler(CommandHandler("note", cmd_note))
    app.add_handler(CommandHandler("ai", cmd_ai))
    app.add_handler(CommandHandler("log", cmd_log))
    app.add_handler(CommandHandler("edit", cmd_edit))
    app.add_handler(CommandHandler("domain", cmd_domain))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("behind", cmd_behind))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CallbackQueryHandler(checkin_callback, pattern=r"^ci:"))
    app.add_handler(CallbackQueryHandler(reshuffle_choice_callback, pattern=r"^(rm|ad):"))
    logger.info("Bot starting (long-polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


def main() -> None:
    parser = argparse.ArgumentParser(description="Life OS Telegram bot")
    parser.add_argument("--notify", metavar="BLOCK", help="Send block start notification")
    parser.add_argument("--checkin", metavar="BLOCK", help="Send check-in prompt for a block")
    args = parser.parse_args()

    if args.notify:
        asyncio.run(send_notify(args.notify))
    elif args.checkin:
        asyncio.run(send_checkin(args.checkin))
    else:
        run_bot()


if __name__ == "__main__":
    main()
