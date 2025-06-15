from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
import shutil
import os

from core.templates import templates  # using shared Jinja2 environment

dropbox_router = APIRouter()
UPLOAD_DIR = Path("dropbox")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def is_authenticated(request: Request) -> bool:
    return request.session.get("auth") is True

@dropbox_router.get("/dropbox")
async def show_dropbox(request: Request, error: str = None):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=302)

    files = sorted(UPLOAD_DIR.glob("*"), key=lambda f: f.stat().st_mtime, reverse=True)
    return templates.TemplateResponse("dropbox.html", {
        "request": request,
        "files": files,
        "upload_dir": UPLOAD_DIR,
        "error": error
    })

@dropbox_router.post("/dropbox/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=302)

    try:
        target_path = UPLOAD_DIR / file.filename
        with target_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return RedirectResponse("/dropbox", status_code=303)
    except Exception as e:
        return RedirectResponse(f"/dropbox?error=upload_failed", status_code=303)

@dropbox_router.get("/dropbox/download/{filename:path}")
async def download_file(request: Request, filename: str):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=302)

    try:
        file_path = (UPLOAD_DIR / filename).resolve()
        if not file_path.exists() or not str(file_path).startswith(str(UPLOAD_DIR.resolve())):
            raise FileNotFoundError
        return FileResponse(file_path, filename=file_path.name)
    except Exception:
        return RedirectResponse("/dropbox?error=not_found", status_code=303)

@dropbox_router.post("/dropbox/delete/{filename:path}")
async def delete_file(request: Request, filename: str):
    if not is_authenticated(request):
        return RedirectResponse("/login", status_code=302)

    try:
        file_path = (UPLOAD_DIR / filename).resolve()
        if not file_path.exists() or not str(file_path).startswith(str(UPLOAD_DIR.resolve())):
            raise FileNotFoundError
        file_path.unlink()
        return RedirectResponse("/dropbox", status_code=303)
    except Exception:
        return RedirectResponse("/dropbox?error=not_found", status_code=303)
    
