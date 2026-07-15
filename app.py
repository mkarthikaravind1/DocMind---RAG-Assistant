#app.py
import shutil
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
import os
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from rag import get_answer
from ingest import ingest_pdf          
from database import engine, Base, get_db
from routes.auth_routes import router as auth_router
from fastapi.security import OAuth2PasswordBearer
from auth import decode_token
from sqlalchemy.orm import Session
from jose import JWTError
from dependencies import get_current_user, require_role
from guardrails import validate_input
import time
from models import User, QueryLog
from datetime import datetime, timezone
from typing import cast

# Create DB tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "documents"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Include auth routes
app.include_router(auth_router, prefix="/auth")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# ── Protected routes ───────────────────────────────────────────────
@app.get("/files")
async def list_docs(current_user: User = Depends(get_current_user)):
    files = os.listdir(UPLOAD_DIR)
    return {"docs": files}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...),current_user: User = Depends(get_current_user)):
    if not file.filename:
        return {"error": "No filename provided"}
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    ingest_pdf(file_path)
    return {"filename": file.filename, "status": "uploaded and ingested"}

# ── Admin only ─────────────────────────────────────────────────────
@app.delete("/delete/{filename}")
async def delete_file(
    filename: str,
    current_user: User = Depends(require_role("admin"))
):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
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
    
    #user.role = str(body.role)
    setattr(user,"role",body.role)     
    db.commit()
    return {"message": f"{user.email} is now {body.role}"}

# @app.post("/chat")
# async def chat(
#     request: ChatRequest,
#     current_user: User = Depends(get_current_user)
# ):
#     # Run input guardrails
#     error = validate_input(request.question)
#     if error:
#         raise HTTPException(status_code=400, detail=error)

#     answer = get_answer(request.question)
#     return {"answer": answer, "user": current_user.email}

@app.post("/chat")
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # ── Guardrail check ───────────────────────────────────────────
    error = validate_input(request.question)
    if error:
        # Log the guardrail violation
        log = QueryLog(
            user_email       = str(current_user.email),
            user_role        = str(current_user.role),
            question         = request.question[:500],
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
    start   = time.time()
    result  = get_answer(request.question)
    elapsed = round(time.time() - start, 3)

    answer          = result["answer"]
    chunks_retrieved = result["chunks_retrieved"]

    # ── Log to DB ─────────────────────────────────────────────────
    log = QueryLog(
        user_email       = str(current_user.email),
        user_role        = str(current_user.role),
        question         = request.question[:500],
        answer_length    = len(answer),
        response_time    = elapsed,
        chunks_retrieved = chunks_retrieved,
        guardrail_hit    = None,
        timestamp        = datetime.now(timezone.utc),
    )
    db.add(log)
    db.commit()

    return {"answer": answer, "user": current_user.email}

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
            "timestamp":        l.timestamp,
        }
        for l in logs
    ]

# ── Admin: log summary stats ───────────────────────────────────────
@app.get("/admin/logs/stats")
def get_stats(
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db)
):
    logs = db.query(QueryLog).all()
    if not logs:
        return {
            "total_queries":      0,
            "avg_response_time":  0,
            "guardrail_violations": 0,
            "avg_chunks":         0,
        }

    total           = len(logs)
    violations      = sum(1 for l in logs if l.guardrail_hit is not None)
    avg_time = round(sum(cast(float, l.response_time) for l in logs) / total,3)

    avg_chunks = round(sum(cast(float, l.chunks_retrieved) for l in logs) / total,2)

    return {
        "total_queries":        total,
        "avg_response_time":    avg_time,
        "guardrail_violations": violations,
        "avg_chunks":           avg_chunks,
    }