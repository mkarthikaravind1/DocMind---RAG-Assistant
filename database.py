from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv
from urllib.parse import quote_plus
import os

load_dotenv()

# quote_plus keeps passwords containing @ : / # from breaking the URL
DB_URL = (
    f"mysql+pymysql://{quote_plus(os.getenv('MYSQL_USER', 'root'))}:"
    f"{quote_plus(os.getenv('MYSQL_PASSWORD', ''))}"
    f"@{os.getenv('MYSQL_HOST', 'localhost')}:{os.getenv('MYSQL_PORT', '3306')}"
    f"/{os.getenv('MYSQL_DB')}"
)

# pool_pre_ping / pool_recycle stop "MySQL server has gone away" after idle periods
engine = create_engine(DB_URL, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
