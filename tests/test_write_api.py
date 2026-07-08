"""Write API — append-only primitives + the write-token gate (write-mcp.md P1)."""
from datetime import date

from fastapi.testclient import TestClient

import dashboard.app as A

WTOK = "write-secret-xyz"
H = {"Authorization": f"Bearer {WTOK}"}


def _client(life_os, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(life_os))
    monkeypatch.setenv("LIFE_OS_WRITE_TOKEN", WTOK)
    return TestClient(A.app)


# --- auth gate -------------------------------------------------------------

def test_write_requires_token(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    assert c.post("/api/write/log", json={"domain": "coding"}).status_code == 401
    assert c.post("/api/write/log", json={"domain": "coding"},
                  headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_write_disabled_when_token_unset(life_os, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(life_os))
    monkeypatch.delenv("LIFE_OS_WRITE_TOKEN", raising=False)
    c = TestClient(A.app)
    r = c.post("/api/write/log", json={"domain": "coding"}, headers=H)
    assert r.status_code == 503   # never open


# --- primitives ------------------------------------------------------------

def test_log_writes_entry_with_amount(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    r = c.post("/api/write/log",
               json={"domain": "music-practice", "amount": 30, "unit": "minutes",
                     "covered": "scales"}, headers=H)
    assert r.status_code == 200 and r.json()["ok"]
    today = date.today().isoformat()
    text = (life_os / "daily" / "logs" / f"{today}.md").read_text(encoding="utf-8")
    assert "duration:** 30 minutes" in text and "music-practice" in text


def test_log_rejects_unknown_domain_and_outcome(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    assert c.post("/api/write/log", json={"domain": "nope"}, headers=H).status_code == 422
    assert c.post("/api/write/log", json={"domain": "career", "outcome": "vibes"},
                  headers=H).status_code == 422


def test_note_and_review_and_inbox(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    assert c.post("/api/write/note", json={"text": "idea: X", "domain": "music-practice"},
                  headers=H).json()["ok"]
    assert (life_os / "ingest").glob("*.md")

    rv = c.post("/api/write/review", json={"text": "rough day", "kind": "daily"}, headers=H)
    assert rv.json()["ok"]
    today = date.today().isoformat()
    assert "rough day" in (life_os / "daily" / "reviews" / f"{today}.md").read_text(encoding="utf-8")

    ib = c.post("/api/write/inbox", json={"text": "call plumber", "due": "hard 2026-07-20"},
                headers=H)
    assert ib.json()["ok"]
    inbox = (life_os / "inbox.md").read_text(encoding="utf-8")
    assert "call plumber | due: hard 2026-07-20" in inbox


def test_bad_kind_and_empty_rejected(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    assert c.post("/api/write/review", json={"text": "x", "kind": "monthly"},
                  headers=H).status_code == 422
    assert c.post("/api/write/inbox", json={"text": "   "}, headers=H).status_code == 422
