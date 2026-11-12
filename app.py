#app.py
import json
import os
import shutil
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

import audit
from access import DEFAULT_ROLES, can_access, normalize_roles, roles_from_str, roles_to_str
from chat_history import get_owned_conversation, recent_history, save_exchange
from database import engine, Base, get_db, SessionLocal
from evaluation import schedule as schedule_evaluation
from feedback import feedback_payload, link_answer
from dependencies import get_current_user, require_role
from guardrails import validate_input
from ingest import ingest_pdf, delete_document_chunks, set_document_roles, IngestError
from models import User, QueryLog, Document, Evaluation, Feedback
from rag import get_answer, stream_answer
from retrieval import warm_up as warm_up_reranker
from routes.audit_routes import router as audit_router
from routes.auth_routes import router as auth_router
from routes.conversation_routes import router as conversation_router
from routes.eval_routes import eval_fields, router as eval_router
from routes.feedback_routes import admin_router as feedback_admin_router, message_router as feedback_router
from vector_store import get_embeddings

# Create DB tables on startup
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the embedding model and the reranker before the first request, so
    # the first upload or question is not slow. Set PRELOAD_EMBEDDINGS=0 to
    # skip (tests do).
    if os.getenv("PRELOAD_EMBEDDINGS", "1") == "1":
        get_embeddings()
        warm_up_reranker()
    yield


app = FastAPI(lifespan=lifespan)

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
# UPLOAD_DIR can be overridden (the test suite points it at a temporary folder)
UPLOAD_DIR = os.getenv("UPLOAD_DIR") or os.path.join(BASE_DIR, "documents")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Include auth routes
app.include_router(auth_router, prefix="/auth")
app.include_router(conversation_router, prefix="/conversations")
app.include_router(eval_router, prefix="/admin/evals")
app.include_router(feedback_router, prefix="/messages")
app.include_router(feedback_admin_router, prefix="/admin/feedback")
app.include_router(audit_router, prefix="/admin/audit")


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
        audit.record(db, "document_upload", **audit.actor(current_user), target=filename,
                     details={"reason": "name belongs to a document this role cannot access"},
                     outcome=audit.DENIED)
        raise HTTPException(
            status_code=409,
            detail="A document with this name already exists. Please rename your file.",
        )
    already_existed = record is not None or os.path.exists(file_path)
    previous_roles = roles_from_str(record.allowed_roles) if record else None

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        chunks = ingest_pdf(file_path, roles)
    except IngestError as e:
        _cleanup_failed_upload(file_path, filename, db)
        audit.record(db, "document_upload", **audit.actor(current_user), target=filename,
                     details={"reason": "no readable text"}, outcome=audit.FAILED)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # A file that was never indexed must not show up as "Ready"
        _cleanup_failed_upload(file_path, filename, db)
        print(f"[UPLOAD] Ingestion failed for {filename}: {e}")
        audit.record(db, "document_upload", **audit.actor(current_user), target=filename,
                     details={"reason": "could not be indexed"}, outcome=audit.FAILED)
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
    audit.add(db, "document_upload", **audit.actor(current_user), target=filename, details={
        "allowed_roles": roles, "chunks": chunks,
        "replaced": already_existed, "previous_roles": previous_roles,
    })
    db.commit()   # the document record and its audit row together

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

    record = db.query(Document).filter(Document.filename == filename).first()
    had_roles = roles_from_str(record.allowed_roles) if record else None

    # Remove the vectors first, so a deleted document can no longer be used in answers
    try:
        delete_document_chunks(filename)
    except Exception as e:
        print(f"[DELETE] Could not remove chunks for {filename}: {e}")
        audit.record(db, "document_delete", **audit.actor(current_user), target=filename,
                     details={"reason": "vector store unreachable"}, outcome=audit.FAILED)
        raise HTTPException(
            status_code=503,
            detail="Could not reach the vector store. The document was not deleted.",
        )

    os.remove(file_path)
    db.query(Document).filter(Document.filename == filename).delete()
    audit.add(db, "document_delete", **audit.actor(current_user), target=filename,
              details={"allowed_roles": had_roles})
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
        audit.record(db, "access_change", **audit.actor(current_user), target=filename,
                     details={"reason": "vector store unreachable"}, outcome=audit.FAILED)
        raise HTTPException(
            status_code=503,
            detail="Could not reach the vector store. Access was not changed.",
        )

    audit.add(db, "access_change", **audit.actor(current_user), target=filename,
              details={"from": roles_from_str(record.allowed_roles), "to": roles})
    setattr(record, "allowed_roles", roles_to_str(roles))
    db.commit()
    return _doc_payload(record)

class ChatRequest(BaseModel):
    question: str
    conversation_id: int | None = None   # omit to start a new conversation

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

    audit.add(db, "role_change", **audit.actor(current_user), target=user.email,
              details={"from": user.role, "to": body.role})
    setattr(user,"role",body.role)
    db.commit()   # the new role and its audit row together
    return {"message": f"{user.email} is now {body.role}"}

# ── Chat ───────────────────────────────────────────────────────────
def _log_query(db: Session, email: str, role: str, question: str, *,
               answer_length=0, response_time=0.0, chunks=0, guardrail_hit=None) -> int:
    """Store one query log row and return its id."""
    row = QueryLog(
        user_email=email, user_role=role, question=question[:500],
        answer_length=answer_length, response_time=response_time,
        chunks_retrieved=chunks,
        guardrail_hit=guardrail_hit[:100] if guardrail_hit else None,
        timestamp=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    return int(row.id)  # type: ignore[arg-type]


def _prepare_chat(request: ChatRequest, current_user: User, db: Session):
    """
    Shared start of /chat and /chat/stream: guardrails, then conversation memory.
    Returns (question, email, role, user_id, conversation_id, history).
    """
    question = request.question.strip()
    email    = str(current_user.email)
    role     = str(current_user.role)
    user_id  = int(current_user.id)  # type: ignore[arg-type]

    error = validate_input(question)
    if error:
        _log_query(db, email, role, question, guardrail_hit=error)   # log the violation
        raise HTTPException(status_code=400, detail=error)

    history = []
    if request.conversation_id is not None:
        # 404 unless the conversation belongs to this user
        conv = get_owned_conversation(db, user_id, request.conversation_id)
        history = recent_history(db, int(conv.id))  # type: ignore[arg-type]

    return question, email, role, user_id, request.conversation_id, history


@app.post("/chat")
def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    question, email, role, user_id, conversation_id, history = _prepare_chat(request, current_user, db)

    # ── RAG call with timing ──────────────────────────────────────
    start = time.time()
    try:
        result = get_answer(question, role, history)
    except Exception as e:
        print(f"[CHAT] RAG pipeline failed: {e}")
        raise HTTPException(
            status_code=503,
            detail="The answer service is unavailable right now. Please try again in a moment.",
        )
    elapsed = round(time.time() - start, 3)

    conversation_id, message_id = save_exchange(
        db, user_id, conversation_id, question, result["answer"], result["sources"]
    )
    log_id = _log_query(db, email, role, question, answer_length=len(result["answer"]),
                        response_time=elapsed, chunks=result["chunks_retrieved"])
    # Quality scores are worked out in the background, after this response
    schedule_evaluation(log_id, result["answer"], result.get("eval_input"))
    # Lets a later thumbs up/down be shown next to this query in the dashboard
    link_answer(db, message_id, log_id, user_id)

    return {
        "answer":          result["answer"],
        "sources":         result["sources"],   # [{id, filename, page, snippet}]
        "conversation_id": conversation_id,
        "message_id":      message_id,          # used to rate this answer
        "user":            email,
    }


def _sse(event: str, data: dict) -> str:
    """One Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ── Chat (streaming) ───────────────────────────────────────────────
@app.post("/chat/stream")
def chat_stream(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Same as /chat, but the answer arrives piece by piece as Server-Sent Events:
      event: token  data: {"text": "..."}             (many)
      event: done   data: {"answer", "sources", "conversation_id", "message_id"}   (once, at the end)
      event: error  data: {"detail": "..."}           (instead of done, on failure)
    Guardrail blocks are returned as a normal 400 JSON error before any stream starts.
    """
    question, email, role, user_id, conversation_id, history = _prepare_chat(request, current_user, db)

    def event_stream():
        start = time.time()
        # The request's own DB session is already closed by the time the stream
        # finishes, so saving and logging use a session of their own.
        own_db = SessionLocal()
        try:
            for kind, payload in stream_answer(question, role, history):
                if kind == "token":
                    yield _sse("token", {"text": payload})
                    continue

                result = payload
                saved_id, message_id = save_exchange(
                    own_db, user_id, conversation_id, question, result["answer"], result["sources"]
                )
                log_id = _log_query(own_db, email, role, question, answer_length=len(result["answer"]),
                                    response_time=round(time.time() - start, 3),
                                    chunks=result["chunks_retrieved"])
                schedule_evaluation(log_id, result["answer"], result.get("eval_input"))
                link_answer(own_db, message_id, log_id, user_id)
                yield _sse("done", {
                    "answer":          result["answer"],
                    "sources":         result["sources"],
                    "conversation_id": saved_id,
                    "message_id":      message_id,
                    "user":            email,
                })
        except Exception as e:
            print(f"[CHAT] Streaming RAG pipeline failed: {e}")
            yield _sse("error", {
                "detail": "The answer service is unavailable right now. Please try again in a moment.",
            })
        finally:
            own_db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    # Quality scores, where the query was evaluated (see evaluation.py)
    evals = {
        e.query_log_id: e
        for e in db.query(Evaluation).filter(Evaluation.query_log_id.in_([l.id for l in logs])).all()
    }
    votes = {
        f.query_log_id: f
        for f in db.query(Feedback).filter(Feedback.query_log_id.in_([l.id for l in logs])).all()
    }
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
            **eval_fields(evals.get(l.id)),
            "feedback":         feedback_payload(votes.get(l.id)),   # the asker's thumbs up/down
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
