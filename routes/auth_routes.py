import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
from database import get_db
from models import User
from auth import hash_password, verify_password, create_token
from dependencies import get_current_user
import audit

router = APIRouter()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

class RegisterInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=100)
    # bcrypt only supports passwords up to 72 bytes
    password: str = Field(min_length=8, max_length=72)

    @field_validator("name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")
        return v

    @field_validator("email")
    @classmethod
    def clean_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v

class LoginInput(BaseModel):
    email: str
    password: str

@router.post("/register")
def register(data: RegisterInput, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    # The very first account becomes the admin, so the app can be
    # bootstrapped without editing the database by hand.
    is_first_user = db.query(User).count() == 0

    user = User(
        name=data.name,
        email=data.email,
        hashed_password=hash_password(data.password),
        role="admin" if is_first_user else "employee",
    )
    db.add(user)
    # Same transaction as the new account
    audit.add(db, "user_register", actor_email=user.email, actor_role=user.role,
              target=user.email, details={"role": user.role, "first_admin": is_first_user})
    db.commit()
    return {"message": "User registered successfully", "role": user.role}

@router.post("/login")
def login(data: LoginInput, db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(data.password, str(user.hashed_password)):
        # The reason is for the audit trail only: the response never says which it was
        audit.record(db, "login_failed", target=email,
                     details={"reason": "wrong_password" if user else "unknown_account"},
                     outcome=audit.FAILED)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token({"sub": user.email, "role": user.role})
    audit.record(db, "login", **audit.actor(user), target=user.email)
    return {"access_token": token, "token_type": "bearer"}

@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    """Current user's live profile, so the UI never shows a stale role."""
    return {
        "id":    current_user.id,
        "name":  current_user.name,
        "email": current_user.email,
        "role":  current_user.role,
    }
