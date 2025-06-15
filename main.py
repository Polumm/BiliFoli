# --- main.py (refactored as frontend_router) ---
from core.templates import templates
from fastapi import APIRouter, Request, HTTPException, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
import os
import httpx

from core.bilibili_api import BilibiliAPI

frontend_router = APIRouter()
bilibili_api = BilibiliAPI()

def is_authenticated(request: Request) -> bool:
    return request.session.get("auth") is True

@frontend_router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@frontend_router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, key: str = Form(...)):
    secret_key = os.getenv("LOGIN_SECRET", "")
    if key == secret_key:
        request.session["auth"] = True
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid secret key."})

@frontend_router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)

@frontend_router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=302)
    try:
        config_error = bilibili_api.check_config()
        if config_error:
            return templates.TemplateResponse("error.html", {"request": request, "title": "Configuration Error", "message": config_error, "back_url": None})

        result = await bilibili_api.get_favorite_folders()
        if not result["success"]:
            return templates.TemplateResponse("error.html", {"request": request, "title": "API Error", "message": result["error"], "back_url": None})

        return templates.TemplateResponse("index.html", {"request": request, "folders": result["data"], "title": "Your Favorite Folders"})
    except Exception as e:
        return templates.TemplateResponse("error.html", {"request": request, "title": "Unexpected Error", "message": str(e), "back_url": None})

@frontend_router.get("/folder/{media_id}", response_class=HTMLResponse)
async def folder_detail(request: Request, media_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50)):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=302)
    try:
        config_error = bilibili_api.check_config()
        if config_error:
            return templates.TemplateResponse("error.html", {"request": request, "title": "Configuration Error", "message": config_error, "back_url": "/"})

        result = await bilibili_api.get_folder_videos(media_id, page, page_size)
        if not result["success"]:
            return templates.TemplateResponse("error.html", {"request": request, "title": f"Error Loading Folder (ID: {media_id})", "message": result["error"], "back_url": "/"})

        data = result["data"]
        total_count = data["info"].get("media_count", 0)
        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1

        return templates.TemplateResponse("folder_detail.html", {
            "request": request,
            "folder_info": data["info"],
            "videos": data["videos"],
            "current_page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "total_count": total_count,
            "has_more": data["has_more"],
            "media_id": media_id,
            "title": f"Videos in {data['info']['title']}"
        })
    except Exception as e:
        return templates.TemplateResponse("error.html", {"request": request, "title": f"Unexpected Error (Folder ID: {media_id})", "message": str(e), "back_url": "/"})

@frontend_router.get("/api/folders")
async def api_get_folders():
    result = await bilibili_api.get_favorite_folders()
    if result["success"]:
        return {"status": "success", "data": result["data"]}
    else:
        raise HTTPException(status_code=400, detail=result["error"])

@frontend_router.get("/api/folder/{media_id}")
async def api_get_folder_videos(media_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=50)):
    result = await bilibili_api.get_folder_videos(media_id, page, page_size)
    if result["success"]:
        return {"status": "success", "data": result["data"]}
    else:
        raise HTTPException(status_code=400, detail=result["error"])


@frontend_router.get("/api/video/{bvid}/playurl")
async def get_playurl(bvid: str):
    """
    Return a direct MP4 URL (audio + video) that all browsers can play.
    Order of preference:
      1. First .mp4 inside "durl"
      2. First entry in "durl" (even if the CDN omits the suffix)
    Fallbacks to DASH are deliberately *not* used because Safari
    refuses video-only .m4s segments.
    """
    try:
        # 1) basic information (gives us CID)
        info = await bilibili_api.get_video_info(bvid)
        if not info["success"]:
            raise HTTPException(400, info["error"])
        cid = info["data"]["cid"]

        # 2) play-info (real stream URLs)
        res = await bilibili_api.get_playinfo(bvid, cid)
        if not res["success"]:
            raise HTTPException(400, res["error"])

        play_data = res["data"]

        # 3) choose the safest stream – full MP4 first
        url: str | None = None

        if "durl" in play_data and play_data["durl"]:
            # Prefer true MP4s (Safari, Edge-iOS, etc.)
            mp4s = [seg["url"] for seg in play_data["durl"]
                    if ".mp4" in seg["url"].lower()]
            url = mp4s[0] if mp4s else play_data["durl"][0]["url"]

        # 4) still nothing?  Give up – better to fail loudly
        if not url:
            raise HTTPException(
                status_code=500,
                detail="Bilibili did not return any MP4 stream for this video"
            )

        return {"status": "success", "url": url}

    except HTTPException:
        raise                # re-throw cleanly
    except Exception as e:
        # unexpected – network glitch, JSON schema change, etc.
        raise HTTPException(500, f"Failed to retrieve playurl: {e}") from e
