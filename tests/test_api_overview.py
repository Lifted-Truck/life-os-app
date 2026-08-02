"""GET /api/overview — the contract life-os-web consumes (BR-1 + BR-2).

Contract tests as requested in life-os-web/BACKEND-REQUESTS.md: they run against
the temp `life_os` fixture tree so they stay env-independent (the deploy gate
runs pytest with the VPS .env — never assert on real-tree values or literal paths).
"""
from fastapi.testclient import TestClient

import dashboard.app as A
from dashboard.overview_data import build_overview
from scheduler.domains import list_domains


def _client(life_os, monkeypatch, token="secret123"):
    monkeypatch.setenv("LIFE_OS_ROOT", str(life_os))
    monkeypatch.setenv("LIFE_OS_DASHBOARD_TOKEN", token)
    return TestClient(A.app)


H = {"Authorization": "Bearer secret123"}


def test_api_overview_is_gated(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    assert c.get("/api/overview").status_code == 401


def test_shape_and_row_count(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    d = c.get("/api/overview", headers=H).json()
    assert set(d) >= {"date", "spark_days", "pulse", "umbrellas", "rows"}
    assert len(d["rows"]) == len(list_domains(life_os))
    assert d["pulse"]["total"] == len(d["rows"])


def test_every_spark_has_spark_days_entries(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    d = c.get("/api/overview", headers=H).json()
    assert d["spark_days"] > 0
    for r in d["rows"]:
        assert len(r["spark"]) == d["spark_days"], r["domain"]


def test_pulse_carries_the_fields_the_client_rendered_as_na(life_os, monkeypatch):
    """The five values that had no endpoint before BR-1."""
    c = _client(life_os, monkeypatch)
    p = c.get("/api/overview", headers=H).json()["pulse"]
    for k in ("populated", "total", "plan_mode", "streak", "lint_err",
              "lint_warn", "sync_age_seconds", "sync_ok", "rev"):
        assert k in p, k
    assert isinstance(p["populated"], int) and isinstance(p["streak"], int)


def test_rows_arrive_in_display_order(life_os, monkeypatch):
    """populated → started → untouched, then name. Client must not re-sort."""
    c = _client(life_os, monkeypatch)
    rows = c.get("/api/overview", headers=H).json()["rows"]
    rank = {"populated": 0, "started": 1, "untouched": 2}
    keys = [(rank[r["state"]], r["domain"]) for r in rows]
    assert keys == sorted(keys)


def test_umbrellas_served_so_client_need_not_mirror_yaml(life_os, monkeypatch):
    """BR-2: grouping comes from the API; each row carries its umbrella KEY."""
    (life_os / "dev").mkdir(parents=True, exist_ok=True)
    (life_os / "dev" / "domain-groups.yaml").write_text(
        "umbrellas:\n"
        "  - key: health\n    label: \"Health & Body\"\n    domains: [fitness, meals]\n",
        encoding="utf-8")
    c = _client(life_os, monkeypatch)
    d = c.get("/api/overview", headers=H).json()
    assert {"key": "health", "label": "Health & Body",
            "domains": ["fitness", "meals"]} in d["umbrellas"]
    by = {r["domain"]: r["umbrella"] for r in d["rows"]}
    if "fitness" in by:
        assert by["fitness"] == "health"          # key, not label


def test_missing_groups_file_degrades_not_errors(life_os, monkeypatch):
    """groups.py tolerance must survive into the API (no 500 on a bad tree)."""
    c = _client(life_os, monkeypatch)
    r = c.get("/api/overview", headers=H)
    assert r.status_code == 200
    assert isinstance(r.json()["umbrellas"], list)


def test_session_cookie_also_works(life_os, monkeypatch):
    """The SPA's actual auth path (no token in client JS)."""
    c = _client(life_os, monkeypatch)
    c.post("/login", data={"token": "secret123"}, follow_redirects=False)
    assert c.get("/api/overview").status_code == 200


def test_html_and_json_surfaces_share_one_computation(life_os, monkeypatch):
    """BR-1's real point: /overview and /api/overview cannot drift."""
    monkeypatch.setenv("LIFE_OS_ROOT", str(life_os))
    monkeypatch.setenv("LIFE_OS_DASHBOARD_TOKEN", "secret123")
    c = TestClient(A.app)
    api = c.get("/api/overview", headers=H).json()
    direct = build_overview(life_os)          # what the Jinja route calls
    assert [r["domain"] for r in api["rows"]] == [r["domain"] for r in direct["rows"]]
    assert api["pulse"]["total"] == direct["pulse"]["total"]

    c.post("/login", data={"token": "secret123"}, follow_redirects=False)
    assert c.get("/overview").status_code == 200   # page still renders
