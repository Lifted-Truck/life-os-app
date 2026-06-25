"""Log parser — quantitative amount/unit extraction from the canonical
`duration:` field (DOMAIN-FORMAT.md §2: "X min | X words | X pages | X sessions").
"""
from datetime import date

from scheduler.logs import parse_log_text

D = date(2026, 6, 18)


def _one(text):
    entries = parse_log_text(text, D)
    assert len(entries) == 1
    return entries[0]


def _entry(duration_line, extra=""):
    return _one(f"## {D.isoformat()}\n\n{duration_line}\n- **outcome:** done\n{extra}")


def test_minutes():
    e = _entry("- **duration:** 60 min")
    assert e.amount == 60.0 and e.unit == "minutes"


def test_hours_normalized_to_minutes():
    e = _entry("- **duration:** 1.5 h")
    assert e.amount == 90.0 and e.unit == "minutes"


def test_words():
    e = _entry("- **duration:** 500 words", "- **domain:** novel")
    assert e.amount == 500.0 and e.unit == "words"


def test_pages():
    e = _entry("- **duration:** 3 pages")
    assert e.amount == 3.0 and e.unit == "pages"


def test_sessions():
    e = _entry("- **duration:** 1 session")
    assert e.amount == 1.0 and e.unit == "sessions"


def test_bare_number_has_no_unit():
    e = _entry("- **duration:** 45")
    assert e.amount == 45.0 and e.unit is None


def test_no_duration_is_none():
    e = _one(f"## {D.isoformat()}\n\n- **covered:** wrote some stuff\n- **outcome:** done\n")
    assert e.amount is None and e.unit is None


def test_unparseable_duration_is_safe():
    e = _entry("- **duration:** a while")
    assert e.amount is None and e.unit is None


def test_backward_compatible_fields():
    e = _one(f"## {D.isoformat()}\n\n- **outcome:** done\n- **task:** novel-003\n")
    assert e.task_id == "novel-003" and e.outcome == "done"
    assert e.amount is None and e.unit is None


def test_multiple_entries_mixed():
    text = (f"## {D.isoformat()}\n\n- **duration:** 30 min\n- **outcome:** done\n"
            "- **domain:** career\n\n"
            f"## {D.isoformat()}\n\n- **outcome:** partial\n- **domain:** fitness\n")
    entries = parse_log_text(text, D)
    assert len(entries) == 2
    assert entries[0].amount == 30.0 and entries[0].unit == "minutes"
    assert entries[1].amount is None
