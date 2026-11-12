# tokens.py
# Refresh tokens: how a browser stays signed in while the access token (a JWT
# sent with every request) lives for only a few minutes.
#
#   * A refresh token is 256 random bits. Only its SHA-256 hash is stored, so a
#     copy of the database cannot be used to sign in.
#   * It travels in an httpOnly cookie that page JavaScript cannot read, and is
#     only sent to /auth/* (the cookie path).
#   * Rotation: each use retires the token and issues a new one in the same
#     "family". A retired token showing up again means it was copied, so the
#     whole family is revoked and the user must sign in again.
#   * Sign-out revokes the family on the server, not just in the browser.
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from sqlalchemy.orm import Session

from models import RefreshToken

load_dotenv()

COOKIE_NAME = "docmind_refresh"
COOKIE_PATH = "/auth"
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
# Must be 1 when the app is served over HTTPS. Off by default so plain
# http://localhost works.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
# "lax" suits a frontend and API on the same site (localhost:3000 + :8000, or
# app.example.com + api.example.com). Different sites need "none" + COOKIE_SECURE=1.
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax").lower()

# Two tabs can refresh at the same moment with the same cookie. A token that
# was retired only this many seconds ago is treated as that race, not as theft.
REUSE_GRACE_SECONDS = 10

# Origins allowed to call the API from a browser (also used for CORS in app.py).
# Comma-separated, e.g. CORS_ORIGINS=http://localhost:3000,https://myapp.com
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]


class RefreshError(Exception):
    """The refresh token cannot be used. `reason`: missing, unknown, revoked, expired or reuse."""

    def __init__(self, reason: str, user_id: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.user_id = user_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(ts: datetime) -> datetime:
    """MySQL returns naive datetimes; they were stored as UTC."""
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue(db: Session, user_id: int, family: str | None = None) -> str:
    """
    Create a refresh token and return its raw value (shown to the browser once,
    never stored). Does NOT commit: the caller commits it with the sign-in.
    """
    now = _now()
    # Housekeeping: this user's long-expired tokens are of no further use
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id, RefreshToken.expires_at < now - timedelta(days=1)
    ).delete(synchronize_session=False)

    raw = secrets.token_urlsafe(32)
    db.add(RefreshToken(
        user_id=user_id, token_hash=_hash(raw), family=family or secrets.token_hex(16),
        created_at=now, expires_at=now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    return raw


def revoke_family(db: Session, family: str) -> None:
    db.query(RefreshToken).filter(
        RefreshToken.family == family, RefreshToken.revoked_at.is_(None)
    ).update({RefreshToken.revoked_at: _now()}, synchronize_session=False)


def rotate(db: Session, raw: str | None) -> tuple[int, str]:
    """
    Exchange a refresh token for a new one. Returns (user id, new raw token)
    and commits. Raises RefreshError when the token cannot be used.
    """
    if not raw:
        raise RefreshError("missing")
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == _hash(raw)).first()
    if row is None:
        raise RefreshError("unknown")

    now = _now()
    user_id = int(row.user_id)  # type: ignore[arg-type]
    if row.revoked_at is not None:
        raise RefreshError("revoked", user_id)
    if _aware(row.expires_at) <= now:
        raise RefreshError("expired", user_id)

    if row.used_at is not None:
        if now - _aware(row.used_at) > timedelta(seconds=REUSE_GRACE_SECONDS):
            # A retired token came back: someone holds a copy. End every session of this family.
            revoke_family(db, str(row.family))
            db.commit()
            raise RefreshError("reuse", user_id)
        # else: two tabs refreshed together; give this one its own new token
    else:
        setattr(row, "used_at", now)

    new_raw = issue(db, user_id, family=str(row.family))
    db.commit()
    return user_id, new_raw


def revoke(db: Session, raw: str | None) -> int | None:
    """Sign-out: revoke the family this token belongs to. Returns the user id, if the token was known."""
    if not raw:
        return None
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == _hash(raw)).first()
    if row is None:
        return None
    revoke_family(db, str(row.family))
    db.commit()
    return int(row.user_id)  # type: ignore[arg-type]


def set_cookie(response, raw: str) -> None:
    response.set_cookie(
        COOKIE_NAME, raw,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        path=COOKIE_PATH, httponly=True, secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE,
    )


def clear_cookie(response) -> None:
    response.delete_cookie(
        COOKIE_NAME, path=COOKIE_PATH, httponly=True, secure=COOKIE_SECURE, samesite=COOKIE_SAMESITE,
    )


def origin_allowed(request) -> bool:
    """
    Extra protection for the cookie-authenticated endpoints: a browser always
    sends Origin on a cross-origin POST, so one from a site that is not ours is
    refused even if the browser ignored SameSite. Non-browser clients send none.
    """
    origin = request.headers.get("origin")
    return origin is None or origin in ALLOWED_ORIGINS
