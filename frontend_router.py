from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import math
from typing import Optional
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
async def api_playurl(
    request: Request,
    bvid: str,
    cid: Optional[int] = Query(None, ge=1),
):
    if not _is_authed(request):
        raise HTTPException(401, "Authentication required")

    cfg_err = bilibili_api.check_config()
    if cfg_err:
        raise HTTPException(500, f"Configuration error: {cfg_err}")

    url: Optional[str] = None

    # Preferred: core.bilibili_api.get_muxed_mp4 supports cid
    try:
        url = await bilibili_api.get_muxed_mp4(bvid, cid=cid)  # type: ignore[arg-type]
    except TypeError:
        # Backward compatible with older signature get_muxed_mp4(bvid)
        if cid is None:
            url = await bilibili_api.get_muxed_mp4(bvid)
        else:
            # Fallback: derive mp4 URL from playinfo for the given cid
            for q in (16, 32, 48):
                res = await bilibili_api.get_playinfo(bvid, cid, qn=q)
                if not res.get("success"):
                    continue
                data = res.get("data") or {}
                durl = data.get("durl") or []
                if not durl:
                    continue

                mp4s = [
                    seg.get("url")
                    for seg in durl
                    if isinstance(seg, dict) and ".mp4" in str(seg.get("url", "")).lower()
                ]
                url = mp4s[0] if mp4s and mp4s[0] else (durl[0].get("url") if isinstance(durl[0], dict) else None)
                if url:
                    break

    if not url:
        raise HTTPException(502, "No muxed MP4 stream found")

    return {"status": "success", "url": url}


@frontend_router.get("/api/video/{bvid}/playlist")
async def api_playlist(request: Request, bvid: str):
    if not _is_authed(request):
        raise HTTPException(401, "Authentication required")

    cfg_err = bilibili_api.check_config()
    if cfg_err:
        raise HTTPException(500, f"Configuration error: {cfg_err}")

    if not hasattr(bilibili_api, "get_playlist"):
        raise HTTPException(
            501,
            "Playlist API not available. Update core/bilibili_api.py to add get_playlist().",
        )

    res = await bilibili_api.get_playlist(bvid)  # type: ignore[attr-defined]
    if not res.get("success"):
        raise HTTPException(502, res.get("error") or "Failed to fetch playlist")

    return {"status": "success", "data": res.get("data")}

# ───────────────────────────── paginated folder API (for infinite scroll) ──
@frontend_router.get("/api/folder/{media_id}")
async def api_folder(
    request: Request,
    media_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
):
    # Check authentication
    if not _is_authed(request):
        raise HTTPException(401, "Authentication required")
    
    # Check API configuration
    cfg_err = bilibili_api.check_config()
    if cfg_err:
        raise HTTPException(500, f"Configuration error: {cfg_err}")
    
    try:
        # Get actual data from bilibili API instead of mock data
        res = await bilibili_api.get_folder_videos(media_id, page, page_size)
        
        if not res["success"]:
            raise HTTPException(500, f"Bilibili API error: {res['error']}")
        
        data = res["data"]
        
        # Calculate total pages if media_count is available
        total_pages: Optional[int] = None
        if mc := data["info"].get("media_count"):
            total_pages = math.ceil(mc / page_size)
        elif data["has_more"]:
            total_pages = page + 1
        else:
            total_pages = page

        payload = {
            "status": "success",
            "data": {
                "videos": data["videos"],
                "current_page": page,
                "page_size": page_size,
                "has_more": data["has_more"],
                **(
                    {"total_pages": total_pages}
                    if total_pages is not None
                    else {}
                ),
            },
        }
        return payload
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Internal server error: {str(e)}")