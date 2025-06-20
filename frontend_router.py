# frontend_router.py
from __future__ import annotations

import math
import os
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from core.bilibili_api import BilibiliAPI
from core.templates import templates

frontend_router = APIRouter()

# ───────────────────────── helpers ────────────────────────────────────────────
def _is_authed(request: Request) -> bool:
    return "SESSDATA" in request.session


def _api_for(request: Request) -> BilibiliAPI:
    cookies = {k: request.session[k]
               for k in ("SESSDATA", "BILI_JCT")
               if k in request.session}
    return BilibiliAPI(cookies, mid=request.session.get("mid"))


# ───────────────────────── auth routes ────────────────────────────────────────
@frontend_router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    """
    Renders a simple page with a single “Login via Bilibili” button.
    """
    return templates.TemplateResponse("login.html",
                                      {"request": request, "error": None})


@frontend_router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


# ───────────────────────── UI pages ───────────────────────────────────────────
@frontend_router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not _is_authed(request):
        return RedirectResponse("/login", status_code=302)

    async with _api_for(request) as api:
        cfg_err = api.check_config()
        if cfg_err:
            return templates.TemplateResponse(
                "error.html",
                {"request": request,
                 "title": "Configuration error",
                 "message": cfg_err,
                 "back_url": None},
            )

        folders = await api.get_favorite_folders()
        if not folders["success"]:
            return templates.TemplateResponse(
                "error.html",
                {"request": request,
                 "title": "API error",
                 "message": folders["error"],
                 "back_url": None},
            )

    return templates.TemplateResponse(
        "index.html",
        {"request": request,
         "folders": folders["data"],
         "title": "Your favourite folders"},
    )


@frontend_router.get("/folder/{media_id}", response_class=HTMLResponse)
async def folder_detail(
    request: Request,
    media_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
):
    if not _is_authed(request):
        return RedirectResponse("/login", status_code=302)

    async with _api_for(request) as api:
        cfg_err = api.check_config()
        if cfg_err:
            return templates.TemplateResponse(
                "error.html",
                {"request": request,
                 "title": "Configuration error",
                 "message": cfg_err,
                 "back_url": "/"},
            )

        res = await api.get_folder_videos(media_id, page, page_size)
        if not res["success"]:
            return templates.TemplateResponse(
                "error.html",
                {"request": request,
                 "title": f"Folder {media_id}",
                 "message": res["error"],
                 "back_url": "/"},
            )

    data = res["data"]
    total = data["info"].get("media_count", 0)
    total_pages = max(1, math.ceil(total / page_size))

    return templates.TemplateResponse(
        "folder_detail.html",
        {"request": request,
         "folder_info": data["info"],
         "videos": data["videos"],
         "current_page": page,
         "page_size": page_size,
         "total_pages": total_pages,
         "total_count": total,
         "has_more": data["has_more"],
         "media_id": media_id,
         "title": f"Videos in {data['info'].get('title', 'folder')}"}
    )


# ───────────────────────── JSON API endpoints ────────────────────────────────
@frontend_router.get("/api/video/{bvid}/playurl")
async def api_playurl(request: Request, bvid: str):
    async with _api_for(request) as api:
        url = await api.get_muxed_mp4(bvid)
    if not url:
        raise HTTPException(502, "No muxed MP4 stream found")
    return {"status": "success",
            "url": f"/api/proxy?u={quote(url, safe='')}"}


@frontend_router.get("/api/folder/{media_id}")
async def api_folder(
    request: Request,
    media_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
):
    if not _is_authed(request):
        raise HTTPException(401, "Authentication required")

    async with _api_for(request) as api:
        cfg_err = api.check_config()
        if cfg_err:
            raise HTTPException(500, f"Config error: {cfg_err}")

        res = await api.get_folder_videos(media_id, page, page_size)
        if not res["success"]:
            raise HTTPException(500, f"API error: {res['error']}")

    data = res["data"]
    total = data["info"].get("media_count")
    total_pages = math.ceil(total / page_size) if total else None

    return {
        "status": "success",
        "data": {
            "videos": data["videos"],
            "current_page": page,
            "page_size": page_size,
            "has_more": data["has_more"],
            **({"total_pages": total_pages} if total_pages else {}),
        },
    }


# ───────────────────────── streaming proxy ────────────────────────────────────
@frontend_router.get("/api/proxy")
async def proxy(request: Request, u: str):
    """
    Streams the remote Bilibili CDN file while injecting a Referer header so
    video playback works in browsers that block cross-origin range requests.
    """
    headers = {"Referer": "https://www.bilibili.com/"}
    if range_hdr := request.headers.get("range"):
        headers["Range"] = range_hdr

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as c:
        resp = await c.get(u, headers=headers, stream=True)
        if resp.status_code >= 400:
            raise HTTPException(resp.status_code, "CDN rejected hot-link")

        safe_headers = {
            k: v for k, v in resp.headers.items()
            if k.lower() in (
                "content-length", "content-type", "content-range", "accept-ranges")
        }

        return StreamingResponse(
            resp.aiter_bytes(),
            status_code=resp.status_code,
            headers=safe_headers,
        )
