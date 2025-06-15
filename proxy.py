import json
import uuid
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from typing import Optional, Dict

from logging_config import setup_logging

proxy_router = APIRouter()
logger = setup_logging("proxy-service")

backend_socket: Optional[WebSocket] = None
client_socket: Optional[WebSocket] = None
pending_responses: Dict[str, asyncio.Future] = {}

async def ws_backend(ws: WebSocket):
    global backend_socket
    await ws.accept()
    backend_socket = ws
    logger.info("✅ Backend connected")

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            response_id = msg.get("id")
            if response_id and response_id in pending_responses:
                pending_responses[response_id].set_result(msg)
    except WebSocketDisconnect:
        logger.warning("⚠️ Backend disconnected")
        backend_socket = None
    except Exception as e:
        logger.exception(f"❌ Backend error: {e}")
        backend_socket = None

async def ws_client(ws: WebSocket):
    global client_socket
    await ws.accept()
    client_socket = ws
    logger.info("✅ Client connected")

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            msg["headers"] = {
                "Authorization": ws.headers.get("sec-websocket-protocol", "")
            }
            if backend_socket:
                await backend_socket.send_text(json.dumps(msg))
    except WebSocketDisconnect:
        logger.warning("⚠️ Client disconnected")
        client_socket = None

@proxy_router.api_route("/proxy{full_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def dynamic_proxy_router(full_path: str, request: Request):
    if backend_socket is None:
        return JSONResponse(status_code=503, content={"error": "Backend not connected"})

    message_id = str(uuid.uuid4())
    method = request.method.upper()
    body = await request.json() if method in ("POST", "PUT") else None
    endpoint = "/" + full_path.lstrip("/")

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() in ["authorization", "content-type"]
    }

    payload = {
        "id": message_id,
        "endpoint": endpoint,
        "method": method,
        "message": body,
        "headers": headers,
    }

    future = asyncio.get_event_loop().create_future()
    pending_responses[message_id] = future
    await backend_socket.send_text(json.dumps(payload))

    try:
        result = await asyncio.wait_for(future, timeout=10)
        return JSONResponse(
            status_code=result.get("status_code", 500),
            content=result.get("data", {}),
        )
    except asyncio.TimeoutError:
        logger.error(f"Timeout waiting for backend response to {endpoint}")
        return JSONResponse(status_code=504, content={"error": "Timeout waiting for backend response"})
    finally:
        pending_responses.pop(message_id, None)

@proxy_router.get("/proxy/health")
async def proxy_health_check():
    return {
        "status": "proxy healthy",
        "backend_connected": backend_socket is not None,
    }
