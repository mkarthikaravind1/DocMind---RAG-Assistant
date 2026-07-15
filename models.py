from sqlalchemy import Column, Integer, String, Float, DateTime
from database import Base
from datetime import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100))
    email = Column(String(100), unique=True, index=True)
    hashed_password = Column(String(255))
    role = Column(String(50), default="employee")

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
    timestamp        = Column(DateTime, default=datetime.utcnow)