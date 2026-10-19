"""FastAPI dependencies: DB session, current user, role checks, CSRF, audit."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import token_hash
from app.core.db import utcnow
from app.core.observability import client_ip, request_id_var
from app.models import AuditLog, User, UserSession
from app.models.enums import ROLE_RANK, Role

SESSION_COOKIE = "atlas_session"
CSRF_COOKIE = "atlas_csrf"
CSRF_HEADER = "x-csrf-token"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def get_db(request: Request) -> Iterator[Session]:
    yield from request.app.state.db.session()


def _session_for(request: Request, db: Session) -> UserSession | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    sess = db.get(UserSession, token_hash(token))
    if sess is None or sess.revoked or sess.expires_at <= utcnow() or not sess.user.is_active:
        return None
    return sess


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    sess = _session_for(request, db)
    if sess is None:
        return None
    if request.method in UNSAFE:
        # Double-submit CSRF: the header must echo the per-session token (readable cookie set at login).
        if request.headers.get(CSRF_HEADER) != sess.csrf_token:
            raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
    request.state.user_id = sess.user_id
    return sess.user


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_role(minimum: Role) -> Callable[[User], User]:
    def dep(user: User = Depends(current_user)) -> User:
        if ROLE_RANK[Role(user.role)] < ROLE_RANK[minimum]:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return user

    return dep


def audit(db: Session, request: Request, action: str, user_id: str | None, resource: str | None = None,
          detail: dict | None = None, outcome: str = "ok") -> None:
    db.add(
        AuditLog(
            user_id=user_id, action=action, resource=resource, request_id=request_id_var.get(),
            ip=client_ip(request), detail=detail or {}, outcome=outcome,
        )
    )


def user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.strip().lower()))
