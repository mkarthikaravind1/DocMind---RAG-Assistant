# routes/feedback_routes.py
# Voting on an answer (its owner only) and the admin views of the votes.
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user, require_role
from feedback import RATINGS, REASONS, feedback_payload, set_feedback
from guardrails import check_pii_in_response
from models import Conversation, Evaluation, Feedback, Message, QueryLog, User

message_router = APIRouter()    # mounted at /messages
admin_router = APIRouter()      # mounted at /admin/feedback


class FeedbackRequest(BaseModel):
    rating: str | None = None    # "up", "down", or null to clear the vote
    reason: str | None = None    # optional, only with "down"


@message_router.put("/{message_id}/feedback")
def rate_answer(
    message_id: int,
    body: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.rating is not None and body.rating not in RATINGS:
        raise HTTPException(status_code=400, detail="Rating must be 'up', 'down' or null")
    if body.reason is not None and body.reason not in REASONS:
        raise HTTPException(status_code=400, detail="Unknown reason")
    if body.reason is not None and body.rating != "down":
        raise HTTPException(status_code=400, detail="A reason can only be given with a thumbs down")

    # Only an AI answer in one of the caller's own conversations can be rated.
    # Anything else looks exactly like a message that does not exist.
    message = (
        db.query(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(Message.id == message_id, Message.role == "ai",
                Conversation.user_id == current_user.id)
        .first()
    )
    if not message:
        raise HTTPException(status_code=404, detail="Answer not found")

    row = set_feedback(db, message_id, int(current_user.id), body.rating, body.reason)  # type: ignore[arg-type]
    return {"message_id": message_id, **feedback_payload(row)}


def _utc_iso(ts):
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


@admin_router.get("/stats")
def feedback_stats(
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    counts = dict(
        db.query(Feedback.rating, func.count(Feedback.id))
        .filter(Feedback.rating.isnot(None))
        .group_by(Feedback.rating)
        .all()
    )
    up, down = counts.get("up", 0), counts.get("down", 0)
    rated = up + down
    # Every answer saved since feedback exists has a row, rated or not
    answers = db.query(func.count(Feedback.id)).scalar() or 0
    reasons = dict(
        db.query(Feedback.reason, func.count(Feedback.id))
        .filter(Feedback.rating == "down", Feedback.reason.isnot(None))
        .group_by(Feedback.reason)
        .all()
    )
    return {
        "up":           up,
        "down":         down,
        "rated":        rated,
        "satisfaction": round(up / rated, 3) if rated else None,
        "answers":      answers,
        "rated_share":  round(rated / answers, 3) if answers else 0.0,
        "reasons":      {reason: reasons.get(reason, 0) for reason in REASONS},
    }


@admin_router.get("")
def recent_feedback(
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """The latest votes, newest first, with the question and its quality scores. No answer text."""
    rows = (
        db.query(Feedback, QueryLog, Evaluation)
        .outerjoin(QueryLog, QueryLog.id == Feedback.query_log_id)
        .outerjoin(Evaluation, Evaluation.query_log_id == Feedback.query_log_id)
        .filter(Feedback.rating.isnot(None))
        .order_by(Feedback.updated_at.desc(), Feedback.id.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "id":               fb.id,
            "query_log_id":     fb.query_log_id,
            "rating":           fb.rating,
            "reason":           fb.reason,
            # The question is the user's own text; redact any PII typed into it
            "question":         check_pii_in_response(str(log.question))[0] if log else None,
            "user_email":       log.user_email if log else None,
            "user_role":        log.user_role if log else None,
            "faithfulness":     ev.faithfulness if ev else None,
            "answer_relevancy": ev.answer_relevancy if ev else None,
            "timestamp":        _utc_iso(fb.updated_at),
        }
        for fb, log, ev in rows
    ]
