# audit.py
# Audit trail: a permanent record of who changed what, and of security events.
# Separate from the query log, which only covers chat questions.
#
# Rows are only ever inserted. Nothing in the application updates or deletes
# them, and there is no API that can.
#
# A change and its audit row are written in the SAME database transaction
# (add() then the endpoint's own commit), so a change cannot be saved without
# its record. Events that change nothing (logins, denials, failures) are
# written with record(), which never raises: auditing must not turn a refused
# request into a server error.
#
# Details hold structured values only (roles, counts, reasons): never document
# text, passwords or tokens.
import json
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from guardrails import PII_PATTERNS
from models import AuditLog

# action -> what it records
ACTIONS = {
    "role_change":     "A user's role was changed",
    "document_upload": "A document was uploaded or replaced",
    "document_delete": "A document was deleted",
    "access_change":   "A document's audience was changed",
    "user_register":   "An account was created",
    "login":           "A successful sign-in",
    "login_failed":    "A failed sign-in attempt",
    "access_denied":   "A signed-in user was refused a protected action",
}
SUCCESS, FAILED, DENIED = "success", "failed", "denied"

_TARGET_CHARS = 255
_DETAILS_CHARS = 2000


def actor(user) -> dict:
    """Keyword arguments naming the signed-in user as the actor."""
    return {"actor_email": str(user.email), "actor_role": str(user.role)}


def add(db: Session, action: str, *, actor_email=None, actor_role=None,
        target=None, details: dict | None = None, outcome: str = SUCCESS) -> None:
    """
    Add an audit row to the session WITHOUT committing. The caller's commit
    then saves the change and its record together, or neither.
    """
    if action not in ACTIONS:
        raise ValueError(f"Unknown audit action: {action}")
    db.add(AuditLog(
        timestamp=datetime.now(timezone.utc),
        actor_email=(actor_email or None) and str(actor_email)[:100],
        actor_role=(actor_role or None) and str(actor_role)[:50],
        action=action,
        target=(target or None) and str(target)[:_TARGET_CHARS],
        details=json.dumps(details, default=str)[:_DETAILS_CHARS] if details else None,
        outcome=outcome,
    ))


def record(db: Session, action: str, **fields) -> None:
    """Add an audit row and commit it now. Never raises."""
    try:
        add(db, action, **fields)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[AUDIT] Could not record {action}: {e}")


# Emails identify the actor and the target account, so they stay readable
# (as on the Users tab). Everything else the PII guardrail knows is redacted.
_REDACT = [re.compile(p) for label, p in PII_PATTERNS.items() if label != "email"]


def _redact(value):
    if isinstance(value, str):
        for pattern in _REDACT:
            value = pattern.sub("[REDACTED]", value)
        return value
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    return value


def _utc_iso(ts):
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


def payload(row: AuditLog) -> dict:
    """One event as the API returns it."""
    try:
        details = json.loads(str(row.details)) if row.details else {}
    except ValueError:
        details = {}
    return {
        "id":          row.id,
        "timestamp":   _utc_iso(row.timestamp),
        "actor_email": row.actor_email,
        "actor_role":  row.actor_role,
        "action":      row.action,
        "target":      _redact(row.target),
        "details":     _redact(details),
        "outcome":     row.outcome,
    }
