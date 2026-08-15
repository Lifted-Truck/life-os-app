"""Write API — append-only recording primitives (write-mcp.md Phase 1).

Authenticated by ``LIFE_OS_WRITE_TOKEN`` — a SEPARATE, higher-privilege secret
than the dashboard read token. Each endpoint is a constrained, validated
primitive that appends to the data tree via the existing writers; there is no
arbitrary-file-write path. Writes land in the tree and the 5-min sync timer
commits + pushes them (git = the audit log).

Hard scope (write-mcp.md): these primitives can only append to daily/logs,
ingest/, daily/reviews, and inbox.md. They cannot touch the vault, thresholds,
schema, derived state, skills, or dev/ — there is simply no endpoint for it.

If ``LIFE_OS_WRITE_TOKEN`` is unset the whole write API is disabled (503) — a
write surface must never be open, unlike the read grace mode.
"""
import hmac
import os
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from bot_handlers.review import append_review
from dashboard.ratelimit import enforce_pre_auth, enforce_write, record_auth_failure
from scheduler.domains import list_domains
from utils import append_inbox, append_log_entry, get_life_os_root, write_ingest_note

router = APIRouter(prefix="/api/write", tags=["write"])

_OUTCOMES = ("done", "partial", "missed", "rescheduled")


def _write_token() -> str:
    return os.getenv("LIFE_OS_WRITE_TOKEN", "").strip()


def require_write_token(request: Request,
                        authorization: Optional[str] = Header(default=None)) -> None:
    """Bearer-only gate for the write API, rate-limited (Phase 3 hardening).

    Order is deliberate:
      1. rate-limit check on FAILED-auth budget — refuses a brute-force burst
         BEFORE the token compare (cheap, no timing surface, no file work);
      2. token compare (constant-time); a miss burns the caller's fail budget;
      3. successful-write budget — a leaked-but-valid token cannot flood.
    Deliberately NOT session-cookie: this is state-changing, so cookie auth
    would be CSRF-able (see app.require_token for the read-side contrast).
    """
    tok = _write_token()
    if not tok:
        raise HTTPException(status_code=503,
                            detail="write API disabled (LIFE_OS_WRITE_TOKEN unset)")
    key = enforce_pre_auth(request)                       # 429 if fail budget burned
    if not authorization or not hmac.compare_digest(authorization, f"Bearer {tok}"):
        record_auth_failure(key)
        raise HTTPException(status_code=401, detail="missing or invalid write token",
                            headers={"WWW-Authenticate": "Bearer"})
    enforce_write(key)                                    # 429 if write budget burned


def _require_domain(domain: Optional[str]) -> None:
    if domain and domain not in list_domains(get_life_os_root()):
        raise HTTPException(status_code=422, detail=f"unknown domain {domain!r}")


class LogBody(BaseModel):
    domain: str
    outcome: str = "done"
    amount: Optional[float] = None
    unit: Optional[str] = None
    covered: Optional[str] = None
    task: Optional[str] = None


class NoteBody(BaseModel):
    text: str
    domain: Optional[str] = None


class ReviewBody(BaseModel):
    text: str
    kind: str = "daily"


class InboxBody(BaseModel):
    text: str
    due: Optional[str] = None   # e.g. "hard 2026-07-15"


@router.post("/log", dependencies=[Depends(require_write_token)])
def w_log(b: LogBody) -> dict:
    _require_domain(b.domain)
    if b.outcome not in _OUTCOMES:
        raise HTTPException(status_code=422, detail=f"outcome must be one of {_OUTCOMES}")
    entry = {"date": date.today().isoformat(), "outcome": b.outcome, "domain": b.domain}
    if b.covered:
        entry["covered"] = b.covered
    if b.task:
        entry["task"] = b.task
    if b.amount is not None and b.unit:
        # Canonical `duration:` field carries the unit (DOMAIN-FORMAT §2).
        entry["duration"] = f"{b.amount:g} {b.unit}"
    append_log_entry(entry)
    return {"ok": True, "written": "daily/logs", "entry": entry}


@router.post("/note", dependencies=[Depends(require_write_token)])
def w_note(b: NoteBody) -> dict:
    _require_domain(b.domain)
    if not b.text.strip():
        raise HTTPException(status_code=422, detail="empty note text")
    rel = write_ingest_note(b.domain or "", b.text.strip())
    return {"ok": True, "written": rel}


@router.post("/review", dependencies=[Depends(require_write_token)])
def w_review(b: ReviewBody) -> dict:
    if b.kind not in ("daily", "weekly"):
        raise HTTPException(status_code=422, detail="kind must be 'daily' or 'weekly'")
    if not b.text.strip():
        raise HTTPException(status_code=422, detail="empty review text")
    path = append_review(get_life_os_root(), b.text.strip(), kind=b.kind)
    return {"ok": True, "written": path.name, "kind": b.kind}


@router.post("/inbox", dependencies=[Depends(require_write_token)])
def w_inbox(b: InboxBody) -> dict:
    text = b.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="empty inbox text")
    if b.due:
        text = f"{text} | due: {b.due.strip()}"
    append_inbox(text)
    return {"ok": True, "written": "inbox.md", "line": text}
