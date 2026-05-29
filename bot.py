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
    read_file,
    read_thresholds,
    update_threshold,
    write_ingest_note,
)

load_dotenv(Path(__file__).parent / ".env", override=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
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


async def cmd_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage:\n"
            "  /note [domain] <text>   — tag optional, must match a domain name\n"
            "  /note ai <text>         — let Haiku extract domain and clean text\n"
            "  /note list              — same as /domain list"
        )
        return

    known_domains = set(read_thresholds().keys())

    if args[0] == "ai":
        text = " ".join(args[1:])
        if not text:
            await update.message.reply_text("Provide text after 'ai'.")
            return
        try:
            domain, body = await _haiku_structure_note(text, known_domains)
        except Exception as e:
            await update.message.reply_text(f"Error calling AI: {e}")
            return
    else:
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

    append_log_entry({
        "date": date.today().isoformat(),
        "covered": f"{block_name} block completed.",
        "outcome": outcome,
    })

    labels = {
        "done": "✅ Done",
        "partial": "⏩ Partial — logged",
        "reschedule": "🔁 Rescheduled — logged",
    }
    await query.edit_message_text(f"{labels.get(outcome_key, outcome)} — {block_name}.")


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
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Done", callback_data=f"ci:done:{block_name}"),
        InlineKeyboardButton("⏩ Partial", callback_data=f"ci:partial:{block_name}"),
        InlineKeyboardButton("🔁 Reschedule", callback_data=f"ci:reschedule:{block_name}"),
    ]])
    async with bot:
        await bot.send_message(
            chat_id=get_chat_id(),
            text=f"⏱ *{block_name}* is wrapping up. How did it go?",
            reply_markup=keyboard,
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
    app.add_handler(CommandHandler("edit", cmd_edit))
    app.add_handler(CommandHandler("domain", cmd_domain))
    app.add_handler(CallbackQueryHandler(checkin_callback, pattern=r"^ci:"))
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
