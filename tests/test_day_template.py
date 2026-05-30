"""Tests for the resilient day-template loader (scheduler.day_template)."""
import textwrap
from pathlib import Path

import pytest
import yaml

from scheduler.constants import DEFAULT_BLOCKS
from scheduler.day_template import load_day_template, parse_blocks


def _write_template(root: Path, text: str) -> Path:
    p = root / "schedule" / "template.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text), encoding="utf-8")
    return p


GOOD = """\
    blocks:
      - name: Morning Pages & Coffee
        start: "07:00"
        end: "08:00"
        slot: null
      - name: Deep Work
        start: "08:00"
        end: "10:00"
        slot: deep-work
"""


def test_live_source_is_read_and_cached(tmp_path):
    root = tmp_path / "life-os"
    _write_template(root, GOOD)
    cache = tmp_path / "cache" / "day_template.yaml"

    blocks, source = load_day_template(root, cache_path=cache)

    assert source == "live"
    assert [b["name"] for b in blocks] == ["Morning Pages & Coffee", "Deep Work"]
    assert blocks[0]["slot"] is None and blocks[1]["slot"] == "deep-work"
    # cache was refreshed from the live read
    assert cache.is_file()
    assert parse_blocks(yaml.safe_load(cache.read_text(encoding="utf-8")))[1]["slot"] == "deep-work"


def test_falls_back_to_cache_when_live_missing(tmp_path):
    root = tmp_path / "life-os"          # no schedule/template.yaml here
    cache = tmp_path / "cache" / "day_template.yaml"
    cache.parent.mkdir(parents=True)
    cache.write_text(textwrap.dedent(GOOD), encoding="utf-8")

    blocks, source = load_day_template(root, cache_path=cache)

    assert source == "cache"
    assert [b["name"] for b in blocks] == ["Morning Pages & Coffee", "Deep Work"]


def test_falls_back_to_cache_when_live_corrupt(tmp_path):
    root = tmp_path / "life-os"
    _write_template(root, "blocks: [ this is : not : valid")  # broken YAML
    cache = tmp_path / "cache" / "day_template.yaml"
    cache.parent.mkdir(parents=True)
    cache.write_text(textwrap.dedent(GOOD), encoding="utf-8")

    blocks, source = load_day_template(root, cache_path=cache)
    assert source == "cache"


def test_falls_back_to_default_when_nothing_available(tmp_path):
    root = tmp_path / "life-os"
    cache = tmp_path / "cache" / "day_template.yaml"  # does not exist

    blocks, source = load_day_template(root, cache_path=cache)

    assert source == "default"
    assert [b["name"] for b in blocks] == [b["name"] for b in DEFAULT_BLOCKS]


def test_unquoted_sexagesimal_times_are_tolerated(tmp_path):
    # YAML reads unquoted 10:00 as int 600; the loader must still accept it.
    root = tmp_path / "life-os"
    _write_template(root, """\
        blocks:
          - name: Deep Work
            start: 10:00
            end: 12:30
            slot: deep-work
    """)
    cache = tmp_path / "cache" / "day_template.yaml"
    blocks, source = load_day_template(root, cache_path=cache)
    assert source == "live"
    assert blocks[0]["start"] == "10:00" and blocks[0]["end"] == "12:30"


def test_unknown_slot_is_rejected():
    with pytest.raises(ValueError):
        parse_blocks({"blocks": [
            {"name": "X", "start": "08:00", "end": "09:00", "slot": "bogus-slot"},
        ]})


def test_end_before_start_is_rejected():
    with pytest.raises(ValueError):
        parse_blocks({"blocks": [
            {"name": "X", "start": "10:00", "end": "09:00", "slot": None},
        ]})


def test_blocks_are_sorted_by_start():
    blocks = parse_blocks({"blocks": [
        {"name": "Late", "start": "18:00", "end": "19:00", "slot": "admin"},
        {"name": "Early", "start": "08:00", "end": "09:00", "slot": "deep-work"},
    ]})
    assert [b["name"] for b in blocks] == ["Early", "Late"]
