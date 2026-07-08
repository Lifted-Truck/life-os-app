"""Life-OS MCP server — exposes deterministic progress data to AI tools (stdio).

A local, read-only MCP server that makes Life-OS a data source an external agent
can query — e.g. a tailored-exercise generator reading your music-practice
progress. It reuses the same `metrics` module the REST `/api/metrics` endpoints
use, so the numbers are identical and computed in one place.

Boundary (unchanged): no AI and no writes here. Life-OS *measures* logged
behavior deterministically; the consuming tool's AI decides what to do with it.

Run (stdio):
    venv/bin/python mcp_server.py

Register with Claude (Claude Desktop config / Claude Code MCP config):
    {
      "mcpServers": {
        "life-os": {
          "command": "/Users/machinepriest/Documents/Claude/life-os/life-os-app/venv/bin/python",
          "args": ["/Users/machinepriest/Documents/Claude/life-os/life-os-app/mcp_server.py"]
        }
      }
    }
LIFE_OS_ROOT is read from the app's .env (via utils), so the server finds the
data tree without extra config.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from metrics.aggregate import all_domains_summary, domain_progress
from scheduler.domains import list_domains as _list_domains
from scheduler.logs import domain_of, read_log_entries
from utils import get_life_os_root

mcp = FastMCP("life-os")


def _root():
    return get_life_os_root()


def _require_domain(root, domain: str) -> None:
    if domain not in _list_domains(root):
        raise ValueError(f"unknown domain {domain!r}; call list_domains() first")


@mcp.tool()
def list_domains() -> list:
    """List the Life-OS life domains available for progress queries."""
    return _list_domains(_root())


@mcp.tool()
def get_domain_progress(domain: str, days: int = 30, bucket: str = "day") -> dict:
    """Progress for one domain over the last `days`.

    Returns a time series (bucket = 'day' or 'week'), totals, current streak, and
    cadence adherence. Amounts are in the domain's own unit (minutes / words /
    pages / sessions); amount is null where the log recorded no quantity.
    """
    root = _root()
    _require_domain(root, domain)
    if bucket not in ("day", "week"):
        raise ValueError("bucket must be 'day' or 'week'")
    days = max(1, min(int(days), 365))
    return domain_progress(root, domain, days=days, bucket=bucket)


@mcp.tool()
def domains_summary(days: int = 30) -> list:
    """Per-domain progress summary (totals / streak / adherence) for all domains."""
    days = max(1, min(int(days), 365))
    return all_domains_summary(_root(), days=days)


@mcp.tool()
def get_recent_activity(domain: str, limit: int = 10) -> list:
    """The most recent logged entries for a domain, newest first."""
    root = _root()
    _require_domain(root, domain)
    limit = max(1, min(int(limit), 100))
    entries = [e for e in read_log_entries(root) if domain_of(e) == domain]
    entries.sort(key=lambda e: e.date, reverse=True)
    return [
        {"date": e.date.isoformat(), "outcome": e.outcome,
         "amount": e.amount, "unit": e.unit, "task": e.task_id}
        for e in entries[:limit]
    ]


# --- write tools (thin HTTPS clients to the VPS write API) -----------------
# These RECORD to Life-OS. They post to the write API (single write authority),
# so they need LIFE_OS_WRITE_TOKEN configured in THIS MCP's env; without it the
# server is read-only. Base URL defaults to the live hidden path; override with
# LIFE_OS_WRITE_URL for a different host.
import os

_WRITE_BASE = os.getenv(
    "LIFE_OS_WRITE_URL", "https://mindlathe.xyz/lathe/api/write").rstrip("/")


def _write(path: str, payload: dict) -> dict:
    token = os.getenv("LIFE_OS_WRITE_TOKEN", "").strip()
    if not token:
        raise ValueError(
            "recording is disabled: set LIFE_OS_WRITE_TOKEN in this MCP's env "
            "to enable the write tools")
    import httpx
    resp = httpx.post(f"{_WRITE_BASE}/{path}", json=payload,
                      headers={"Authorization": f"Bearer {token}"}, timeout=15)
    if resp.status_code >= 400:
        raise ValueError(f"write API {resp.status_code}: {resp.text[:200]}")
    return resp.json()


@mcp.tool()
def log_activity(domain: str, outcome: str = "done", amount: float = None,
                 unit: str = None, covered: str = None, task: str = None) -> dict:
    """Record a completed activity to today's log — e.g. music-practice, 30,
    "minutes". `amount`+`unit` populate the quantitative field that feeds the
    progress graphs. outcome ∈ done|partial|missed|rescheduled."""
    return _write("log", {"domain": domain, "outcome": outcome, "amount": amount,
                          "unit": unit, "covered": covered, "task": task})


@mcp.tool()
def capture_note(text: str, domain: str = None) -> dict:
    """Save a quick ingest note, optionally tagged to a domain."""
    return _write("note", {"text": text, "domain": domain})


@mcp.tool()
def capture_review(text: str, kind: str = "daily") -> dict:
    """Append a messy daily|weekly review stanza (same store the bot's /review
    writes to)."""
    return _write("review", {"text": text, "kind": kind})


@mcp.tool()
def add_inbox(text: str, due: str = None) -> dict:
    """Add an inbox item; optional `due` like 'hard 2026-07-15'."""
    return _write("inbox", {"text": text, "due": due})


if __name__ == "__main__":
    mcp.run()   # stdio transport
