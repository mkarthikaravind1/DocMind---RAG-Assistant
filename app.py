#app.py
import os
import shutil
import time
from datetime import datetime, timezone

from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from access import DEFAULT_ROLES, can_access, normalize_roles, roles_from_str, roles_to_str
from database import engine, Base, get_db
from dependencies import get_current_user, require_role
from guardrails import validate_input
from ingest import ingest_pdf, delete_document_chunks, set_document_roles, IngestError
from models import User, QueryLog, Document
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
def _doc_payload(doc: Document) -> dict:
    return {
        "filename":      doc.filename,
        "allowed_roles": roles_from_str(doc.allowed_roles),
        "uploaded_by":   doc.uploaded_by,
        "indexed":       True,
    }


@app.get("/files")
def list_docs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Only the documents the caller's role is allowed to see."""
    role = str(current_user.role)
    records = db.query(Document).order_by(Document.filename).all()

    documents = [
        _doc_payload(d) for d in records
        if can_access(role, roles_from_str(d.allowed_roles))
    ]

    # PDFs on disk with no access record (uploaded before document-level RBAC
    # existed) are not searchable. Only admins see them, flagged for re-upload.
    if role == "admin":
        known = {d.filename for d in records}
        for f in sorted(os.listdir(UPLOAD_DIR)):
            if f.lower().endswith(".pdf") and f not in known:
                documents.append({
                    "filename": f, "allowed_roles": ["admin"],
                    "uploaded_by": None, "indexed": False,
                })

    return {
        "docs":      [d["filename"] for d in documents if d["indexed"]],
        "documents": documents,
    }

# ── Manager + Admin only ───────────────────────────────────────────
@app.post("/upload")
def upload_file(
    file: UploadFile = File(...),
    # Comma-separated roles allowed to read the document, e.g. "manager,admin"
    allowed_roles: str = Form(",".join(DEFAULT_ROLES)),
    current_user: User = Depends(require_role("admin", "manager")),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    role = str(current_user.role)
    try:
        roles = normalize_roles(allowed_roles)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not can_access(role, roles):
        raise HTTPException(
            status_code=400,
            detail="You cannot upload a document that your own role is not allowed to access.",
        )

    filename  = safe_pdf_name(file.filename)
    file_path = os.path.join(UPLOAD_DIR, filename)

    record = db.query(Document).filter(Document.filename == filename).first()
    # A manager must not be able to overwrite (or learn the contents of)
    # a document that is restricted to admins.
    if record and not can_access(role, roles_from_str(record.allowed_roles)):
        raise HTTPException(
            status_code=409,
            detail="A document with this name already exists. Please rename your file.",
        )
    already_existed = record is not None or os.path.exists(file_path)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        chunks = ingest_pdf(file_path, roles)
    except IngestError as e:
        _cleanup_failed_upload(file_path, filename, db)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # A file that was never indexed must not show up as "Ready"
        _cleanup_failed_upload(file_path, filename, db)
        print(f"[UPLOAD] Ingestion failed for {filename}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Could not index this file. Check that it is a valid PDF and that ChromaDB is running.",
        )

    if record is None:
        record = Document(filename=filename)
        db.add(record)
    setattr(record, "allowed_roles", roles_to_str(roles))
    setattr(record, "uploaded_by", str(current_user.email))
    setattr(record, "chunks", chunks)
    setattr(record, "uploaded_at", datetime.now(timezone.utc))
    db.commit()

    return {
        "filename":      filename,
        "status":        "replaced and re-ingested" if already_existed else "uploaded and ingested",
        "chunks":        chunks,
        "allowed_roles": roles,
        "uploaded_by":   str(current_user.email),
        "indexed":       True,
    }


def _cleanup_failed_upload(file_path: str, filename: str, db: Session) -> None:
    if os.path.exists(file_path):
        os.remove(file_path)
    try:
        delete_document_chunks(filename)
    except Exception:
        pass  # vector store unreachable: nothing was stored anyway
    db.query(Document).filter(Document.filename == filename).delete()
    db.commit()

# ── Admin only ─────────────────────────────────────────────────────
@app.delete("/delete/{filename}")
def delete_file(
    filename: str,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
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
    db.query(Document).filter(Document.filename == filename).delete()
    db.commit()
    return {"message": f"{filename} deleted successfully"}

# ── Admin: change who can access a document ────────────────────────
class AccessUpdateRequest(BaseModel):
    allowed_roles: list[str]

@app.patch("/documents/{filename}/access")
def update_document_access(
    filename: str,
    body: AccessUpdateRequest,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    filename = safe_pdf_name(filename)
    try:
        roles = normalize_roles(body.allowed_roles)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    record = db.query(Document).filter(Document.filename == filename).first()
    if not record:
        raise HTTPException(status_code=404, detail="Document not found")

    # Vector store first: if it fails, the database still shows the old
    # (still enforced) audience instead of a new one that is not in effect.
    try:
        set_document_roles(filename, roles)
    except Exception as e:
        print(f"[ACCESS] Could not update chunks for {filename}: {e}")
        raise HTTPException(
            status_code=503,
            detail="Could not reach the vector store. Access was not changed.",
        )

    setattr(record, "allowed_roles", roles_to_str(roles))
    db.commit()
    return _doc_payload(record)

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
        result = get_answer(question, str(current_user.role))
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

    return {
        "answer":  answer,
        "sources": result.get("sources", []),   # [{id, filename, page, snippet}]
        "user":    current_user.email,
    }


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
