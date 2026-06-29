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


if __name__ == "__main__":
    mcp.run()   # stdio transport
