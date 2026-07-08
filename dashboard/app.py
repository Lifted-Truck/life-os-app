"""Life-OS web hub — server-rendered FastAPI dashboard behind Caddy on the VPS.

Phase 1: a read-only hub across four surfaces — Today, Domains, Logs, System —
plus the original JSON API (moved under ``/api/*``) and an unauthenticated
``/health`` probe.

Two auth surfaces share one secret (``LIFE_OS_DASHBOARD_TOKEN``):
  * Browser pages use a login form → signed session cookie (a browser can't send
    an ``Authorization`` header on navigation).
  * ``/api/*`` keeps the header-based ``Authorization: Bearer <token>`` flow for
    programmatic callers.
If the token env var is unset, BOTH are disabled (local dev / first-boot grace).

Governing principle (unchanged): AI may interpret language; AI may NOT make
scheduling decisions. This hub only reads — no AI anywhere in it.
"""
from __future__ import annotations

import hmac
import os
import time
from datetime import date, timedelta
from pathlib import Path

import markdown as _md
import yaml
from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from commands_doc import COMMAND_REGISTRY
from metrics.aggregate import all_domains_summary, domain_progress, series
from scheduler.domains import list_domains, read_thresholds
from scheduler.logs import read_log_entries
from scheduler.compile_queue import load_queue
from scheduler.day import build_result
from scheduler.day_template import load_day_template
from scheduler.goals import split_goals
from scheduler.logs import (
    completions_this_week,
    last_completion_for_domain,
    read_log_entries,
)
from scheduler.mode import load_mode
from scheduler.tasks_parser import parse_tasks_file
from scheduler.urgency import cadence_debt_urgency
from utils import get_life_os_root

BASE = Path(__file__).resolve().parent

# External URL prefix when the hub is mounted under a secret path (so the
# domain root can host a separate public site). Env-driven; empty = served at
# the domain root, which is the default for local dev and tests. Templates get
# it as `{{ p }}`; redirects prepend it via _redirect().
HUB_PREFIX = os.getenv("LIFE_OS_HUB_PREFIX", "").rstrip("/")

templates = Jinja2Templates(directory=str(BASE / "templates"))
templates.env.globals["p"] = HUB_PREFIX


def _redirect(path: str, status: int = 303) -> RedirectResponse:
    """Redirect to an internal path, honoring the hidden-hub prefix."""
    return RedirectResponse(HUB_PREFIX + path, status_code=status)


# --- auth ------------------------------------------------------------------

def _token() -> str:
    """Current dashboard token, read live so .env changes need only a restart."""
    return os.getenv("LIFE_OS_DASHBOARD_TOKEN", "").strip()


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Header-based gate for /api/* — Authorization: Bearer <token>."""
    expected = _token()
    if not expected:
        return
    if not authorization or not hmac.compare_digest(authorization, f"Bearer {expected}"):
        raise HTTPException(
            status_code=401,
            detail="missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )


class _NotAuthenticated(Exception):
    """Raised by require_session so the handler can redirect to /login."""


def require_session(request: Request) -> None:
    """Cookie-session gate for HTML pages. Token unset → disabled (grace)."""
    if not _token():
        return
    if not request.session.get("auth"):
        raise _NotAuthenticated()


app = FastAPI(
    title="Life-OS",
    description="Personal automation layer — bot + scheduler + web hub.",
    version="0.2.0",
    # NB: no FastAPI root_path. Caddy strips the hidden prefix (handle_path), so
    # the app runs as a normal root app; all EXTERNAL links carry the prefix via
    # {{ p }} / _redirect(). Setting root_path here made StaticFiles expect the
    # prefix while Caddy stripped it → CSS 404. Keeping them decoupled is robust.
)
# Stable signing secret across restarts so cookies survive deploys. Falls back
# to a dev value when the token is unset (auth disabled anyway in that case).
app.add_middleware(
    SessionMiddleware,
    secret_key=_token() or "life-os-dev-insecure-secret",
    same_site="lax",
)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

# Write API (append-only primitives, gated by LIFE_OS_WRITE_TOKEN) — write-mcp.md
from dashboard.write import router as _write_router  # noqa: E402
app.include_router(_write_router)


@app.exception_handler(_NotAuthenticated)
async def _login_redirect(request: Request, exc: _NotAuthenticated):
    return _redirect("/login")


# --- small helpers ---------------------------------------------------------

def _safe_read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _render_md(text: str | None) -> str | None:
    """Render markdown → HTML. Single-tenant own content; not sanitized."""
    if text is None:
        return None
    return _md.markdown(text, extensions=["tables", "fenced_code"])


def _domain_names(root: Path) -> set:
    """Canonical domain set for this tree (see scheduler.domains.list_domains)."""
    return set(list_domains(root))


def _group_by_domain(tasks: list) -> list[tuple[str, list]]:
    """Preserve incoming (urgency) order; group consecutive-by-domain."""
    groups: list[tuple[str, list]] = []
    index: dict[str, int] = {}
    for t in tasks:
        d = t.domain or "—"
        if d not in index:
            index[d] = len(groups)
            groups.append((d, []))
        groups[index[d]][1].append(t)
    return groups


# --- health (unauthenticated; auto-deploy polls its rev) -------------------

def _sync_heartbeat_path() -> Path:
    """Where sync-data-tree.sh records its last fully-successful cycle."""
    return Path.home() / ".cache" / "life-os" / "last-sync"


def _sync_age_seconds():
    """Seconds since the data-tree sync last succeeded, or None if unknown."""
    try:
        last = int(_sync_heartbeat_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return max(0, int(time.time()) - last)


@app.get("/health")
def health() -> dict:
    age = _sync_age_seconds()
    return {
        "status": "ok",
        "rev": _read_rev(),
        # None until the first sync heartbeat exists (fresh box / local dev).
        "sync_age_seconds": age,
        "sync_ok": age is not None and age <= 1200,
    }


def _read_rev() -> str:
    """Best-effort short git SHA of the running checkout."""
    try:
        head = BASE.parent / ".git" / "HEAD"
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref: "):
            return (BASE.parent / ".git" / ref[5:]).read_text(encoding="utf-8").strip()[:8]
        return ref[:8]
    except OSError:
        return "unknown"


# --- login / logout --------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if not _token() or request.session.get("auth"):
        return _redirect("/")
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login_submit(request: Request, token: str = Form(default="")):
    expected = _token()
    if not expected:
        return _redirect("/")
    if hmac.compare_digest(token, expected):
        request.session["auth"] = True
        return _redirect("/")
    return templates.TemplateResponse(
        request, "login.html", {"error": "Incorrect token."}, status_code=401,
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return _redirect("/login")


# --- HTML views ------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_session)])
def today_view(request: Request):
    root = get_life_os_root()
    d = date.today()
    mode = load_mode(root)
    ctx: dict = {"request": request, "nav": "today", "date": d.isoformat(), "mode": mode}
    if mode["plan_mode"] == "goals":
        try:
            tasks, _lint, _gen = load_queue(root)
        except OSError:
            tasks = []
        anchors, live, waiting, blocked = split_goals(tasks, d)
        ctx.update(view="goals", anchors=anchors, live_groups=_group_by_domain(live),
                   waiting=waiting, blocked=blocked)
    else:
        try:
            result, _state = build_result(root, d)
            ctx.update(view="blocks", assignments=result.assignments, carried=result.carried)
        except OSError:
            ctx.update(view="blocks", assignments=[], carried=[])
    return templates.TemplateResponse(request, "today.html", ctx)


@app.get("/domains", response_class=HTMLResponse, dependencies=[Depends(require_session)])
def domains_view(request: Request):
    root = get_life_os_root()
    thresholds = read_thresholds(root)
    entries = read_log_entries(root)
    d = date.today()
    rows = []
    for name in sorted(_domain_names(root)):
        cfg = thresholds.get(name, {})
        last = last_completion_for_domain(entries, name)
        rows.append({
            "name": name,
            "cadence": cfg.get("cadence"),
            "unit": cfg.get("unit"),
            "last": last.isoformat() if last else None,
            "week": completions_this_week(entries, name, d),
            "has_tasks": (root / "domains" / name / "tasks.md").exists(),
        })
    return templates.TemplateResponse(
        request, "domains.html", {"nav": "domains", "domains": rows})


@app.get("/domains/{name}", response_class=HTMLResponse,
         dependencies=[Depends(require_session)])
def domain_detail(request: Request, name: str):
    root = get_life_os_root()
    if name not in _domain_names(root):           # validates + blocks traversal
        raise HTTPException(status_code=404, detail="unknown domain")
    ddir = root / "domains" / name
    tasks: list = []
    tasks_path = ddir / "tasks.md"
    if tasks_path.exists():
        _next, tasks, _lint = parse_tasks_file(tasks_path, name)
    entries = read_log_entries(root)
    last = last_completion_for_domain(entries, name)
    ctx = {
        "request": request, "nav": "domains", "name": name,
        "cfg": read_thresholds(root).get(name, {}),
        "readme_html": _render_md(_safe_read(ddir / "README.md")),
        "goals_html": _render_md(_safe_read(ddir / "goals.md")),
        "tasks": tasks,
        "last": last.isoformat() if last else None,
        "week": completions_this_week(entries, name, date.today()),
    }
    return templates.TemplateResponse(request, "domain_detail.html", ctx)


@app.get("/logs", response_class=HTMLResponse, dependencies=[Depends(require_session)])
def logs_view(request: Request):
    root = get_life_os_root()
    entries = read_log_entries(root)
    d = date.today()
    thresholds = read_thresholds(root)

    recent = []
    logs_dir = root / "daily" / "logs"
    if logs_dir.is_dir():
        for p in sorted(logs_dir.glob("*.md"), reverse=True)[:14]:
            recent.append({"name": p.stem, "html": _render_md(p.read_text(encoding="utf-8"))})

    summary = []
    for name in sorted(_domain_names(root)):
        cfg = thresholds.get(name, {})
        last = last_completion_for_domain(entries, name)
        debt = cadence_debt_urgency(cfg.get("cadence"), last, d, cfg.get("days"))
        summary.append({
            "domain": name,
            "week": completions_this_week(entries, name, d),
            "last": last.isoformat() if last else None,
            "days_since": (d - last).days if last else None,
            "debt": round(debt, 1),
        })
    return templates.TemplateResponse(
        request, "logs.html", {"nav": "logs", "recent": recent, "summary": summary})


@app.get("/system", response_class=HTMLResponse, dependencies=[Depends(require_session)])
def system_view(request: Request):
    root = get_life_os_root()
    mode = load_mode(root)
    try:
        _tasks, lint, generated = load_queue(root)
    except OSError:
        lint, generated = [], None
    groups: list[tuple[str, list]] = []
    seen: dict[str, int] = {}
    for group, cmd, desc in COMMAND_REGISTRY:
        if group not in seen:
            seen[group] = len(groups)
            groups.append((group, []))
        groups[seen[group]][1].append((cmd, desc))
    ctx = {
        "request": request, "nav": "system",
        "rev": _read_rev(), "mode": mode, "generated": generated, "lint": lint,
        "command_groups": groups,
        "handoff_html": _render_md(_safe_read(root / "dev" / "handoff.md")),
        "todo_html": _render_md(_safe_read(root / "dev" / "TODO.md")),
        "commands_html": _render_md(_safe_read(root / "dev" / "bot-commands.md")),
    }
    return templates.TemplateResponse(request, "system.html", ctx)


# --- overview (the live system map) ----------------------------------------

def _age_label(sec) -> str:
    if sec is None:
        return "unknown"
    if sec < 90:
        return f"{sec}s ago"
    if sec < 5400:
        return f"{sec // 60} min ago"
    return f"{sec // 3600}h ago"


def _walkthrough_status(root: Path) -> dict:
    """domain -> 'populated' | 'started' from dev/walkthrough-state.yaml."""
    try:
        data = yaml.safe_load(
            (root / "dev" / "walkthrough-state.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    out = {}
    for dom, rec in (data or {}).items():
        if not isinstance(rec, dict):
            continue
        status = str(rec.get("status", ""))
        done = rec.get("scopes_done") or []
        out[dom] = "populated" if status.upper().startswith("POPULATED") or len(done) >= 5 \
            else "started"
    return out


@app.get("/overview", response_class=HTMLResponse, dependencies=[Depends(require_session)])
def overview(request: Request):
    root = get_life_os_root()
    today = date.today()
    entries = read_log_entries(root)
    th = read_thresholds(root)
    walk = _walkthrough_status(root)
    domains = list_domains(root)

    SPARK_DAYS = 21
    rows = []
    for d in domains:
        ser = series(entries, d, today - timedelta(days=SPARK_DAYS - 1), today, "day")
        counts = [p["completions"] for p in ser["points"]]
        cfg = th.get(d, {})
        rows.append({
            "domain": d,
            "state": walk.get(d, "untouched"),   # populated | started | untouched
            "cadence": cfg.get("cadence"),
            "has_cadence": bool(cfg.get("cadence")),
            "spark": counts,
            "spark_max": max(counts) if counts else 0,
            "recent": sum(counts[-7:]),
        })
    # frontier first: populated on top, then started, then untouched; then name
    order = {"populated": 0, "started": 1, "untouched": 2}
    rows.sort(key=lambda r: (order[r["state"]], r["domain"]))

    populated_n = sum(1 for r in rows if r["state"] == "populated")
    mode = load_mode(root)
    try:
        _t, lint, generated = load_queue(root)
    except OSError:
        lint, generated = [], None

    # logging streak (any completion) + latest review capture
    logged_days = sorted({e.date for e in entries if e.outcome in ("done", "partial")})
    streak = 0
    probe = today
    logged_set = set(logged_days)
    while probe in logged_set:
        streak += 1
        probe -= timedelta(days=1)

    latest_review = None
    rdir = root / "daily" / "reviews"
    if rdir.is_dir():
        files = sorted(rdir.glob("*.md"))
        if files:
            latest_review = {"name": files[-1].stem,
                             "html": _render_md(files[-1].read_text(encoding="utf-8"))}

    sync_age = _sync_age_seconds()
    pulse = {
        "populated": populated_n,
        "total": len(rows),
        "mode": mode["plan_mode"],
        "lint_warn": sum(1 for i in lint if i.level == "warning"),
        "lint_err": sum(1 for i in lint if i.level == "error"),
        "streak": streak,
        "sync_label": _age_label(sync_age),
        "sync_ok": sync_age is not None and sync_age <= 1200,
        "rev": _read_rev(),
    }
    return templates.TemplateResponse(
        request, "overview.html",
        {"nav": "overview", "rows": rows, "pulse": pulse,
         "latest_review": latest_review, "spark_days": SPARK_DAYS})


# --- JSON API (header-token auth; preserves the old / and /today shapes) ---

@app.get("/api/", dependencies=[Depends(require_token)])
def api_index() -> dict:
    root = get_life_os_root()
    mode = load_mode(root)
    return {
        "app": "Life-OS",
        "date": date.today().isoformat(),
        "plan_mode": mode["plan_mode"],
        "haiku_phrasing": mode["haiku_phrasing"],
        "links": ["/api/today", "/health"],
    }


@app.get("/api/today", dependencies=[Depends(require_token)])
def api_today() -> dict:
    root = get_life_os_root()
    d = date.today()
    mode = load_mode(root)
    if mode["plan_mode"] == "goals":
        try:
            tasks, _lint, _gen = load_queue(root)
        except OSError:
            tasks = []
        anchors, live, waiting, blocked = split_goals(tasks, d)
        return {
            "mode": "goals", "date": d.isoformat(),
            "anchors": [{"title": t.title,
                         "time": t.placement.window[0] if t.placement.window else None}
                        for t in anchors],
            "live": [{"domain": t.domain, "title": t.title, "urgency": t.urgency}
                     for t in live],
            "waiting": [{"title": t.title} for t in waiting],
            "blocked": [{"title": t.title, "reason": t.blocked_reason} for t in blocked],
        }
    try:
        result, _state = build_result(root, d)
    except OSError:
        return {"mode": "blocks", "date": d.isoformat(), "blocks": []}
    return {
        "mode": "blocks", "date": d.isoformat(),
        "blocks": [
            {"name": a.block["name"], "start": a.block["start"], "end": a.block["end"],
             "slot": a.block["slot"], "task": a.task.title if a.task else None,
             "domain": a.task.domain if a.task else None}
            for a in result.assignments
        ],
        "carried": [{"id": t.id, "title": t.title} for t in result.carried],
    }


@app.get("/api/metrics", dependencies=[Depends(require_token)])
def api_metrics(days: int = Query(30, ge=1, le=365)) -> dict:
    """Per-domain progress summary (no full series) — the metrics index."""
    root = get_life_os_root()
    return {
        "date": date.today().isoformat(),
        "days": days,
        "domains": all_domains_summary(root, days=days),
    }


@app.get("/api/metrics/{domain}", dependencies=[Depends(require_token)])
def api_metrics_domain(
    domain: str,
    days: int = Query(30, ge=1, le=365),
    bucket: str = Query("day", pattern="^(day|week)$"),
) -> dict:
    """Full progress payload (series + summary) for one domain."""
    root = get_life_os_root()
    if domain not in list_domains(root):
        raise HTTPException(status_code=404, detail="unknown domain")
    return domain_progress(root, domain, days=days, bucket=bucket)
