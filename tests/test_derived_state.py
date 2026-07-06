"""Derived-state eviction (architecture-review Tier-1B).

queue.yaml is untracked in git; the app must self-heal when it's absent, and
bot-commands.md must not rewrite when only its timestamp would change.
"""
from commands_doc import write_bot_commands_md
from scheduler.compile_queue import load_queue


def test_load_queue_self_heals_when_missing(life_os):
    q = life_os / "schedule" / "queue.yaml"
    q.unlink()
    tasks, lint, generated = load_queue(life_os)
    assert q.exists(), "missing projection should be re-derived"
    assert generated is not None
    assert any(t.id == "career-001" for t in tasks)   # fixture content compiled


def test_load_queue_reads_existing_without_recompiling(life_os):
    # the fixture's placeholder queue is empty; a plain load must NOT clobber it
    tasks, _lint, generated = load_queue(life_os)
    assert tasks == [] and generated is None


def test_bot_commands_skips_timestamp_only_rewrite(life_os, monkeypatch):
    out = write_bot_commands_md(life_os)
    first = out.read_text(encoding="utf-8")
    monkeypatch.setattr("commands_doc.datetime", _FrozenLater)
    out2 = write_bot_commands_md(life_os)
    assert out2.read_text(encoding="utf-8") == first, \
        "timestamp-only change must not rewrite the file"


def test_bot_commands_rewrites_on_real_change(life_os, monkeypatch):
    write_bot_commands_md(life_os)
    monkeypatch.setattr(
        "commands_doc.COMMAND_REGISTRY",
        [("Daily flow", "newcmd", "a brand new command")],
    )
    out = write_bot_commands_md(life_os)
    text = out.read_text(encoding="utf-8")
    assert "newcmd" in text and "plan" not in text


class _FrozenLater:
    """datetime stand-in whose now() is a different, fixed timestamp."""
    @staticmethod
    def now():
        from datetime import datetime
        return datetime(2099, 1, 1, 12, 0)
