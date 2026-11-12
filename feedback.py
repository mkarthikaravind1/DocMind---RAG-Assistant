# feedback.py
# Answer feedback: a thumbs up / thumbs down (with an optional preset reason
# for a thumbs down) on each AI answer.
#
# One row per answer in its own table. The row is created when the answer is
# saved, which links the saved message to its query log, so a vote can be shown
# next to that query and its quality scores in the admin dashboard. The rating
# is filled in when the user votes.
#
# Only a rating and a preset reason are stored: no free text, so feedback can
# never carry PII or document content into the admin view.
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import Feedback

RATINGS = ("up", "down")
# Offered after a thumbs down. Keys are stored; the labels live in the frontend.
REASONS = ("wrong_answer", "missing_info", "wrong_source", "not_relevant")


def link_answer(db: Session, message_id: int, query_log_id: int, user_id: int) -> None:
    """
    Remember which query log a saved answer belongs to. Never raises: feedback
    bookkeeping must not be able to break a chat response.
    """
    try:
        db.add(Feedback(message_id=message_id, query_log_id=query_log_id, user_id=user_id,
                        created_at=datetime.now(timezone.utc)))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[FEEDBACK] Could not link answer {message_id} to its query log: {e}")


def set_feedback(db: Session, message_id: int, user_id: int, rating, reason) -> Feedback:
    """
    Store a vote on an answer. rating None clears it. A reason is only kept
    with a thumbs down. The caller has already checked ownership.
    """
    row = db.query(Feedback).filter(Feedback.message_id == message_id).first()
    if row is None:
        # An answer saved before feedback existed has no row yet
        row = Feedback(message_id=message_id, user_id=user_id, created_at=datetime.now(timezone.utc))
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            # Another request created it a moment ago
            db.rollback()
            row = db.query(Feedback).filter(Feedback.message_id == message_id).one()

    setattr(row, "rating", rating)
    setattr(row, "reason", reason if rating == "down" else None)
    setattr(row, "updated_at", datetime.now(timezone.utc))
    db.commit()
    return row


def feedback_payload(row: Feedback | None) -> dict:
    """The vote as the API returns it (both None when the answer is not rated)."""
    return {
        "rating": row.rating if row else None,
        "reason": row.reason if row else None,
    }


def detach_messages(db: Session, message_ids: list[int]) -> None:
    """
    Called when a conversation is deleted. The votes stay as statistics (they
    hold no message text), but let go of the message ids, so a vote can never
    end up attached to a different, later message that reuses an id.
    Does not commit: the caller's delete and this happen together.
    """
    if message_ids:
        db.query(Feedback).filter(Feedback.message_id.in_(message_ids)).update(
            {Feedback.message_id: None}, synchronize_session=False
        )
