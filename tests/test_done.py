"""Tests for /done — the one-shot task completion path.

Covers:
  - compile_queue's inbox parser now skips checked items
  - utils.check_inbox_item rewrites the n-th open inbox line in place
  - both pieces compose: check an item, recompile, item disappears
"""
import os
from pathlib import Path

import pytest

import utils
from scheduler.compile_queue import _normalize_inbox


# --- inbox parser respects [x] ---------------------------------------------

def test_normalize_inbox_skips_checked_items():
    text = (
        "- [ ] open one\n"
        "- [x] already done\n"
        "- [ ] open two\n"
    )
    tasks = _normalize_inbox(text, today=None, lint=[])
    titles = [t.title for t in tasks]
    assert titles == ["open one", "open two"]


def test_normalize_inbox_ids_count_only_open():
    text = (
        "- [x] zero\n"
        "- [ ] first\n"
        "- [x] still done\n"
        "- [ ] second\n"
    )
    tasks = _normalize_inbox(text, today=None, lint=[])
    assert [t.id for t in tasks] == ["inbox-001", "inbox-002"]
    assert [t.title for t in tasks] == ["first", "second"]


# --- check_inbox_item helper -----------------------------------------------

def _write_inbox(root: Path, text: str) -> Path:
    p = root / "inbox.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_check_inbox_item_marks_correct_line(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    _write_inbox(tmp_path, "- [ ] alpha\n- [ ] beta\n- [ ] gamma\n")
    assert utils.check_inbox_item("inbox-002") is True
    text = (tmp_path / "inbox.md").read_text(encoding="utf-8")
    assert text == "- [ ] alpha\n- [x] beta\n- [ ] gamma\n"


def test_check_inbox_item_skips_already_checked(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    # inbox-002 should be the SECOND open item ("gamma"), not "already-done"
    _write_inbox(
        tmp_path,
        "- [ ] alpha\n- [x] already-done\n- [ ] gamma\n- [ ] delta\n",
    )
    assert utils.check_inbox_item("inbox-002") is True
    text = (tmp_path / "inbox.md").read_text(encoding="utf-8")
    assert text == (
        "- [ ] alpha\n- [x] already-done\n- [x] gamma\n- [ ] delta\n"
    )


def test_check_inbox_item_preserves_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    _write_inbox(
        tmp_path,
        "- [ ] File taxes | due: hard 2026-06-15\n"
        "- [ ] Email landlord | waiting: true\n",
    )
    assert utils.check_inbox_item("inbox-001") is True
    text = (tmp_path / "inbox.md").read_text(encoding="utf-8")
    assert text.startswith("- [x] File taxes | due: hard 2026-06-15\n")
    assert "| waiting: true" in text


def test_check_inbox_item_returns_false_when_out_of_range(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    _write_inbox(tmp_path, "- [ ] only one\n")
    assert utils.check_inbox_item("inbox-005") is False
    # Original content untouched
    assert (tmp_path / "inbox.md").read_text(encoding="utf-8") == "- [ ] only one\n"


def test_check_inbox_item_handles_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    # No inbox.md
    assert utils.check_inbox_item("inbox-001") is False


# --- check_inbox_item_by_title --------------------------------------------

def test_check_by_title_marks_first_match(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    _write_inbox(tmp_path, "- [ ] Pick up dry cleaning\n- [ ] File taxes\n")
    assert utils.check_inbox_item_by_title("Pick up dry cleaning") is True
    text = (tmp_path / "inbox.md").read_text(encoding="utf-8")
    assert text.startswith("- [x] Pick up dry cleaning\n")


def test_check_by_title_substring_match(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    _write_inbox(tmp_path, "- [ ] File taxes | due: hard 2026-06-15\n")
    # The Task.title is just "File taxes" (pipe-fields stripped by parser).
    assert utils.check_inbox_item_by_title("File taxes") is True


def test_check_by_title_skips_already_checked(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    _write_inbox(
        tmp_path,
        "- [x] Pick up dry cleaning\n- [ ] Pick up dry cleaning\n",
    )
    # The first OPEN matching line is the second (second [ ] line wins).
    assert utils.check_inbox_item_by_title("Pick up dry cleaning") is True
    text = (tmp_path / "inbox.md").read_text(encoding="utf-8")
    assert text == "- [x] Pick up dry cleaning\n- [x] Pick up dry cleaning\n"


def test_check_by_title_no_match_returns_false(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    _write_inbox(tmp_path, "- [ ] something else\n")
    assert utils.check_inbox_item_by_title("not present") is False


# --- goals output respects today's done log entries -----------------------

def test_goals_view_excludes_today_done(life_os):
    """The integration cmd_plan/morning.py do: filter queue by done_ids_today."""
    from datetime import date
    from scheduler.compile_queue import compile_to_file
    from scheduler.day import done_ids_today
    from scheduler.goals import render_goals_text
    from scheduler.compile_queue import load_queue

    today = date(2026, 6, 1)
    # Seed inbox.md with one item so queue has an inbox task
    (life_os / "inbox.md").write_text(
        "- [ ] Pick up dry cleaning\n", encoding="utf-8")
    compile_to_file(life_os, today)

    tasks, _l, _g = load_queue(life_os)
    inbox_task = next(t for t in tasks if t.source == "inbox")

    # Simulate /done writing a log entry referencing the inbox task id
    (life_os / "daily" / "logs" / f"{today.isoformat()}.md").write_text(
        f"## {today.isoformat()}\n\n"
        f"- **outcome:** done\n"
        f"- **task:** {inbox_task.id}\n",
        encoding="utf-8",
    )

    done = done_ids_today(life_os, today)
    assert inbox_task.id in done

    # The done-filter is what cmd_plan + morning.py apply
    filtered = [t for t in tasks if t.id not in done]
    text = render_goals_text(filtered, today)
    assert "Pick up dry cleaning" not in text


# --- end-to-end: check an item, parser drops it -----------------------------

def test_check_then_normalize_removes_item(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    _write_inbox(tmp_path, "- [ ] alpha\n- [ ] beta\n- [ ] gamma\n")
    utils.check_inbox_item("inbox-002")
    text = (tmp_path / "inbox.md").read_text(encoding="utf-8")
    tasks = _normalize_inbox(text, today=None, lint=[])
    assert [t.title for t in tasks] == ["alpha", "gamma"]
