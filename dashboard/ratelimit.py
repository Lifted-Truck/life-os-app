"""Rate limiting for the write API — write-mcp.md Phase 3 hardening.

Why this exists: the VPS address is public (autonomous-lifeos-001), so the write
endpoint is findable. Auth already bounds the blast radius (a valid token can
only append low-stakes, git-tracked records; a bad token gets 401). A rate cap
closes the two things auth alone does not:

  1. token brute-force — hammering the 401 path;
  2. nuisance flooding — a leaked-but-valid token filling the data tree.

So two buckets per client, with different budgets: FAILED auth attempts are
capped tightly, SUCCESSFUL writes generously (a human logging a busy day must
never hit it; a script pouring thousands in must).

Design (deliberate, all deterministic — no AI, no external service):
- Sliding window per client, in-process. Single-process single-tenant app, so a
  dict of timestamps is correct, dependency-free, and testable. State resets on
  restart, which is fine: an attacker cannot cause a restart, and a legitimate
  caller loses nothing.
- The check runs BEFORE token comparison, so a brute-force burst is refused
  before the constant-time compare and any file work.
- 429 + `Retry-After` — standard and machine-readable, so the MCP client can
  surface it instead of retrying blindly.
- Buckets only ever DENY; nothing here can grant access. Fail-safe by shape.

Client identity: Caddy is the sole ingress and reverse-proxies to this app, so
`request.client.host` is always the proxy hop (observed live: the VPS's own
address). We therefore read `X-Forwarded-For` (Caddy sets it by default) and
take the FIRST hop = the real client. LOAD-BEARING ASSUMPTION: this is safe ONLY
because port 8000 is not reachable from outside (ufw allows 22/80/443 only), so
a client cannot spoof XFF by bypassing Caddy. If the app is ever exposed
directly, this must change to trusting only the proxy's rightmost hop.

Limits are module constants overridable by env — for tests and for tuning
without a code change — never by request.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


# Failed-auth budget: tight. 10 bad tokens per 10 min per client is far more
# than any legitimate misconfiguration produces, and makes brute-force absurd.
FAIL_LIMIT = _env_int("LIFE_OS_WRITE_FAIL_LIMIT", 10)
FAIL_WINDOW = _env_int("LIFE_OS_WRITE_FAIL_WINDOW", 600)      # seconds

# Successful-write budget: generous. 120 writes per 10 min per client — a human
# can't approach it; a runaway loop or a leaked-token flood hits it fast.
WRITE_LIMIT = _env_int("LIFE_OS_WRITE_LIMIT", 120)
WRITE_WINDOW = _env_int("LIFE_OS_WRITE_WINDOW", 600)          # seconds

# Bound memory: forget clients we haven't seen for a full window. Prevents a
# scan across many spoofed sources from growing the table without limit.
_MAX_CLIENTS = 10_000


class SlidingWindow:
    """Per-key sliding-window counter. Deterministic given a clock."""

    def __init__(self, limit: int, window: int, clock=time.monotonic):
        self.limit = limit
        self.window = window
        self._clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque:
        q = self._hits[key]
        cutoff = now - self.window
        while q and q[0] <= cutoff:
            q.popleft()
        return q

    def _evict_idle(self, now: float) -> None:
        if len(self._hits) <= _MAX_CLIENTS:
            return
        cutoff = now - self.window
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= cutoff]:
            del self._hits[k]

    def check(self, key: str) -> float | None:
        """Seconds until the key is allowed again, or None if it is under the limit."""
        with self._lock:
            now = self._clock()
            q = self._prune(key, now)
            if len(q) >= self.limit:
                return max(0.0, self.window - (now - q[0]))
            return None

    def hit(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            self._evict_idle(now)
            self._prune(key, now).append(now)

    def reset(self) -> None:          # tests
        with self._lock:
            self._hits.clear()


fail_bucket = SlidingWindow(FAIL_LIMIT, FAIL_WINDOW)
write_bucket = SlidingWindow(WRITE_LIMIT, WRITE_WINDOW)


def client_key(request: Request) -> str:
    """Real client identity behind the proxy (see module docstring)."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def _too_many(retry_after: float, what: str) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=f"rate limit exceeded ({what}); retry later",
        headers={"Retry-After": str(int(retry_after) + 1)},
    )


def enforce_pre_auth(request: Request) -> str:
    """Refuse clients that have burned their failed-auth budget. Returns the key.

    Runs BEFORE the token compare so a brute-force burst never reaches it.
    """
    key = client_key(request)
    wait = fail_bucket.check(key)
    if wait is not None:
        raise _too_many(wait, "too many failed authentications")
    return key


def record_auth_failure(key: str) -> None:
    fail_bucket.hit(key)


def enforce_write(key: str) -> None:
    """Refuse a client that has burned its successful-write budget."""
    wait = write_bucket.check(key)
    if wait is not None:
        raise _too_many(wait, "too many writes")
    write_bucket.hit(key)


def reset_all() -> None:              # tests
    fail_bucket.reset()
    write_bucket.reset()
