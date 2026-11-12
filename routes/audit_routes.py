# routes/audit_routes.py
# Admin-only, read-only view of the audit trail (see audit.py).
# There is deliberately no route that edits or deletes an audit row.
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import audit
from database import get_db
from dependencies import require_role
from models import AuditLog, User

router = APIRouter()


@router.get("")
def list_audit_events(
    action: str | None = None,                    # one of audit.ACTIONS
    actor: str | None = None,                     # exact email of who did it
    outcome: str | None = None,                   # success | failed | denied
    limit: int = Query(50, ge=1, le=200),
    before: int | None = Query(None, ge=1),       # paging: only events older than this id
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Newest first. Pass the returned `next_before` as `before` to load the next page."""
    if action is not None and action not in audit.ACTIONS:
        raise HTTPException(status_code=400, detail="Unknown action")
    if outcome is not None and outcome not in (audit.SUCCESS, audit.FAILED, audit.DENIED):
        raise HTTPException(status_code=400, detail="Unknown outcome")

    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if actor:
        query = query.filter(AuditLog.actor_email == actor.strip().lower())
    if outcome:
        query = query.filter(AuditLog.outcome == outcome)
    if before:
        query = query.filter(AuditLog.id < before)

    # Ids only ever grow, so they give a stable newest-first order even when
    # several events share the same second.
    rows = query.order_by(AuditLog.id.desc()).limit(limit + 1).all()
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "events":      [audit.payload(r) for r in rows],
        "next_before": rows[-1].id if more else None,
        "actions":     list(audit.ACTIONS),
    }
