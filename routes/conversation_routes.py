from datetime import timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from access import can_access, roles_from_str
from chat_history import get_owned_conversation, load_sources
from database import get_db
from dependencies import get_current_user
from models import Conversation, Document, Message, User

router = APIRouter()


def _iso(ts):
    """MySQL drops the timezone, so re-attach UTC before sending to the browser."""
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


@router.get("")
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The caller's own conversations, most recently used first."""
    rows = (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .limit(100)
        .all()
    )
    return [{"id": c.id, "title": c.title, "updated_at": _iso(c.updated_at)} for c in rows]


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = get_owned_conversation(db, int(current_user.id), conversation_id)  # type: ignore[arg-type]
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(Message.id)
        .all()
    )

    # Saved sources are a snapshot. If a document has since been deleted or
    # restricted, its excerpts are no longer shown when the chat is reopened.
    role = str(current_user.role)
    visible = {
        d.filename for d in db.query(Document).all()
        if can_access(role, roles_from_str(d.allowed_roles))
    }

    return {
        "id":    conv.id,
        "title": conv.title,
        "messages": [
            {
                "role":    m.role,
                "text":    m.content,
                "sources": [s for s in load_sources(m) if s.get("filename") in visible],
            }
            for m in messages
        ],
    }


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = get_owned_conversation(db, int(current_user.id), conversation_id)  # type: ignore[arg-type]
    db.query(Message).filter(Message.conversation_id == conv.id).delete()
    db.delete(conv)
    db.commit()
    return {"message": "Conversation deleted"}
