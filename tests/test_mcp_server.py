"""Life-OS MCP server tools — exercised directly (FastMCP leaves them callable)."""
from datetime import date

import pytest

import mcp_server as M


def _use(life_os, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(life_os))


def _log_today(root, body):
    today = date.today().isoformat()
    (root / "daily" / "logs" / f"{today}.md").write_text(
        f"## {today}\n\n{body}\n", encoding="utf-8")


def test_list_domains(life_os, monkeypatch):
    _use(life_os, monkeypatch)
    doms = M.list_domains()
    assert "music-practice" in doms and "novel" in doms


def test_get_domain_progress(life_os, monkeypatch):
    _use(life_os, monkeypatch)
    _log_today(life_os, "- **duration:** 30 min\n- **outcome:** done\n"
                        "- **domain:** music-practice")
    p = M.get_domain_progress("music-practice", days=7)
    assert p["domain"] == "music-practice" and p["unit"] == "minutes"
    assert p["totals"]["completions"] >= 1 and len(p["series"]) == 7


def test_unknown_domain_raises(life_os, monkeypatch):
    _use(life_os, monkeypatch)
    with pytest.raises(ValueError):
        M.get_domain_progress("nonesuch")


def test_bad_bucket_raises(life_os, monkeypatch):
    _use(life_os, monkeypatch)
    with pytest.raises(ValueError):
        M.get_domain_progress("music-practice", bucket="month")


def test_recent_activity(life_os, monkeypatch):
    _use(life_os, monkeypatch)
    _log_today(life_os, "- **duration:** 500 words\n- **outcome:** done\n"
                        "- **domain:** novel")
    acts = M.get_recent_activity("novel", limit=5)
    assert acts and acts[0]["amount"] == 500 and acts[0]["unit"] == "words"


def test_domains_summary(life_os, monkeypatch):
    _use(life_os, monkeypatch)
    rows = M.domains_summary(days=7)
    assert any(r["domain"] == "music-practice" for r in rows)
