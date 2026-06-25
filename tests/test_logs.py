"""Log parser — quantitative amount/unit extraction (L0 for progress metrics)."""
from datetime import date

from scheduler.logs import parse_log_text

D = date(2026, 6, 18)


def _one(text):
    entries = parse_log_text(text, D)
    assert len(entries) == 1
    return entries[0]


def test_duration_minutes():
    e = _one("## 2026-06-18\n\n- **duration:** 60 min\n- **outcome:** done\n"
             "- **domain:** music-practice\n")
    assert e.amount == 60.0 and e.unit == "minutes"
    assert e.domain == "music-practice" and e.outcome == "done"


def test_duration_hours_normalized_to_minutes():
    e = _one("## x\n\n- **duration:** 1.5 h\n- **outcome:** done\n")
    assert e.amount == 90.0 and e.unit == "minutes"


def test_explicit_amount_and_unit():
    e = _one("## x\n\n- **amount:** 500\n- **unit:** words\n- **outcome:** done\n"
             "- **domain:** novel\n")
    assert e.amount == 500.0 and e.unit == "words"


def test_no_amount_is_none():
    e = _one("## x\n\n- **covered:** wrote some stuff\n- **outcome:** done\n")
    assert e.amount is None and e.unit is None


def test_bad_amount_is_safe():
    e = _one("## x\n\n- **amount:** lots\n- **outcome:** done\n")
    assert e.amount is None


def test_backward_compatible_fields():
    e = _one("## x\n\n- **outcome:** done\n- **task:** novel-003\n")
    assert e.task_id == "novel-003" and e.outcome == "done"
    assert e.amount is None and e.unit is None


def test_multiple_entries_mixed():
    text = ("## 2026-06-18\n\n- **duration:** 30 min\n- **outcome:** done\n"
            "- **domain:** career\n\n"
            "## 2026-06-18\n\n- **outcome:** partial\n- **domain:** fitness\n")
    entries = parse_log_text(text, D)
    assert len(entries) == 2
    assert entries[0].amount == 30.0 and entries[0].unit == "minutes"
    assert entries[1].amount is None
