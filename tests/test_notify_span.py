"""Test the block-span label on T-5 'is starting' notifications.

Dev note 2026-06-05: "'is starting' notes should give length of block or
end time." _block_span_label looks up today's effective block and returns
'until <end> (<dur> min)'.

We write an explicit template.yaml into the tmp data tree so the loader
reads it "live" — otherwise it would fall back to the app-dir cache (the
real user template) and the assertions wouldn't be deterministic.
"""
import textwrap

import bot


TEMPLATE = """\
    blocks:
      - name: Deep Work 1
        start: "08:00"
        end: "10:00"
        slot: deep-work
      - name: Lunch
        start: "12:30"
        end: "13:30"
        slot: null
"""


def _seed(tmp_path):
    sched = tmp_path / "schedule"
    sched.mkdir(parents=True, exist_ok=True)
    (sched / "template.yaml").write_text(textwrap.dedent(TEMPLATE), encoding="utf-8")


def test_span_label_for_known_block(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    _seed(tmp_path)
    assert bot._block_span_label("Deep Work 1") == "until 10:00 (120 min)"


def test_span_label_for_fixed_block(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    _seed(tmp_path)
    assert bot._block_span_label("Lunch") == "until 13:30 (60 min)"


def test_span_label_empty_for_unknown_block(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    _seed(tmp_path)
    # An anchored Type-2 event title is not a template block -> no span.
    assert bot._block_span_label("Dentist appointment") == ""


def test_span_label_reflects_block_edits(tmp_path, monkeypatch):
    """A /extend or /move that changed the block's end is reflected."""
    from datetime import date
    from scheduler.day import load_state, save_state, set_block_time
    monkeypatch.setenv("LIFE_OS_ROOT", str(tmp_path))
    _seed(tmp_path)
    today = date.today()
    state = load_state(tmp_path, today)
    set_block_time(state, "Deep Work 1", "08:00", "11:00")  # extended to 11:00
    save_state(tmp_path, state)
    assert bot._block_span_label("Deep Work 1") == "until 11:00 (180 min)"
