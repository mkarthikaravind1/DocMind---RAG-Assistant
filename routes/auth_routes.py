import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
from database import get_db
from models import User
from auth import TOKEN_EXPIRE_MINUTES, hash_password, verify_password, create_token
from dependencies import get_current_user
import audit
import ratelimit
import tokens

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


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/register")
def register(data: RegisterInput, request: Request, db: Session = Depends(get_db)):
    ratelimit.enforce("register", _client_ip(request), "Too many accounts created from this address.",
                      db=db, target="POST /auth/register")

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


def _session_payload(user: User) -> dict:
    """What the browser gets on sign-in and on every refresh."""
    return {
        "access_token": create_token({"sub": user.email, "role": user.role}),
        "token_type":   "bearer",
        "expires_in":   TOKEN_EXPIRE_MINUTES * 60,
        "role":         user.role,
    }


@router.post("/login")
def login(data: LoginInput, request: Request, response: Response, db: Session = Depends(get_db)):
    email = data.email.strip().lower()[:100]

    # Brute-force protection. Per address: every attempt counts. Per account:
    # only failures count, and while an account is locked even the right
    # password is refused, so the lock cannot be used to test passwords.
    ratelimit.enforce("login_ip", _client_ip(request), "Too many sign-in attempts from this address.",
                      db=db, target=email)
    ratelimit.check("login", email, "Too many failed sign-in attempts for this account.",
                    db=db, target=email)

    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(data.password, str(user.hashed_password)):
        ratelimit.count("login", email)
        # The reason is for the audit trail only: the response never says which it was
        audit.record(db, "login_failed", target=email,
                     details={"reason": "wrong_password" if user else "unknown_account"},
                     outcome=audit.FAILED)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    ratelimit.LIMITS["login"].reset(email)
    # The refresh token and the audit row are saved together
    raw = tokens.issue(db, int(user.id))  # type: ignore[arg-type]
    audit.add(db, "login", **audit.actor(user), target=user.email)
    db.commit()
    tokens.set_cookie(response, raw)
    return _session_payload(user)


def _signed_out(detail: str, status_code: int = 401) -> JSONResponse:
    """An error reply that also removes the refresh cookie from the browser."""
    reply = JSONResponse(status_code=status_code, content={"detail": detail})
    tokens.clear_cookie(reply)
    return reply


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    """
    Exchange the refresh cookie for a new access token (and a new refresh
    cookie: the old one is retired). No access token is needed to call this.
    """
    if not tokens.origin_allowed(request):
        raise HTTPException(status_code=403, detail="Origin not allowed")

    try:
        user_id, raw = tokens.rotate(db, request.cookies.get(tokens.COOKIE_NAME))
    except tokens.RefreshError as e:
        if e.reason == "reuse":
            user = db.query(User).filter(User.id == e.user_id).first()
            audit.record(db, "token_reuse", target=user.email if user else None,
                         details={"action": "all sessions of this sign-in were ended"}, outcome=audit.DENIED)
        return _signed_out("Your session has ended. Please sign in again.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return _signed_out("Your session has ended. Please sign in again.")
    tokens.set_cookie(response, raw)
    return _session_payload(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """Ends the session on the server: the refresh token can no longer be used."""
    if not tokens.origin_allowed(request):
        raise HTTPException(status_code=403, detail="Origin not allowed")

    user_id = tokens.revoke(db, request.cookies.get(tokens.COOKIE_NAME))
    if user_id is not None:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            audit.record(db, "logout", **audit.actor(user), target=user.email)
    tokens.clear_cookie(response)
    return {"message": "Signed out"}


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    """Current user's live profile, so the UI never shows a stale role."""
    return {
        "id":    current_user.id,
        "name":  current_user.name,
        "email": current_user.email,
        "role":  current_user.role,
    }
