# core/auth_bilibili.py
"""
OAuth2 “Login via Bilibili” helper.

Flow
────
1. GET  /auth/bilibili/login   → redirects user to Bilibili’s OAuth page.
2. Bilibili redirects back to /auth/bilibili/callback?code=…
3. We exchange ?code for an access-token **and** follow the extra redirect
   Bilibili gives us; that response sets the ordinary web cookies
   (SESSDATA,  BILI_JCT,  buvid3 …).
4. We store the essential cookies – plus the user’s mid – in the signed
   session cookie.  All subsequent API calls use those cookies.
"""

from __future__ import annotations

import os
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
import httpx
from authlib.integrations.starlette_client import OAuth, OAuthError

router = APIRouter(prefix="/auth/bilibili", tags=["auth"])
oauth = OAuth()

# ───────────────────────── OAuth client registration ──────────────────────────
oauth.register(
    name="bilibili",
    client_id=os.getenv("BILIBILI_CLIENT_ID"),
    client_secret=os.getenv("BILIBILI_CLIENT_SECRET"),
    authorize_url="https://passport.bilibili.com/x/oauth2/authorize",
    access_token_url="https://passport.bilibili.com/x/oauth2/token",
    api_base_url="https://api.bilibili.com",
    client_kwargs={"token_endpoint_auth_method": "client_secret_post"},
)

# ─────────────────────────────── routes ────────────────────────────────────────
@router.get("/login")
async def auth_login(request: Request):
    """Kick off OAuth2 authorisation."""
    redirect_uri = request.url_for("auth_bilibili_callback")
    return await oauth.bilibili.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def auth_bilibili_callback(request: Request):
    """
    Handle the ?code=… redirect.  Capture cookies + user mid → session.
    """
    try:
        token = await oauth.bilibili.authorize_access_token(request)
    except OAuthError as e:
        raise HTTPException(400, f"Login failed: {e.error}") from e

    redirect_url = token.get("redirect_url")
    if not redirect_url:
        raise HTTPException(400, "No redirect URL in token response")

    # Follow redirect URL to pick up standard cookies.
    async with httpx.AsyncClient(follow_redirects=True) as cli:
        resp = await cli.get(redirect_url)
    jar = resp.cookies

    sessdata = jar.get("SESSDATA")
    bili_jct = jar.get("BILI_JCT") or jar.get("bili_jct")
    if not sessdata:
        raise HTTPException(400, "Bilibili did not return SESSDATA cookie")

    # ── fetch the user’s mid once ──────────────────────────────────────────────
    async with httpx.AsyncClient(follow_redirects=True, cookies=jar) as cli:
        nav = await cli.get("https://api.bilibili.com/x/web-interface/nav")
    mid = nav.json().get("data", {}).get("mid")

    # ── persist in the signed session cookie ───────────────────────────────────
    request.session.update({
        "SESSDATA": sessdata,
        "BILI_JCT": bili_jct,
        "mid": mid,
        # Optional: keep OAuth tokens if you need them later
        "access_token": token["access_token"],
        "refresh_token": token.get("refresh_token"),
        "token_expires": token.get("expires_in"),
    })
    return RedirectResponse("/", status_code=302)


@router.get("/logout")
async def auth_logout(request: Request):
    """Clear our own session copy (does not log the user out of Bilibili)."""
    request.session.clear()
    return RedirectResponse("/login", status_code=302)
    