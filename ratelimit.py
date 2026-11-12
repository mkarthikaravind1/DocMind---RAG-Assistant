# ratelimit.py
# Rate limiting: a small in-memory sliding-window limiter.
#
# The backend runs as ONE uvicorn process, so plain memory is enough (no Redis).
# The counters reset when the backend restarts, and would have to move to a
# shared store if the app were ever run with several workers.
#
# Limits are written as "count/seconds" and can be overridden in .env:
#   RATE_LIMIT_LOGIN      failed sign-ins per ACCOUNT   (default 5 per 5 minutes)
#   RATE_LIMIT_LOGIN_IP   sign-in attempts per IP       (default 30 per 5 minutes)
#   RATE_LIMIT_REGISTER   new accounts per IP           (default 5 per hour)
#   RATE_LIMIT_CHAT       questions per user            (default 20 per minute)
#   RATE_LIMIT_UPLOAD     uploads per user              (default 10 per 10 minutes)
#   RATE_LIMIT_ENABLED=0  switches all of them off
import math
import os
import threading
import time
from collections import deque

from dotenv import load_dotenv
from fastapi import HTTPException

import audit

load_dotenv()

ENABLED = os.getenv("RATE_LIMIT_ENABLED", "1") == "1"
_MAX_KEYS = 10_000      # above this, keys with nothing left in their window are dropped


def _now() -> float:
    """Monotonic seconds (the test suite replaces this with a fake clock)."""
    return time.monotonic()


class SlidingWindow:
    """At most `limit` hits per key within any `window` seconds."""

    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque] = {}
        self._refused: dict[str, float] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque:
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        return hits

    def retry_after(self, key: str) -> int:
        """0 when another hit is allowed, otherwise the seconds until one is."""
        with self._lock:
            now = _now()
            hits = self._recent(key, now)
            if len(hits) < self.limit:
                return 0
            return max(1, math.ceil(hits[0] + self.window - now))

    def hit(self, key: str) -> None:
        with self._lock:
            now = _now()
            self._recent(key, now).append(now)
            if len(self._hits) > _MAX_KEYS:
                for k in [k for k, v in self._hits.items() if not self._recent(k, now)]:
                    del self._hits[k]

    def consume(self, key: str) -> int:
        """Count one hit if allowed and return 0; otherwise return the wait in seconds."""
        wait = self.retry_after(key)
        if not wait:
            self.hit(key)
        return wait

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
            self._refused.pop(key, None)

    def first_refusal(self, key: str) -> bool:
        """True once per window per key, so a flood of refused requests writes ONE audit row."""
        with self._lock:
            now = _now()
            last = self._refused.get(key)
            if last is not None and last > now - self.window:
                return False
            self._refused[key] = now
            return True

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()
            self._refused.clear()


def _parse(value: str, default: tuple[int, int]) -> tuple[int, int]:
    try:
        count, seconds = value.split("/")
        count, seconds = int(count), int(seconds)
        if count < 1 or seconds < 1:
            raise ValueError
        return count, seconds
    except (ValueError, AttributeError):
        return default


_DEFAULTS = {
    "login":    ("RATE_LIMIT_LOGIN",    (5, 300)),
    "login_ip": ("RATE_LIMIT_LOGIN_IP", (30, 300)),
    "register": ("RATE_LIMIT_REGISTER", (5, 3600)),
    "chat":     ("RATE_LIMIT_CHAT",     (20, 60)),
    "upload":   ("RATE_LIMIT_UPLOAD",   (10, 600)),
}
LIMITS = {
    name: SlidingWindow(*_parse(os.getenv(env, ""), default))
    for name, (env, default) in _DEFAULTS.items()
}


def reset_all() -> None:
    for limiter in LIMITS.values():
        limiter.clear()


def _wait_text(seconds: int) -> str:
    if seconds >= 120:
        return f"{math.ceil(seconds / 60)} minutes"
    return f"{seconds} second{'s' if seconds != 1 else ''}"


def refuse(name: str, key: str, wait: int, message: str, *, db=None, **audit_fields):
    """
    Raise the 429 for a limit that was hit. The first refusal in a window is
    written to the audit trail; the rest are not, so the limiter cannot be used
    to flood it.
    """
    if db is not None and LIMITS[name].first_refusal(key):
        audit.record(db, "rate_limited", outcome=audit.DENIED,
                     details={"limit": name, "retry_after": wait}, **audit_fields)
    raise HTTPException(
        status_code=429,
        detail=f"{message} Try again in {_wait_text(wait)}.",
        headers={"Retry-After": str(wait)},
    )


def enforce(name: str, key: str, message: str, *, db=None, **audit_fields) -> None:
    """Count one request against a limit, or raise 429 if the limit is reached."""
    if not ENABLED:
        return
    wait = LIMITS[name].consume(key)
    if wait:
        refuse(name, key, wait, message, db=db, **audit_fields)


def check(name: str, key: str, message: str, *, db=None, **audit_fields) -> None:
    """Raise 429 if the limit is already reached, WITHOUT counting this request."""
    if not ENABLED:
        return
    wait = LIMITS[name].retry_after(key)
    if wait:
        refuse(name, key, wait, message, db=db, **audit_fields)


def count(name: str, key: str) -> None:
    if ENABLED:
        LIMITS[name].hit(key)
