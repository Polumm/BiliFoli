import json
import uuid
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, APIRouter
from fastapi.responses import JSONResponse
from typing import Dict, Set, List
from logging_config import setup_logging

# Setup logger
logger = setup_logging("proxy-service")

# Track connected clients and in-flight messages
client_sockets: Set[WebSocket] = set()
pending_responses: Dict[str, List[asyncio.Future]] = {}

# WebSocket for proxy-client(s)
async def ws_client(ws: WebSocket):
    await ws.accept()
    client_sockets.add(ws)
    logger.info(f"✅ Proxy client connected. Total clients: {len(client_sockets)}")

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            response_id = msg.get("id")
            if response_id and response_id in pending_responses:
                for future in pending_responses[response_id]:
                    if not future.done():
                        future.set_result(msg)
                        break
    except WebSocketDisconnect:
        logger.warning("⚠️ Client disconnected")
    except Exception as e:
        logger.exception(f"❌ Client socket error: {e}")
    finally:
        client_sockets.discard(ws)
        logger.info(f"ℹ️ Client removed. Remaining: {len(client_sockets)}")

# Dummy backend socket route if needed later (currently unused)
async def ws_backend(ws: WebSocket):
    await ws.accept()
    logger.info("ℹ️ Backend WebSocket connected (placeholder)")
    try:
        while True:
            await ws.receive_text()  # No-op
    except WebSocketDisconnect:
        logger.warning("⚠️ Backend placeholder disconnected")

# HTTP proxy router (standard APIRouter with prefix)
http_proxy_router = APIRouter()

@http_proxy_router.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def dynamic_proxy_router(full_path: str, request: Request):
    if not client_sockets:
        return JSONResponse(status_code=503, content={"error": "No clients connected"})

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

    futures: List[asyncio.Future] = []
    for client in list(client_sockets):
        future = asyncio.get_event_loop().create_future()
        futures.append(future)
        try:
            await client.send_text(json.dumps(payload))
        except Exception as e:
            logger.warning(f"⛔ Failed to send to client: {e}")
            client_sockets.discard(client)

    pending_responses[message_id] = futures

    try:
        done, _ = await asyncio.wait(futures, timeout=10, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            raise asyncio.TimeoutError()

        response = list(done)[0].result()
        return JSONResponse(
            status_code=response.get("status_code", 500),
            content=response.get("data", {}),
        )
    except asyncio.TimeoutError:
        logger.error(f"⏱ Timeout waiting for backend response to {endpoint}")
        return JSONResponse(status_code=504, content={"error": "Timeout waiting for backend response"})
    finally:
        pending_responses.pop(message_id, None)

# Health check
@http_proxy_router.get("/health")
async def proxy_health_check():
    return {
        "status": "proxy healthy",
        "connected_clients": len(client_sockets),
    }