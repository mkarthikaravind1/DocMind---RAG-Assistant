# chat_history.py
# Saved conversations: storage helpers shared by the chat endpoints.
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Conversation, Message

HISTORY_TURNS = 3          # how many past question/answer pairs feed follow-up rewriting
TITLE_CHARS   = 60


def get_owned_conversation(db: Session, user_id: int, conversation_id: int) -> Conversation:
    """
    The conversation, but only if it belongs to this user.
    Someone else's conversation looks exactly like one that does not exist (404).
    """
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


def recent_history(db: Session, conversation_id: int) -> list[tuple[str, str]]:
    """The last few messages, oldest first, as (role, content) pairs."""
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(HISTORY_TURNS * 2)
        .all()
    )
    return [(str(m.role), str(m.content)) for m in reversed(rows)]


def save_exchange(
    db: Session,
    user_id: int,
    conversation_id: int | None,
    question: str,
    answer: str,
    sources: list,
) -> int:
    """
    Store one question/answer pair and return the conversation id.
    A new conversation is created here (not earlier), so a failed or blocked
    first question never leaves an empty conversation behind.
    """
    now = datetime.now(timezone.utc)

    conv = None
    if conversation_id is not None:
        conv = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .first()
        )
    if conv is None:
        title = " ".join(question.split())
        if len(title) > TITLE_CHARS:
            title = title[:TITLE_CHARS].rstrip() + "…"
        conv = Conversation(user_id=user_id, title=title, created_at=now)
        db.add(conv)
        db.flush()   # assigns conv.id

    setattr(conv, "updated_at", now)
    db.add(Message(conversation_id=conv.id, role="user", content=question, created_at=now))
    db.add(Message(
        conversation_id=conv.id, role="ai", content=answer,
        sources=json.dumps(sources or []), created_at=now,
    ))
    db.commit()
    return int(conv.id)  # type: ignore[arg-type]


def load_sources(message: Message) -> list:
    try:
        data = json.loads(str(message.sources)) if message.sources else []
        return data if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []
