"""Minimal Life-OS dashboard — placeholder served behind Caddy on the VPS.

This is the *first* HTTP surface. It exists to:
  1. Verify the Caddy + Let's Encrypt + reverse-proxy stack works end-to-end.
  2. Give the bot somewhere to grow toward (webhook endpoints, status pages).

It serves today's plan as JSON, plus a /health probe Caddy and Ionos can hit
without authentication. Authenticated endpoints require an
``Authorization: Bearer <LIFE_OS_DASHBOARD_TOKEN>`` header; if the env var
is unset, auth is disabled (local dev / first-boot grace).
"""
from __future__ import annotations

import hmac
import os
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException

from scheduler.compile_queue import load_queue
from scheduler.day import build_result
from scheduler.day_template import load_day_template
from scheduler.goals import split_goals
from scheduler.mode import load_mode
from utils import get_life_os_root


# Read once at module-load — restart picks up changes (which auto-deploy does
# on every code push, and a manual `systemctl restart life-os-dashboard`
# picks up .env-only changes).
DASHBOARD_TOKEN = os.getenv("LIFE_OS_DASHBOARD_TOKEN", "").strip()


def require_token(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency: enforce Authorization: Bearer <token>.

    Constant-time compare against LIFE_OS_DASHBOARD_TOKEN. If the env var is
    unset/empty, auth is disabled — keeps local dev and first-boot working
    without ceremony. Production: set the env var on the VPS.
    """
    if not DASHBOARD_TOKEN:
        return
    expected = f"Bearer {DASHBOARD_TOKEN}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(
            status_code=401,
            detail="missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

app = FastAPI(
    title="Life-OS",
    description="Personal automation layer — bot + scheduler + dashboard.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    """Unauthenticated probe Caddy / Ionos can hit. Returns 200 if the app is up.

    Carries the build revision so an auto-deploy can be verified end-to-end
    by polling /health and watching `rev` change after a push.
    """
    return {"status": "ok", "rev": _read_rev()}


def _read_rev() -> str:
    """Best-effort: short git SHA of the currently-running checkout."""
    try:
        head = Path(__file__).resolve().parent.parent / ".git" / "HEAD"
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref: "):
            ref_path = Path(__file__).resolve().parent.parent / ".git" / ref[5:]
            return ref_path.read_text(encoding="utf-8").strip()[:8]
        return ref[:8]
    except OSError:
        return "unknown"


@app.get("/", dependencies=[Depends(require_token)])
def index() -> dict:
    """Top-level state — today's mode and a one-line summary."""
    root = get_life_os_root()
    today = date.today()
    mode = load_mode(root)
    return {
        "app": "Life-OS",
        "date": today.isoformat(),
        "plan_mode": mode["plan_mode"],
        "haiku_phrasing": mode["haiku_phrasing"],
        "links": ["/today", "/health"],
    }


@app.get("/today", dependencies=[Depends(require_token)])
def today() -> dict:
    """Today's plan rendered in JSON, mode-aware."""
    root = get_life_os_root()
    d = date.today()
    mode = load_mode(root)

    if mode["plan_mode"] == "goals":
        try:
            tasks, _lint, _gen = load_queue(root)
        except (OSError, FileNotFoundError):
            tasks = []
        anchors, live, waiting, blocked = split_goals(tasks, d)
        return {
            "mode": "goals",
            "date": d.isoformat(),
            "anchors": [{"title": t.title, "time": t.placement.window[0]
                         if t.placement.window else None}
                        for t in anchors],
            "live": [{"domain": t.domain, "title": t.title, "urgency": t.urgency}
                     for t in live],
            "waiting": [{"title": t.title} for t in waiting],
            "blocked": [{"title": t.title, "reason": t.blocked_reason}
                        for t in blocked],
        }

    # blocks mode — return the placement
    try:
        result, _state = build_result(root, d)
    except (OSError, FileNotFoundError):
        return {"mode": "blocks", "date": d.isoformat(), "blocks": []}
    return {
        "mode": "blocks",
        "date": d.isoformat(),
        "blocks": [
            {
                "name": a.block["name"],
                "start": a.block["start"],
                "end": a.block["end"],
                "slot": a.block["slot"],
                "task": a.task.title if a.task else None,
                "domain": a.task.domain if a.task else None,
            }
            for a in result.assignments
        ],
        "carried": [{"id": t.id, "title": t.title} for t in result.carried],
    }
