from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from dropbox import dropbox_router as dropbox_router
from core.templates import setup_jinja_filters
from pathlib import Path
import os

from proxy import http_proxy_router, ws_client, ws_backend
from frontend_router import frontend_router
from core.templates import setup_jinja_filters

app = FastAPI(title="Unified Bili Viewer + Proxy")

# Add session middleware
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "change-this-in-prod")
)

# Routers
app.include_router(http_proxy_router, prefix="/proxy")
app.include_router(frontend_router)
app.include_router(dropbox_router)

# WebSocket routes
app.add_api_websocket_route("/ws/backend", ws_backend)
app.add_api_websocket_route("/ws/client", ws_client)

# Setup templates and filters
setup_jinja_filters() 

# Static files
static_dir = Path("static")
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
