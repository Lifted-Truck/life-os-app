import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import anthropic
import resend
import yaml
from dotenv import load_dotenv

from utils import (
    get_life_os_root,
    read_file,
    read_thresholds,
    write_file,
)

load_dotenv(Path(__file__).parent / ".env", override=True)

MODEL = "claude-haiku-4-5-20251001"

DAILY_README_TEMPLATE = """\
<!-- SCRIPT-OWNED: overwritten each morning by cron. Do not restructure. -->

# Daily Plan

**Date:** {date}
**Generated:** {generated}

{body}"""

SYSTEM_PROMPT = """\
You are a daily planning assistant for a personal life operating system.
Given the user's domain thresholds, schedule template, and yesterday's activity,
generate a concise daily block plan.

Return ONLY the content for these four sections, in this exact format:

## Available Time Today
[Brief note on available time based on the schedule template]

## Today's Blocks

| Time | Domain | Task | Type | Duration | Status |
|------|--------|------|------|----------|--------|
[One row per workable block. Match domains to thresholds. Tasks should be specific and actionable.]

## Non-Negotiables Today
[List any mandatory-weekly thresholds due or at risk today. If none, write: None flagged.]

## Carried Forward
[List any missed or rescheduled items from yesterday's log. If none, write: None.]

Keep content brief. Do not add sections or commentary outside these four."""


def _read_yesterday_log() -> str:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    try:
        return read_file(f"daily/logs/{yesterday}.md")
    except FileNotFoundError:
        return "No log found for yesterday."


def _build_user_prompt(thresholds: dict, schedule: str, yesterday_log: str) -> str:
    thresholds_text = yaml.dump(thresholds, default_flow_style=False)
    return "\n\n".join([
        f"Today's date: {date.today().isoformat()}",
        f"## Domain Thresholds\n\n{thresholds_text}",
        f"## Schedule Template\n\n{schedule}",
        f"## Yesterday's Log\n\n{yesterday_log}",
    ])


def generate_plan() -> str:
    thresholds = read_thresholds()
    schedule = read_file("schedule/template.md")
    yesterday_log = _read_yesterday_log()

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": _build_user_prompt(thresholds, schedule, yesterday_log)}
        ],
    )
    return message.content[0].text


def write_daily_readme(body: str) -> None:
    now = datetime.now()
    content = DAILY_README_TEMPLATE.format(
        date=now.strftime("%Y-%m-%d"),
        generated=now.strftime("%H:%M"),
        body=body,
    )
    write_file("daily/README.md", content)


def create_today_log(plan_body: str) -> None:
    today = date.today().isoformat()
    log_path = f"daily/logs/{today}.md"
    full_path = get_life_os_root() / log_path
    if not full_path.exists():
        content = f"# Daily Log — {today}\n\n## Plan\n\n{plan_body}\n\n## Check-ins\n\n"
        write_file(log_path, content)


def send_email(body: str) -> None:
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        print("RESEND_API_KEY not set — skipping email.")
        return

    resend.api_key = api_key
    resend.Emails.send({
        "from": os.getenv("EMAIL_FROM"),
        "to": os.getenv("EMAIL_TO"),
        "subject": f"Morning Briefing — {date.today().isoformat()}",
        "text": body,
    })


def main():
    print(f"Generating morning briefing for {date.today().isoformat()}...")

    try:
        plan_body = generate_plan()
    except Exception as e:
        print(f"Error generating plan: {e}", file=sys.stderr)
        sys.exit(1)

    write_daily_readme(plan_body)
    print("Wrote daily/README.md")

    create_today_log(plan_body)
    print(f"Created daily/logs/{date.today().isoformat()}.md")

    try:
        send_email(plan_body)
        print("Sent email briefing")
    except Exception as e:
        print(f"Warning: email send failed: {e}", file=sys.stderr)

    print("Done.")


if __name__ == "__main__":
    main()
