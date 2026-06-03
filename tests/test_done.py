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


# --- end-to-end: check an item, parser drops it -----------------------------

def test_check_then_normalize_removes_item(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    _write_inbox(tmp_path, "- [ ] alpha\n- [ ] beta\n- [ ] gamma\n")
    utils.check_inbox_item("inbox-002")
    text = (tmp_path / "inbox.md").read_text(encoding="utf-8")
    tasks = _normalize_inbox(text, today=None, lint=[])
    assert [t.title for t in tasks] == ["alpha", "gamma"]
