import os
import sys
from datetime import date
from pathlib import Path

import resend
from dotenv import load_dotenv

from utils import (
    get_life_os_root,
    write_file,
)
from scheduler.compile_queue import compile_to_file
from scheduler.day import build_result, reset_state, write_daily_readme
from scheduler.schedule import render_daily_readme_body

load_dotenv(Path(__file__).parent / ".env", override=True)


def generate_plan() -> str:
    """Build today's plan deterministically — NO AI (SYSTEM.md governing principle).

    compile() regenerates schedule/queue.yaml from the four task sources + logs,
    resets the day's reshuffle state, then the shared schedule() engine places
    tasks into the day's blocks. morning.py and bot.py share this engine.
    Returns the rendered README body (for the log + email).
    """
    root = get_life_os_root()
    today = date.today()

    tasks, lint = compile_to_file(root, today)
    reset_state(root, today)                       # fresh day: clear drops/boosts
    result, _state = build_result(root, today)
    write_daily_readme(root, result, today)

    errors = [i for i in lint if i.level == "error"]
    if errors:
        print(f"compile() raised {len(errors)} lint error(s):", file=sys.stderr)
        for i in errors:
            print(f"  [{i.where}] {i.message}", file=sys.stderr)

    return render_daily_readme_body(result, today)


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

    print("Wrote daily/README.md (compiled queue.yaml + deterministic schedule)")

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
