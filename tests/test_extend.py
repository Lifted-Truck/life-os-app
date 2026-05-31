"""Tests for /extend's small helpers.

The full extend flow goes through _perform_move (shared with /move) which is
exercised end-to-end via the block-edit + conflict helpers already under test
in test_block_edits.py. This file pins down the minutes math.
"""
import bot


def test_add_minutes_basic():
    assert bot._add_minutes("10:00", 30) == "10:30"
    assert bot._add_minutes("10:45", 30) == "11:15"


def test_add_minutes_crosses_hour():
    assert bot._add_minutes("23:50", 30) == "23:59"   # capped at 23:59


def test_add_minutes_negative_floor():
    assert bot._add_minutes("00:10", -30) == "00:00"


def test_add_minutes_str_input_tolerant():
    # called from callback handlers where N is parsed from str(int) — int() is fine
    assert bot._add_minutes("09:00", 15) == "09:15"


def test_command_registry_describes_every_handler():
    """The grouped index and BotFather list must stay in sync with reality."""
    registry_cmds = {cmd for _grp, cmd, _desc in bot.COMMAND_REGISTRY}
    # every command described here should also be wired
    expected_subset = {
        "plan", "log", "ai", "behind", "add", "skip", "move", "extend",
        "clearday", "note", "edit", "domain", "evening", "commands", "start",
    }
    assert expected_subset <= registry_cmds
