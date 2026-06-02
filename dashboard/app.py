"""Minimal Life-OS dashboard — placeholder served behind Caddy on the VPS.

This is the *first* HTTP surface. It exists to:
  1. Verify the Caddy + Let's Encrypt + reverse-proxy stack works end-to-end.
  2. Give the bot somewhere to grow toward (webhook endpoints, status pages).

It serves today's plan as JSON, plus a /health probe Caddy and Ionos can hit
without authentication. Everything else can grow later.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import FastAPI

from scheduler.compile_queue import load_queue
from scheduler.day import build_result
from scheduler.day_template import load_day_template
from scheduler.goals import split_goals
from scheduler.mode import load_mode
from utils import get_life_os_root

app = FastAPI(
    title="Life-OS",
    description="Personal automation layer — bot + scheduler + dashboard.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    """Unauthenticated probe Caddy / Ionos can hit. Returns 200 if the app is up."""
    return {"status": "ok"}


@app.get("/")
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


@app.get("/today")
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
