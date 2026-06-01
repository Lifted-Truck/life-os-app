"""Tests for /note routing — life notes vs Dev-Note Bin (`/note dev`).

The literal `dev` keyword is recognized alongside thresholds.yaml domains and
routes the note to `ingest/dev/` (a Code session drain target) rather than
the life-note `ingest/` bin (a Cowork drain target).
"""
import os
from pathlib import Path

import pytest

import utils
import bot


def test_extract_domain_recognizes_dev_keyword():
    domain, body = bot._extract_domain(["dev", "fix", "the", "thing"], known_domains={"novel", "career"})
    assert domain == "dev"
    assert body == "fix the thing"


def test_extract_domain_falls_back_blank_when_not_a_tag():
    domain, body = bot._extract_domain(["random", "musing"], known_domains={"novel"})
    assert domain == "" and body == "random musing"


def test_write_ingest_note_routes_dev_to_dev_subfolder(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    path = utils.write_ingest_note("dev", "extend the bot to do X")
    assert path.startswith("ingest/dev/")
    assert (tmp_path / path).is_file()
    body = (tmp_path / path).read_text(encoding="utf-8")
    assert "domain: dev" in body
    assert "extend the bot to do X" in body


def test_write_ingest_note_keeps_life_notes_in_main_ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    path = utils.write_ingest_note("novel", "ideas for chapter 3")
    assert path.startswith("ingest/") and not path.startswith("ingest/dev/")
    assert (tmp_path / path).is_file()


def test_write_ingest_note_blank_domain_goes_to_main_ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    path = utils.write_ingest_note("", "untagged thought")
    assert path.startswith("ingest/") and not path.startswith("ingest/dev/")
