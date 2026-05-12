"""Cookie-gate behaviour."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _client(monkeypatch, gated: bool):
    if gated:
        monkeypatch.setenv("SITE_PASSWORD", "letmein")
        monkeypatch.setenv("AUTH_SECRET", "x" * 32)
    else:
        monkeypatch.delenv("SITE_PASSWORD", raising=False)
        monkeypatch.delenv("AUTH_SECRET", raising=False)
    # Reset cached settings so the new env vars take effect.
    import papers_cool.config as cfg
    cfg._loaded = False
    from papers_cool.main import app
    return TestClient(app)


def test_open_when_auth_unset(monkeypatch):
    with _client(monkeypatch, gated=False) as c:
        assert c.get("/").status_code == 200
        assert c.get("/healthz").json()["ok"] is True


def test_redirect_to_login_when_gated(monkeypatch):
    with _client(monkeypatch, gated=True) as c:
        r = c.get("/", follow_redirects=False)
        assert r.status_code in (302, 303, 307)
        assert "/login" in r.headers["location"]


def test_static_and_health_remain_public_when_gated(monkeypatch):
    with _client(monkeypatch, gated=True) as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/static/style.css").status_code == 200
        assert c.get("/login").status_code == 200


def test_api_returns_401_when_gated(monkeypatch):
    with _client(monkeypatch, gated=True) as c:
        r = c.get("/api/papers/cs.IR", follow_redirects=False)
        assert r.status_code == 401


def test_wrong_password_rejected(monkeypatch):
    with _client(monkeypatch, gated=True) as c:
        r = c.post("/api/auth", data={"password": "nope", "next": "/"}, follow_redirects=False)
        # Renders login page again (200) with error
        assert r.status_code == 200
        assert "Wrong password" in r.text


def test_correct_password_sets_cookie_and_unlocks(monkeypatch):
    with _client(monkeypatch, gated=True) as c:
        r = c.post(
            "/api/auth",
            data={"password": "letmein", "next": "/"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert "pc_auth" in r.cookies or any("pc_auth=" in v for v in r.headers.get_list("set-cookie"))

        # Cookie now lets us through.
        r2 = c.get("/")
        assert r2.status_code == 200


def test_open_redirect_blocked(monkeypatch):
    with _client(monkeypatch, gated=True) as c:
        r = c.post(
            "/api/auth",
            data={"password": "letmein", "next": "//evil.example/x"},
            follow_redirects=False,
        )
        assert r.headers["location"] == "/"
