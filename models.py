from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from database import Base
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100))
    email = Column(String(100), unique=True, index=True)
    hashed_password = Column(String(255))
    role = Column(String(50), default="employee")

class Document(Base):
    __tablename__ = "documents"

    id            = Column(Integer, primary_key=True, index=True)
    filename      = Column(String(255), unique=True, index=True)
    allowed_roles = Column(String(100))       # comma-separated, e.g. "manager,admin"
    uploaded_by   = Column(String(100))
    chunks        = Column(Integer)
    uploaded_at   = Column(DateTime, default=utcnow)   # stored as UTC

class Conversation(Base):
    __tablename__ = "conversations"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, index=True)       # owner; conversations are private
    title      = Column(String(120))
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow)

class Message(Base):
    __tablename__ = "messages"

    id              = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, index=True)
    role            = Column(String(10))           # "user" or "ai"
    content         = Column(Text)
    sources         = Column(Text)                 # JSON list of cited sources (ai messages)
    created_at      = Column(DateTime, default=utcnow)

class QueryLog(Base):
    __tablename__ = "query_logs"
    id               = Column(Integer, primary_key=True, index=True)
    user_email       = Column(String(100))
    user_role        = Column(String(50))
    question         = Column(String(1000))
    answer_length    = Column(Integer)        # chars in response
    response_time    = Column(Float)          # seconds
    chunks_retrieved = Column(Integer)        # k value used
    guardrail_hit    = Column(String(100))    # None or violation type
    timestamp        = Column(DateTime, default=utcnow)   # stored as UTC
