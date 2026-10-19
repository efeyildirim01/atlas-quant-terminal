"""Authentication, CSRF, RBAC and portfolio-isolation boundaries."""

from dataclasses import replace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.deps import CSRF_COOKIE, require_role
from app.auth.security import hash_password, token_hash, verify_password
from app.core.db import Base, Database
from app.main import create_app
from app.models import AuditLog, User, UserSession
from app.models.enums import Role
from tests.conftest import make_settings

PW = "correct horse battery"


def register(c: TestClient, email: str, pw: str = PW):
    return c.post("/api/v1/auth/register", json={"email": email, "password": pw})


def csrf(c: TestClient) -> dict:
    return {"X-CSRF-Token": c.cookies.get(CSRF_COOKIE)}


def test_password_hashing():
    h = hash_password(PW)
    assert h.startswith("scrypt$") and PW not in h
    assert verify_password(PW, h) and not verify_password("wrong password!", h)
    assert hash_password(PW) != h  # salted


def test_register_login_me_logout(fresh_client):
    c = fresh_client
    r = register(c, "Analyst@Example.com")
    assert r.status_code == 201 and r.json()["user"]["email"] == "analyst@example.com" and r.json()["user"]["role"] == "user"
    set_cookie = r.headers.get_list("set-cookie")
    session_cookie = next(h for h in set_cookie if h.startswith("atlas_session="))
    assert "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie
    assert c.get("/api/v1/auth/me").json()["email"] == "analyst@example.com"
    assert c.post("/api/v1/auth/logout", headers=csrf(c)).status_code == 204
    assert c.get("/api/v1/auth/me").status_code == 401


def test_session_token_not_stored_in_plaintext(fresh_client):
    c = fresh_client
    register(c, "a@example.com")
    token = c.cookies.get("atlas_session")
    with c.app.state.db.sessionmaker() as s:
        sess = s.get(UserSession, token_hash(token))
        assert sess is not None and sess.token_hash != token


def test_bad_credentials_and_weak_password(fresh_client):
    c = fresh_client
    assert register(c, "b@example.com", "short").status_code == 422
    register(c, "b@example.com")
    assert register(c, "b@example.com").status_code == 409
    c.cookies.clear()
    assert c.post("/api/v1/auth/login", json={"email": "b@example.com", "password": "wrong-password-x"}).status_code == 401
    assert c.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": PW}).status_code == 401
    assert c.post("/api/v1/auth/login", json={"email": "b@example.com", "password": PW}).status_code == 200
    with c.app.state.db.sessionmaker() as s:
        outcomes = [a.outcome for a in s.query(AuditLog).filter(AuditLog.action == "auth.login")]
    assert outcomes.count("denied") == 2 and outcomes.count("ok") == 1


def test_csrf_required_for_state_changes(fresh_client):
    c = fresh_client
    register(c, "c@example.com")
    assert c.post("/api/v1/portfolios", json={"name": "Core"}).status_code == 403
    assert c.post("/api/v1/portfolios", json={"name": "Core"}, headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert c.post("/api/v1/portfolios", json={"name": "Core"}, headers=csrf(c)).status_code == 201


def test_portfolio_isolation_between_users(fresh_client):
    alice = fresh_client
    register(alice, "alice@example.com")
    pid = alice.post("/api/v1/portfolios", json={"name": "Alice core"}, headers=csrf(alice)).json()["portfolio_id"]

    bob = TestClient(alice.app)
    register(bob, "bob@example.com")
    assert bob.get(f"/api/v1/portfolios/{pid}").status_code == 404  # existence not disclosed
    assert bob.delete(f"/api/v1/portfolios/{pid}", headers=csrf(bob)).status_code == 404
    assert bob.get("/api/v1/portfolios").json() == []
    assert alice.get(f"/api/v1/portfolios/{pid}").status_code == 200

    anon = TestClient(alice.app)
    assert anon.get("/api/v1/portfolios").status_code == 401


def test_require_role_dependency(tmp_path):
    settings = make_settings(f"sqlite:///{(tmp_path / 'r.db').as_posix()}")
    database = Database(settings.database_url)
    Base.metadata.create_all(database.engine)
    app: FastAPI = create_app(settings, database)

    @app.get("/admin-only")
    def admin_only(user=Depends(require_role(Role.ADMINISTRATOR))):
        return {"ok": True}

    c = TestClient(app)
    register(c, "user@example.com")
    assert c.get("/admin-only").status_code == 403
    with database.sessionmaker() as s:
        u = s.query(User).filter(User.email == "user@example.com").one()
        u.role = Role.ADMINISTRATOR.value
        s.commit()
    assert c.get("/admin-only").status_code == 200


def test_auth_rate_limit(tmp_path):
    settings = replace(make_settings(f"sqlite:///{(tmp_path / 'rl.db').as_posix()}"), auth_rate_limit_per_minute=3)
    database = Database(settings.database_url)
    Base.metadata.create_all(database.engine)
    c = TestClient(create_app(settings, database))
    codes = [c.post("/api/v1/auth/login", json={"email": "x@example.com", "password": PW}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
