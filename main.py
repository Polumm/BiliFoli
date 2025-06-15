from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from core.bilibili_api import BilibiliAPI
from core.templates import templates

frontend_router = APIRouter()
bilibili_api = BilibiliAPI()

# ───────────────────────────────────────────────────────────── auth helpers ────

def _is_authed(request: Request) -> bool:
    return request.session.get("auth") is True

# ─────────────────────────────────────────────────────────── auth endpoints ────

@frontend_router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@frontend_router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, key: str = Form(...)):
    if key == os.getenv("LOGIN_SECRET", ""):
        request.session["auth"] = True
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid secret key."})


@frontend_router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)

# ──────────────────────────────────────────────────────────── UI endpoints ────

@frontend_router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not _is_authed(request):
        return RedirectResponse("/login", status_code=302)
    cfg_err = bilibili_api.check_config()
    if cfg_err:
        return templates.TemplateResponse("error.html", {"request": request, "title": "Configuration error", "message": cfg_err, "back_url": None})

    folders = await bilibili_api.get_favorite_folders()
    if not folders["success"]:
        return templates.TemplateResponse("error.html", {"request": request, "title": "API error", "message": folders["error"], "back_url": None})

    return templates.TemplateResponse("index.html", {"request": request, "folders": folders["data"], "title": "Your favourite folders"})


@frontend_router.get("/folder/{media_id}", response_class=HTMLResponse)
async def folder_detail(request: Request, media_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50)):
    if not _is_authed(request):
        return RedirectResponse("/login", status_code=302)

    cfg_err = bilibili_api.check_config()
    if cfg_err:
        return templates.TemplateResponse("error.html", {"request": request, "title": "Configuration error", "message": cfg_err, "back_url": "/"})

    res = await bilibili_api.get_folder_videos(media_id, page, page_size)
    if not res["success"]:
        return templates.TemplateResponse("error.html", {"request": request, "title": f"Folder {media_id}", "message": res["error"], "back_url": "/"})

    data = res["data"]
    total = data["info"].get("media_count", 0)
    total_pages = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse(
        "folder_detail.html",
        {
            "request": request,
            "folder_info": data["info"],
            "videos": data["videos"],
            "current_page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "total_count": total,
            "has_more": data["has_more"],
            "media_id": media_id,
            "title": f"Videos in {data['info'].get('title', 'folder')}",
        },
    )

# ─────────────────────────────────────────────────────────────── API layer ────

@frontend_router.get("/api/video/{bvid}/playurl")
async def api_playurl(bvid: str):
    url = await bilibili_api.get_muxed_mp4(bvid)
    if not url:
        raise HTTPException(502, "No muxed MP4 stream found")
    return {"status": "success", "url": url}