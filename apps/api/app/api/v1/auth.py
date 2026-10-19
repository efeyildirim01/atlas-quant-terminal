from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.api.v1.common import settings_of
from app.auth.deps import CSRF_COOKIE, SESSION_COOKIE, audit, current_user, get_db, optional_user, user_by_email
from app.auth.security import DUMMY_HASH, hash_password, new_token, token_hash, verify_password
from app.core.db import utcnow
from app.core.observability import client_ip
from app.models import User, UserSession
from app.models.enums import Role
from app.schemas.accounts import Credentials, PasswordChangeIn, RegisterIn, SessionOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _start_session(request: Request, response: Response, db: Session, user: User) -> SessionOut:
    settings = settings_of(request)
    token, csrf = new_token(), new_token()
    expires = utcnow() + timedelta(hours=settings.session_ttl_hours)
    db.add(UserSession(token_hash=token_hash(token), user_id=user.user_id, csrf_token=csrf, expires_at=expires,
                       ip=client_ip(request), user_agent=request.headers.get("user-agent", "")[:300]))
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=settings.secure_cookies, samesite="lax", path="/")
    # Readable by JS on purpose: the client echoes it in X-CSRF-Token (double-submit pattern).
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False, secure=settings.secure_cookies, samesite="lax", path="/")
    return SessionOut(user=UserOut.model_validate(user), csrf_token=csrf, expires_at=expires)


@router.post("/register", response_model=SessionOut, status_code=201)
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if user_by_email(db, body.email):
        audit(db, request, "auth.register", None, body.email, outcome="duplicate")
        db.commit()
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=body.email, password_hash=hash_password(body.password), display_name=body.display_name, role=Role.USER.value)
    db.add(user)
    db.flush()
    out = _start_session(request, response, db, user)
    audit(db, request, "auth.register", user.user_id)
    db.commit()
    return out


LOCKOUT_BUCKET = "login_fail"


@router.post("/login", response_model=SessionOut)
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = settings_of(request)
    limiter, metrics = request.app.state.rate_limiter, request.app.state.metrics
    window = settings.login_lockout_minutes * 60
    # Lockout is keyed by the submitted email whether or not an account exists, so it reveals nothing about accounts.
    if limiter.count(LOCKOUT_BUCKET, body.email, window) >= settings.login_max_failures:
        audit(db, request, "auth.login", None, body.email, outcome="locked")
        db.commit()
        metrics.inc("atlas_login_failures_total", outcome="locked")
        raise HTTPException(429, f"Too many failed sign-in attempts. Try again in {settings.login_lockout_minutes} minutes.",
                            headers={"Retry-After": str(window)})
    user = user_by_email(db, body.email)
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok or not user.is_active:
        limiter.hit(LOCKOUT_BUCKET, body.email, window)
        metrics.inc("atlas_login_failures_total", outcome="denied")
        audit(db, request, "auth.login", user.user_id if user else None, body.email, outcome="denied")
        db.commit()
        raise HTTPException(401, "Invalid email or password")
    limiter.reset(LOCKOUT_BUCKET, body.email)
    out = _start_session(request, response, db, user)
    audit(db, request, "auth.login", user.user_id)
    db.commit()
    return out


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db), user: User | None = Depends(optional_user)):
    token = request.cookies.get(SESSION_COOKIE)
    if token and (sess := db.get(UserSession, token_hash(token))):
        sess.revoked = True
        audit(db, request, "auth.logout", sess.user_id)
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.status_code = 204
    return response


def _revoke_all(db: Session, user_id: str) -> int:
    return db.execute(update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked.is_(False))
                      .values(revoked=True)).rowcount


@router.post("/password", response_model=SessionOut)
def change_password(body: PasswordChangeIn, request: Request, response: Response, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    """Change the password, revoke every session (all devices) and start a fresh one for this browser."""
    if not verify_password(body.current_password, user.password_hash):
        audit(db, request, "auth.password_change", user.user_id, outcome="denied")
        db.commit()
        raise HTTPException(403, "Current password is incorrect")
    if body.new_password == body.current_password:
        raise HTTPException(422, "The new password must differ from the current one")
    user.password_hash = hash_password(body.new_password)
    revoked = _revoke_all(db, user.user_id)
    out = _start_session(request, response, db, user)
    audit(db, request, "auth.password_change", user.user_id, detail={"sessions_revoked": revoked})
    db.commit()
    return out


@router.post("/logout-all", status_code=204)
def logout_all(request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Sign out on every device."""
    revoked = _revoke_all(db, user.user_id)
    audit(db, request, "auth.logout_all", user.user_id, detail={"sessions_revoked": revoked})
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
