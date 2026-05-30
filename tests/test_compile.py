"""Unit tests for scheduler.compile_queue against the fixture tree."""
from datetime import date

from scheduler.compile_queue import compile_queue, compile_to_file, load_queue


TODAY = date(2026, 6, 1)  # a Monday


def _by_id(tasks):
    return {t.id: t for t in tasks}


def test_compile_collects_all_sources(life_os):
    tasks, lint = compile_queue(life_os, TODAY)
    ids = _by_id(tasks)
    # Type 3 from tasks.md
    assert "career-001" in ids and "career-002" in ids and "career-003" in ids
    # Type 4 from thresholds (cadence domains only; upkeep as-scheduled excluded)
    assert "music-practice-recurring" in ids
    assert "novel-recurring" in ids
    assert "career-recurring" in ids
    assert "fitness-recurring" in ids
    assert "upkeep-recurring" not in ids
    # Type 1/2 from inbox
    assert any(t.source == "inbox" for t in tasks)


def test_inbox_due_becomes_type2(life_os):
    tasks, _ = compile_queue(life_os, TODAY)
    taxes = [t for t in tasks if "taxes" in t.title.lower()][0]
    assert taxes.type == 2
    assert taxes.deadline == date(2026, 6, 15)
    assert taxes.deadline_type == "hard"


def test_waiting_item_ineligible(life_os):
    tasks = _by_id(compile_queue(life_os, TODAY)[0])
    assert tasks["career-003"].eligible is False
    assert "waiting" in tasks["career-003"].blocked_reason


def test_depends_on_gates_eligibility(life_os):
    tasks = _by_id(compile_queue(life_os, TODAY)[0])
    # career-002 depends on career-001 which is NOT logged done -> ineligible
    assert tasks["career-002"].eligible is False
    assert "career-001" in tasks["career-002"].blocked_reason
    # career-001 has no deps -> eligible
    assert tasks["career-001"].eligible is True


def test_depends_on_satisfied_by_log(life_os):
    # Log career-001 done; career-002 should become eligible.
    (life_os / "daily" / "logs" / "2026-05-31.md").write_text(
        "## 2026-05-31\n\n- **outcome:** done\n- **task:** career-001\n", encoding="utf-8")
    tasks = _by_id(compile_queue(life_os, TODAY)[0])
    assert tasks["career-002"].eligible is True
    # career-001 logged done but still in tasks.md -> drift warning
    _, lint = compile_queue(life_os, TODAY)
    assert any("still present" in i.message for i in lint)


def test_critical_path_propagation(life_os):
    # career-002 is critical; its blocker career-001 should inherit >= its urgency.
    tasks = _by_id(compile_queue(life_os, TODAY)[0])
    assert tasks["career-001"].urgency >= tasks["career-002"].urgency


def test_cadence_debt_never_completed(life_os):
    # music-practice daily, never logged -> treated as one cycle due (urgency > 0).
    tasks = _by_id(compile_queue(life_os, TODAY)[0])
    assert tasks["music-practice-recurring"].urgency > 0


def test_mandatory_weekly_boost(life_os):
    tasks = _by_id(compile_queue(life_os, TODAY)[0])
    mp = tasks["music-practice-recurring"]   # has mandatory-weekly: 60
    assert mp.mandatory_due is True


def test_write_and_load_roundtrip(life_os):
    tasks, lint = compile_to_file(life_os, TODAY)
    loaded, lint2, generated = load_queue(life_os)
    assert generated is not None
    assert {t.id for t in loaded} == {t.id for t in tasks}
    # urgency frozen through the file boundary
    orig = _by_id(tasks)
    for t in loaded:
        assert abs(t.urgency - orig[t.id].urgency) < 0.01
        assert t.eligible == orig[t.id].eligible
