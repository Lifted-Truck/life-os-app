"""Write-API rate limiting (write-mcp.md Phase 3) — dashboard/ratelimit.py.

Two layers:
  * unit — SlidingWindow with an INJECTED clock (deterministic; no sleeps, no
    wall-clock reads, per doctrine);
  * HTTP — the gate ordering + per-client isolation via X-Forwarded-For, which is
    the subtle property: behind Caddy every request looks like the same host, so
    without XFF a stranger's brute-force would lock the owner out.
"""
import pytest
from fastapi.testclient import TestClient

import dashboard.app as A
import dashboard.ratelimit as RL

WTOK = "write-secret-xyz"
GOOD = {"Authorization": f"Bearer {WTOK}"}
BAD = {"Authorization": "Bearer nope"}


@pytest.fixture(autouse=True)
def _fresh_buckets():
    RL.reset_all()
    yield
    RL.reset_all()


# --- unit: SlidingWindow with a fake clock ----------------------------------

class Clock:
    def __init__(self):
        self.t = 1000.0
    def __call__(self):
        return self.t


def test_window_allows_up_to_limit_then_denies():
    clk = Clock()
    w = RL.SlidingWindow(limit=3, window=60, clock=clk)
    for _ in range(3):
        assert w.check("k") is None
        w.hit("k")
    wait = w.check("k")
    assert wait is not None and 0 < wait <= 60


def test_window_slides_open_after_window_elapses():
    clk = Clock()
    w = RL.SlidingWindow(limit=2, window=60, clock=clk)
    w.hit("k"); w.hit("k")
    assert w.check("k") is not None
    clk.t += 61                                # oldest hit ages out
    assert w.check("k") is None


def test_window_retry_after_is_time_until_oldest_expires():
    clk = Clock()
    w = RL.SlidingWindow(limit=1, window=100, clock=clk)
    w.hit("k")
    clk.t += 30
    wait = w.check("k")
    assert wait == pytest.approx(70)


def test_window_keys_are_independent():
    clk = Clock()
    w = RL.SlidingWindow(limit=1, window=60, clock=clk)
    w.hit("a")
    assert w.check("a") is not None
    assert w.check("b") is None


# NB: client keys below are opaque labels, not IPs, on purpose — the limiter
# keys on whatever string XFF carries, and this is a PUBLIC repo whose ip_gate
# should never be taught to ignore test files.
def test_client_key_prefers_first_xff_hop():
    class Req:
        headers = {"x-forwarded-for": "client-a, proxy-hop"}
        client = type("C", (), {"host": "loopback"})()
    assert RL.client_key(Req()) == "client-a"


def test_client_key_falls_back_to_client_host():
    class Req:
        headers = {}
        client = type("C", (), {"host": "loopback"})()
    assert RL.client_key(Req()) == "loopback"


# --- HTTP: gate ordering + per-client isolation ------------------------------

def _client(life_os, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(life_os))
    monkeypatch.setenv("LIFE_OS_WRITE_TOKEN", WTOK)
    return TestClient(A.app)


def _xff(ip, base):
    return {**base, "X-Forwarded-For": ip}


def test_failed_auth_budget_yields_429_with_retry_after(life_os, monkeypatch):
    monkeypatch.setattr(RL.fail_bucket, "limit", 3)
    c = _client(life_os, monkeypatch)
    for _ in range(3):
        assert c.post("/api/write/inbox", json={"text": "x"},
                      headers=_xff("attacker-1", BAD)).status_code == 401
    r = c.post("/api/write/inbox", json={"text": "x"}, headers=_xff("attacker-1", BAD))
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1


def test_burned_fail_budget_blocks_even_a_correct_token(life_os, monkeypatch):
    """Brute-force refusal happens BEFORE the token compare (the ordering)."""
    monkeypatch.setattr(RL.fail_bucket, "limit", 2)
    c = _client(life_os, monkeypatch)
    for _ in range(2):
        c.post("/api/write/inbox", json={"text": "x"}, headers=_xff("attacker-2", BAD))
    r = c.post("/api/write/inbox", json={"text": "x"}, headers=_xff("attacker-2", GOOD))
    assert r.status_code == 429


def test_other_clients_unaffected_by_one_clients_brute_force(life_os, monkeypatch):
    """The XFF property: a stranger hammering must not lock the owner out."""
    monkeypatch.setattr(RL.fail_bucket, "limit", 2)
    c = _client(life_os, monkeypatch)
    for _ in range(3):
        c.post("/api/write/inbox", json={"text": "x"}, headers=_xff("stranger", BAD))
    r = c.post("/api/write/inbox", json={"text": "legit"}, headers=_xff("owner", GOOD))
    assert r.status_code == 200


def test_successful_write_budget_yields_429(life_os, monkeypatch):
    monkeypatch.setattr(RL.write_bucket, "limit", 3)
    c = _client(life_os, monkeypatch)
    for i in range(3):
        assert c.post("/api/write/inbox", json={"text": f"n{i}"},
                      headers=_xff("flooder", GOOD)).status_code == 200
    r = c.post("/api/write/inbox", json={"text": "n3"}, headers=_xff("flooder", GOOD))
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_correct_token_does_not_burn_fail_budget(life_os, monkeypatch):
    """Successful auths must never count against the failed-auth bucket."""
    monkeypatch.setattr(RL.fail_bucket, "limit", 1)
    c = _client(life_os, monkeypatch)
    for i in range(3):
        assert c.post("/api/write/inbox", json={"text": f"ok{i}"},
                      headers=_xff("regular", GOOD)).status_code == 200


def test_disabled_api_still_503_before_any_limiting(life_os, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(life_os))
    monkeypatch.delenv("LIFE_OS_WRITE_TOKEN", raising=False)
    c = TestClient(A.app)
    assert c.post("/api/write/inbox", json={"text": "x"}, headers=GOOD).status_code == 503


def test_read_api_is_not_rate_limited_by_write_buckets(life_os, monkeypatch):
    """Scope: the cap is on the WRITE surface only."""
    monkeypatch.setattr(RL.fail_bucket, "limit", 1)
    monkeypatch.setenv("LIFE_OS_DASHBOARD_TOKEN", "readtok")
    c = _client(life_os, monkeypatch)
    for _ in range(3):
        c.post("/api/write/inbox", json={"text": "x"}, headers=_xff("probe", BAD))
    r = c.get("/api/today", headers=_xff("probe", {"Authorization": "Bearer readtok"}))
    assert r.status_code == 200
