"""Messy-review capture — fire times, prompt rendering, append-only stanzas."""
from datetime import date, datetime
from pathlib import Path

from bot_handlers.review import (
    append_review,
    render_review_prompt,
    review_fire_times,
)

MON = date(2026, 7, 6)      # a Monday
SUN = date(2026, 7, 5)      # a Sunday


def test_fire_times_daily_only_on_weekdays():
    jobs = review_fire_times(MON, datetime(2026, 7, 6, 8, 0))
    assert [k for k, _ in jobs] == ["daily"]


def test_fire_times_weekly_added_on_sunday():
    jobs = review_fire_times(SUN, datetime(2026, 7, 5, 8, 0))
    assert [k for k, _ in jobs] == ["daily", "weekly"]


def test_fire_times_filters_past():
    jobs = review_fire_times(MON, datetime(2026, 7, 6, 23, 30))
    assert jobs == []


def test_append_review_header_once_stanzas_accumulate(life_os):
    p1 = append_review(life_os, "first messy dump",
                       now=datetime(2026, 7, 6, 21, 10))
    p2 = append_review(life_os, "second thought",
                       kind="weekly", now=datetime(2026, 7, 6, 21, 30))
    assert p1 == p2 == life_os / "daily" / "reviews" / "2026-07-06.md"
    text = p1.read_text(encoding="utf-8")
    assert text.count("APPEND-ONLY") == 1          # header exactly once
    assert "## 21:10 · daily" in text and "first messy dump" in text
    assert "## 21:30 · weekly" in text and "second thought" in text
    assert text.index("first messy dump") < text.index("second thought")


def test_prompt_renders_goals_mode_with_log(life_os):
    (life_os / "schedule" / "mode.yaml").write_text(
        "plan_mode: goals\n", encoding="utf-8")
    today = date.today()
    (life_os / "daily" / "logs" / f"{today.isoformat()}.md").write_text(
        f"## {today}\n\n- **duration:** 30 min\n- **outcome:** done\n"
        "- **domain:** music-practice\n", encoding="utf-8")
    text = render_review_prompt(life_os, today=today)
    assert "Evening review" in text
    assert "1 done" in text and "music-practice" in text
    assert "/review" in text            # the how-to-reply line


def test_prompt_weekly_includes_week_numbers(life_os):
    (life_os / "schedule" / "mode.yaml").write_text(
        "plan_mode: goals\n", encoding="utf-8")
    today = date.today()
    (life_os / "daily" / "logs" / f"{today.isoformat()}.md").write_text(
        f"## {today}\n\n- **outcome:** done\n- **domain:** career\n",
        encoding="utf-8")
    text = render_review_prompt(life_os, today=today, weekly=True)
    assert "Week in numbers" in text and "career: 1 completion" in text


def test_prompt_never_raises_on_broken_tree(tmp_path):
    text = render_review_prompt(tmp_path / "nonexistent")
    assert "Evening review" in text and "/review" in text   # generic fallback


# --- /review command handler (stubbed telegram objects) ----------------------

import asyncio
from types import SimpleNamespace

from bot_handlers.review import PROMPT_IDS, build_cmd_review


def _fake_update(sent):
    async def reply_text(text):
        sent.append(text)
        return SimpleNamespace(message_id=7777)
    return SimpleNamespace(message=SimpleNamespace(reply_text=reply_text))


def test_cmd_review_bare_sends_prompt_and_registers(life_os):
    sent = []
    cmd = build_cmd_review(lambda u: True, lambda: life_os)
    asyncio.run(cmd(_fake_update(sent), SimpleNamespace(args=[])))
    assert sent and "Evening review" in sent[0]
    assert PROMPT_IDS.get(7777) == "daily"
    PROMPT_IDS.clear()


def test_cmd_review_weekly_variant(life_os):
    sent = []
    cmd = build_cmd_review(lambda u: True, lambda: life_os)
    asyncio.run(cmd(_fake_update(sent), SimpleNamespace(args=["weekly"])))
    assert PROMPT_IDS.get(7777) == "weekly"
    PROMPT_IDS.clear()


def test_cmd_review_with_text_captures_stanza(life_os):
    sent = []
    cmd = build_cmd_review(lambda u: True, lambda: life_os)
    asyncio.run(cmd(_fake_update(sent), SimpleNamespace(args=["so", "messy"])))
    files = list((life_os / "daily" / "reviews").glob("*.md"))
    assert len(files) == 1 and "so messy" in files[0].read_text(encoding="utf-8")
    assert sent and "Captured" in sent[0]