"""Unit tests for scheduler.tasks_parser — run against in-memory fixtures."""
from datetime import date

from scheduler.tasks_parser import parse_tasks_text


def _wrap(next_id, yaml_body):
    return (
        "<!-- comment -->\n"
        f"next-id: {next_id}\n\n"
        "# Career — Task Records\n\n"
        "```yaml\n"
        f"{yaml_body}\n"
        "```\n"
    )


def test_empty_scaffold():
    next_id, tasks, issues = parse_tasks_text(_wrap(1, "[]"), "career")
    assert next_id == 1
    assert tasks == []
    assert issues == []


def test_valid_record():
    body = """\
- id: career-001
  goal: nyc-job-search
  type: 3
  subtype: session-based
  title: "Tailor resume"
  importance: high
  duration: 60
  target: 60
  unit: minutes
  min: 30
  not-before: 2026-06-01
  depends-on: [career-002]
  placement:
    class: floating
    slots: [deep-work]
    min-block: 60
    window: ["08:00", "12:30"]
    energy: high
  waiting: false"""
    next_id, tasks, issues = parse_tasks_text(_wrap(2, body), "career")
    assert next_id == 2
    assert len(tasks) == 1
    t = tasks[0]
    assert t.id == "career-001"
    assert t.type == 3
    assert t.subtype == "session-based"
    assert t.importance == "high"
    assert t.duration == 60
    assert t.min == 30
    assert t.not_before == date(2026, 6, 1)
    assert t.depends_on == ["career-002"]
    assert t.placement.cls == "floating"
    assert t.placement.slots == ["deep-work"]
    assert t.placement.min_block == 60
    assert t.placement.window == ["08:00", "12:30"]
    assert [i for i in issues if i.level == "error"] == []


def test_id_at_or_above_next_id_is_error():
    body = "- id: career-005\n  type: 3\n  subtype: session-based\n  title: x\n  importance: normal\n  target: 1\n  unit: sessions\n  placement: {class: floating, slots: [deep-work]}"
    _, tasks, issues = parse_tasks_text(_wrap(5, body), "career")
    assert any("next-id" in i.message and i.level == "error" for i in issues)


def test_bad_id_format():
    body = "- id: career-12\n  type: 3\n  subtype: project\n  title: x\n  importance: low\n  target: 1\n  unit: sessions\n  placement: {class: floating, slots: [admin]}"
    _, _, issues = parse_tasks_text(_wrap(99, body), "career")
    assert any("does not match" in i.message for i in issues)


def test_unknown_slot_is_error():
    body = "- id: career-001\n  type: 3\n  subtype: project\n  title: x\n  importance: low\n  target: 1\n  unit: sessions\n  placement: {class: floating, slots: [made-up-slot]}"
    _, tasks, issues = parse_tasks_text(_wrap(2, body), "career")
    assert any("unknown slot" in i.message for i in issues)
    # invalid slot is stripped from the normalized record
    assert tasks[0].placement.slots == []


def test_invalid_importance():
    body = "- id: career-001\n  type: 3\n  subtype: project\n  title: x\n  importance: urgent\n  target: 1\n  unit: sessions\n  placement: {class: floating, slots: [admin]}"
    _, tasks, issues = parse_tasks_text(_wrap(2, body), "career")
    assert any("importance 'urgent'" in i.message for i in issues)
    assert tasks[0].importance == "normal"


def test_type3_missing_target_unit_warns():
    body = "- id: career-001\n  type: 3\n  subtype: project\n  title: x\n  importance: normal\n  placement: {class: floating, slots: [admin]}"
    _, _, issues = parse_tasks_text(_wrap(2, body), "career")
    assert any("target and unit" in i.message for i in issues)


def test_invalid_type():
    body = "- id: career-001\n  type: 9\n  title: x\n  importance: normal\n  placement: {class: floating, slots: [admin]}"
    _, _, issues = parse_tasks_text(_wrap(2, body), "career")
    assert any("type '9'" in i.message for i in issues)


def test_missing_next_id():
    text = "# Career\n\n```yaml\n[]\n```\n"
    next_id, _, issues = parse_tasks_text(text, "career")
    assert next_id == 1
    assert any("next-id" in i.message and i.level == "error" for i in issues)


def test_duplicate_id():
    body = (
        "- id: career-001\n  type: 1\n  title: a\n  importance: low\n  placement: {class: floating, slots: [admin]}\n"
        "- id: career-001\n  type: 1\n  title: b\n  importance: low\n  placement: {class: floating, slots: [admin]}"
    )
    _, _, issues = parse_tasks_text(_wrap(2, body), "career")
    assert any("duplicate id" in i.message for i in issues)
