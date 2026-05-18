"""Password gate: cookie-based auth + /login + /api/auth.

Mirrors the dream-dict approach. If SITE_PASSWORD or AUTH_SECRET is empty the
site is fully open (useful for plain localhost). When both are set, every
request that is not /login, /api/auth, or /healthz/static must carry a
cookie whose value equals AUTH_SECRET (constant-time compared).
"""

from __future__ import annotations

import hmac
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings

COOKIE_NAME = "pc_auth"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days

_PUBLIC_PATHS = {"/login", "/api/auth", "/healthz"}
_PUBLIC_PREFIXES = ("/static/",)


def _is_public(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    return any(path.startswith(p) for p in _PUBLIC_PREFIXES)


def _is_https(request: Request) -> bool:
    if request.headers.get("x-forwarded-proto", "").lower() == "https":
        return True
    return request.url.scheme == "https"


class AuthMiddleware(BaseHTTPMiddleware):
    """Cookie-gated access. No-op when SITE_PASSWORD / AUTH_SECRET are unset."""

    async def dispatch(self, request: Request, call_next):
        s = get_settings()
        if not (s.site_password and s.auth_secret):
            return await call_next(request)

        if _is_public(request.url.path):
            return await call_next(request)

        cookie = request.cookies.get(COOKIE_NAME, "")
        if cookie and hmac.compare_digest(cookie, s.auth_secret):
            return await call_next(request)

        # Redirect HTML clients, 401 JSON for /api/*
        if request.url.path.startswith("/api/"):
            return Response(b'{"error":"unauthorized"}',
                            status_code=401,
                            media_type="application/json")

        bp = s.base_path_norm
        nxt = bp + request.url.path
        if request.url.query:
            nxt += "?" + request.url.query
        return RedirectResponse(
            url=f"{bp}/login?" + urlencode({"next": nxt}),
            status_code=303,
        )


router = APIRouter()


_LOGIN_HTML = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>papers.cool · login</title>
<link rel="stylesheet" href="__BP__/static/style.css"/>
</head><body>
<main style="min-height:100dvh;display:flex;align-items:center;justify-content:center;padding:20px">
  <form method="post" action="__BP__/api/auth" style="max-width:320px;width:100%;display:flex;flex-direction:column;gap:12px;
       background:var(--card-bg);padding:24px;border-radius:14px;border:1px solid var(--border)">
    <h1 style="margin:0;font-size:20px">papers.cool</h1>
    <p class="dim" style="margin:0 0 4px">Enter password to continue.</p>
    <input type="hidden" name="next" value="__NEXT__"/>
    <input name="password" type="password" autofocus required
           style="padding:10px 12px;border-radius:10px;border:1px solid var(--border);background:var(--bg);color:var(--fg);font:inherit"/>
    __ERROR__
    <button type="submit"
            style="padding:10px 12px;border-radius:10px;border:none;background:var(--accent);color:#fff;font:inherit;font-weight:600;cursor:pointer">
      Enter
    </button>
  </form>
</main>
</body></html>
"""


def _render_login(next_url: str, error: str | None = None) -> HTMLResponse:
    err_html = (
        f'<div style="color:#d6453c;font-size:13px">{error}</div>' if error else ""
    )
    bp = get_settings().base_path_norm
    html = (
        _LOGIN_HTML.replace("__BP__", bp)
        .replace("__NEXT__", _safe_next(next_url))
        .replace("__ERROR__", err_html)
    )
    return HTMLResponse(html)


def _safe_next(s: str) -> str:
    # Only allow same-origin redirects: must start with "/" and not "//".
    if not s.startswith("/") or s.startswith("//"):
        return "/"
    # Escape any HTML-special chars to keep the value usable inside an attribute.
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(next: str = "/"):
    return _render_login(next)


@router.post("/api/auth")
async def login_submit(
    request: Request,
    password: str = Form(...),
    next: str = Form("/"),
):
    s = get_settings()
    bp = s.base_path_norm
    home = f"{bp}/"
    if not (s.site_password and s.auth_secret):
        # Auth disabled; treat as success.
        return RedirectResponse(url=next or home, status_code=303)

    if not hmac.compare_digest(password, s.site_password):
        # Tiny delay to dampen guessing.
        time.sleep(0.3)
        return _render_login(next or home, error="Wrong password")

    safe = next if (next.startswith("/") and not next.startswith("//")) else home
    resp = RedirectResponse(url=safe, status_code=303)
    resp.set_cookie(
        key=COOKIE_NAME,
        value=s.auth_secret,
        max_age=COOKIE_MAX_AGE,
        path="/",
        httponly=True,
        secure=_is_https(request),
        samesite="lax",
    )
    return resp


@router.post("/api/logout")
async def logout():
    bp = get_settings().base_path_norm
    resp = RedirectResponse(url=f"{bp}/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp
