"""Web hub tests — auth gates + the four read views render against a fixture tree.

Uses FastAPI's TestClient (httpx) and the `life_os` conftest fixture, pointing
the app at it via LIFE_OS_ROOT. The dashboard token is read live, so tests set
it with monkeypatch to exercise the enabled/disabled (grace) paths.
"""
from fastapi.testclient import TestClient


def _client(life_os, monkeypatch, token="secret123"):
    monkeypatch.setenv("LIFE_OS_ROOT", str(life_os))
    if token is None:
        monkeypatch.delenv("LIFE_OS_DASHBOARD_TOKEN", raising=False)
    else:
        monkeypatch.setenv("LIFE_OS_DASHBOARD_TOKEN", token)
    from dashboard.app import app
    return TestClient(app)


def _login(client, token="secret123"):
    r = client.post("/login", data={"token": token}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"


# --- health + auth ---------------------------------------------------------

def test_health_is_open(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_html_redirects_to_login_when_unauthed(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_login_sets_cookie_and_grants_access(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    _login(c)
    r = c.get("/")
    assert r.status_code == 200
    assert "Today" in r.text


def test_bad_token_rejected(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    r = c.post("/login", data={"token": "wrong"}, follow_redirects=False)
    assert r.status_code == 401
    assert "Incorrect token" in r.text


def test_grace_mode_disables_auth_when_token_unset(life_os, monkeypatch):
    c = _client(life_os, monkeypatch, token=None)
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 200


# --- the four views render -------------------------------------------------

def test_views_render(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    _login(c)
    for path, needle in [
        ("/", "Today"),
        ("/domains", "career"),
        ("/domains/career", "Draft resume"),
        ("/logs", "Cadence health"),
        ("/system", "Bot commands"),
    ]:
        r = c.get(path)
        assert r.status_code == 200, f"{path} → {r.status_code}"
        assert needle in r.text, f"{needle!r} not in {path}"


def test_unknown_domain_404(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    _login(c)
    assert c.get("/domains/nonesuch").status_code == 404


# --- JSON API keeps the header-token gate ----------------------------------

def test_api_requires_bearer(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    assert c.get("/api/today").status_code == 401
    r = c.get("/api/today", headers={"Authorization": "Bearer secret123"})
    assert r.status_code == 200
    assert r.json()["mode"] in ("goals", "blocks")
