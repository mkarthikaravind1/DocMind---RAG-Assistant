#app.py
import os
import shutil
import time
from datetime import datetime, timezone

from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import engine, Base, get_db
from dependencies import get_current_user, require_role
from guardrails import validate_input
from ingest import ingest_pdf, delete_document_chunks, IngestError
from models import User, QueryLog
from rag import get_answer
from routes.auth_routes import router as auth_router

# Create DB tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI()

# Comma-separated list, e.g. CORS_ORIGINS=http://localhost:3000,https://myapp.com
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "documents")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Include auth routes
app.include_router(auth_router, prefix="/auth")


def safe_pdf_name(filename: str) -> str:
    """
    Strip any directory part (blocks ../ path traversal) and
    make sure only PDFs inside UPLOAD_DIR can be touched.
    """
    name = os.path.basename(filename.replace("\\", "/")).strip()
    if not name or name in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    return name


# NOTE: routes that do blocking work (embedding, LLM calls, DB) are plain `def`
# so FastAPI runs them in a threadpool instead of freezing the event loop.

# ── Protected routes ───────────────────────────────────────────────
@app.get("/files")
def list_docs(current_user: User = Depends(get_current_user)):
    files = sorted(f for f in os.listdir(UPLOAD_DIR) if f.lower().endswith(".pdf"))
    return {"docs": files}

# ── Manager + Admin only ───────────────────────────────────────────
@app.post("/upload")
def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(require_role("admin", "manager")),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    filename  = safe_pdf_name(file.filename)
    file_path = os.path.join(UPLOAD_DIR, filename)
    already_existed = os.path.exists(file_path)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        chunks = ingest_pdf(file_path)
    except IngestError as e:
        _cleanup_failed_upload(file_path, filename)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # A file that was never indexed must not show up as "Ready"
        _cleanup_failed_upload(file_path, filename)
        print(f"[UPLOAD] Ingestion failed for {filename}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Could not index this file. Check that it is a valid PDF and that ChromaDB is running.",
        )

    return {
        "filename": filename,
        "status":   "replaced and re-ingested" if already_existed else "uploaded and ingested",
        "chunks":   chunks,
    }


def _cleanup_failed_upload(file_path: str, filename: str) -> None:
    if os.path.exists(file_path):
        os.remove(file_path)
    try:
        delete_document_chunks(filename)
    except Exception:
        pass  # vector store unreachable: nothing was stored anyway

# ── Admin only ─────────────────────────────────────────────────────
@app.delete("/delete/{filename}")
def delete_file(
    filename: str,
    current_user: User = Depends(require_role("admin"))
):
    filename  = safe_pdf_name(filename)
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    # Remove the vectors first, so a deleted document can no longer be used in answers
    try:
        delete_document_chunks(filename)
    except Exception as e:
        print(f"[DELETE] Could not remove chunks for {filename}: {e}")
        raise HTTPException(
            status_code=503,
            detail="Could not reach the vector store. The document was not deleted.",
        )

    os.remove(file_path)
    return {"message": f"{filename} deleted successfully"}

class ChatRequest(BaseModel):
    question: str

# ── Admin: list all users ──────────────────────────────────────────
@app.get("/admin/users")
def get_users(
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db)
):
    users = db.query(User).all()
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role} for u in users]

# ── Admin: update a user's role ────────────────────────────────────
class RoleUpdateRequest(BaseModel):
    role: str

@app.patch("/admin/users/{user_id}/role")
def update_role(
    user_id: int,
    body: RoleUpdateRequest,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db)
):
    if body.role not in ("admin", "manager", "employee"):
        raise HTTPException(status_code=400, detail="Invalid role")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id is not None and current_user.id is not None:
        if int(user.id) == int(current_user.id): # type: ignore
            raise HTTPException(status_code=400, detail="Cannot change your own role")

    setattr(user,"role",body.role)
    db.commit()
    return {"message": f"{user.email} is now {body.role}"}

# ── Chat ───────────────────────────────────────────────────────────
@app.post("/chat")
def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    question = request.question.strip()

    # ── Guardrail check ───────────────────────────────────────────
    error = validate_input(question)
    if error:
        # Log the guardrail violation
        log = QueryLog(
            user_email       = str(current_user.email),
            user_role        = str(current_user.role),
            question         = question[:500],
            answer_length    = 0,
            response_time    = 0.0,
            chunks_retrieved = 0,
            guardrail_hit    = error[:100],
            timestamp        = datetime.now(timezone.utc),
        )
        db.add(log)
        db.commit()
        raise HTTPException(status_code=400, detail=error)

    # ── RAG call with timing ──────────────────────────────────────
    start = time.time()
    try:
        result = get_answer(question)
    except Exception as e:
        print(f"[CHAT] RAG pipeline failed: {e}")
        raise HTTPException(
            status_code=503,
            detail="The answer service is unavailable right now. Please try again in a moment.",
        )
    elapsed = round(time.time() - start, 3)

    answer           = result["answer"]
    chunks_retrieved = result["chunks_retrieved"]

    # ── Log to DB ─────────────────────────────────────────────────
    log = QueryLog(
        user_email       = str(current_user.email),
        user_role        = str(current_user.role),
        question         = question[:500],
        answer_length    = len(answer),
        response_time    = elapsed,
        chunks_retrieved = chunks_retrieved,
        guardrail_hit    = None,
        timestamp        = datetime.now(timezone.utc),
    )
    db.add(log)
    db.commit()

    return {"answer": answer, "user": current_user.email}


def _utc_iso(ts):
    """MySQL drops the timezone, so re-attach UTC before sending to the browser."""
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()

# ── Admin: view logs ───────────────────────────────────────────────
@app.get("/admin/logs")
def get_logs(
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db)
):
    logs = db.query(QueryLog).order_by(QueryLog.timestamp.desc()).limit(100).all()
    return [
        {
            "id":               l.id,
            "user_email":       l.user_email,
            "user_role":        l.user_role,
            "question":         l.question,
            "answer_length":    l.answer_length,
            "response_time":    l.response_time,
            "chunks_retrieved": l.chunks_retrieved,
            "guardrail_hit":    l.guardrail_hit,
            "timestamp":        _utc_iso(l.timestamp),
        }
        for l in logs
    ]

# ── Admin: log summary stats ───────────────────────────────────────
@app.get("/admin/logs/stats")
def get_stats(
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db)
):
    # Aggregated in SQL (no loading every row into memory)
    total      = db.query(func.count(QueryLog.id)).scalar() or 0
    violations = (
        db.query(func.count(QueryLog.id))
        .filter(QueryLog.guardrail_hit.isnot(None))
        .scalar()
        or 0
    )
    # Averages only cover answered queries; blocked ones would drag them to 0
    avg_time, avg_chunks = (
        db.query(func.avg(QueryLog.response_time), func.avg(QueryLog.chunks_retrieved))
        .filter(QueryLog.guardrail_hit.is_(None))
        .one()
    )

    return {
        "total_queries":        total,
        "avg_response_time":    round(float(avg_time or 0), 3),
        "guardrail_violations": violations,
        "avg_chunks":           round(float(avg_chunks or 0), 2),
    }
