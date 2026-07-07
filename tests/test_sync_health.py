"""/health sync-staleness signal — reads the sync heartbeat file."""
import time

import dashboard.app as app


def test_health_sync_age_none_when_no_heartbeat(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "_sync_heartbeat_path", lambda: tmp_path / "nope")
    h = app.health()
    assert h["status"] == "ok"
    assert h["sync_age_seconds"] is None and h["sync_ok"] is False


def test_health_sync_ok_when_recent(monkeypatch, tmp_path):
    hb = tmp_path / "last-sync"
    hb.write_text(str(int(time.time()) - 60), encoding="utf-8")   # 1 min ago
    monkeypatch.setattr(app, "_sync_heartbeat_path", lambda: hb)
    h = app.health()
    assert 55 <= h["sync_age_seconds"] <= 120 and h["sync_ok"] is True


def test_health_sync_stale_flagged(monkeypatch, tmp_path):
    hb = tmp_path / "last-sync"
    hb.write_text(str(int(time.time()) - 3600), encoding="utf-8")  # 1 h ago
    monkeypatch.setattr(app, "_sync_heartbeat_path", lambda: hb)
    h = app.health()
    assert h["sync_age_seconds"] >= 3600 and h["sync_ok"] is False


def test_health_sync_age_survives_garbage(monkeypatch, tmp_path):
    hb = tmp_path / "last-sync"
    hb.write_text("not-a-number", encoding="utf-8")
    monkeypatch.setattr(app, "_sync_heartbeat_path", lambda: hb)
    assert app.health()["sync_age_seconds"] is None
