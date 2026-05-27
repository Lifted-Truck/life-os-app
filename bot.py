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

from utils import append_log_entry, read_file

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
