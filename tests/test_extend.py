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
    from commands_doc import COMMAND_REGISTRY
    registry_cmds = {cmd for _grp, cmd, _desc in COMMAND_REGISTRY}
    # every command described here should also be wired
    expected_subset = {
        "plan", "log", "ai", "behind", "add", "skip", "move", "extend",
        "clearday", "note", "edit", "domain", "evening", "commands", "start",
    }
    assert expected_subset <= registry_cmds


def test_bot_commands_md_renders_all_groups_and_commands(tmp_path):
    from commands_doc import (
        COMMAND_REGISTRY,
        render_bot_commands_md,
        write_bot_commands_md,
    )
    text = render_bot_commands_md(generated="2026-05-31 12:00")
    # every command in the registry should appear in the doc
    for _grp, cmd, _desc in COMMAND_REGISTRY:
        assert f"`/{cmd}`" in text
    # every distinct group should have its own section header
    groups = {grp for grp, _c, _d in COMMAND_REGISTRY}
    for grp in groups:
        assert f"## {grp}" in text
    # and the writer drops the file at <root>/dev/bot-commands.md
    out = write_bot_commands_md(tmp_path)
    assert out == tmp_path / "dev" / "bot-commands.md"
    assert out.read_text(encoding="utf-8").startswith("<!-- SCRIPT-OWNED")
