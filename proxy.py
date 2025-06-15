import json
import uuid
import asyncio
from typing import Dict, Set, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse

from logging_config import setup_logging

logger = setup_logging("proxy-service")

# ---------------------------------------------------------------------------
# Globals & configuration
# ---------------------------------------------------------------------------

http_proxy_router = APIRouter()

client_sockets: Set[WebSocket] = set()
"""All connected proxy‑clients."""

pending_responses: Dict[str, List[asyncio.Future]] = {}
"""Maps *message_id* → list of futures awaiting that response."""

RESPONSE_TIMEOUT = 10  # seconds

# ---------------------------------------------------------------------------
# WebSocket handlers
# ---------------------------------------------------------------------------

async def _register_client(ws: WebSocket) -> None:
    """Internal helper that accepts the socket and pumps incoming messages.

    Every message *must* be a JSON object containing an ``id``. If that id
    matches an entry in :pydata:`pending_responses`, the message is treated as
    the HTTP response for that proxied call and the corresponding future(s)
    are resolved.
    """
    await ws.accept()
    client_sockets.add(ws)
    logger.info("✅ proxy‑client connected | total=%d", len(client_sockets))

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            response_id = msg.get("id")
            if response_id and response_id in pending_responses:
                futures = pending_responses.pop(response_id, [])
                for fut in futures:
                    if not fut.done():
                        fut.set_result(msg)
    except WebSocketDisconnect:
        logger.warning("⚠️ proxy‑client disconnected")
    except Exception:
        logger.exception("❌ client socket error")
    finally:
        client_sockets.discard(ws)
        logger.info("ℹ️ removed client | remaining=%d", len(client_sockets))


async def ws_client(ws: WebSocket):  # exported
    """WebSocket entry‑point for proxy‑clients."""
    await _register_client(ws)


async def ws_backend(ws: WebSocket):  # exported
    """Optional backend socket (placeholder) – keeps feature‑parity with the
    historical interface so existing *main.py* integrations keep working even
    if you do not need a backend WebSocket right now.
    """
    await ws.accept()
    logger.info("ℹ️ backend WebSocket connected (placeholder)")
    try:
        while True:
            await ws.receive_text()  # no‑op
    except WebSocketDisconnect:
        logger.warning("⚠️ backend placeholder disconnected")
    finally:
        logger.info("ℹ️ backend WebSocket closed")

# ---------------------------------------------------------------------------
# HTTP proxy route
# ---------------------------------------------------------------------------

@http_proxy_router.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_http(full_path: str, request: Request):
    """Catch‑all HTTP entry‑point (mounted under ``/proxy`` by the host app).

    The incoming request is wrapped into a JSON payload and broadcast to all
    connected proxy‑clients. The *first* response that arrives is sent back to
    the caller. If no response is received within *RESPONSE_TIMEOUT* seconds,
    a 504 Gateway Timeout is returned.
    """

    # ---------------- Quick sanity: any clients available? -----------------
    if not client_sockets:
        return JSONResponse(status_code=503, content={"error": "No proxy‑clients connected"})

    # ---------------- Build proxy payload -----------------
    message_id = str(uuid.uuid4())
    method = request.method.upper()
    body = await request.json() if method in {"POST", "PUT", "PATCH"} else None
    endpoint = "/" + full_path.lstrip("/")

    headers = {k: v for k, v in request.headers.items() if k.lower() in {"authorization", "content-type"}}

    payload = {
        "id": message_id,
        "endpoint": endpoint,
        "method": method,
        "message": body,
        "headers": headers,
    }

    logger.info("📨 %s %s | headers=%s", method, endpoint, headers)

    # ---------------- Fan‑out -----------------
    futures: List[asyncio.Future] = []
    dead_clients: Set[WebSocket] = set()

    for client in client_sockets:
        fut = asyncio.get_event_loop().create_future()
        futures.append(fut)
        try:
            await client.send_text(json.dumps(payload))
            pending_responses.setdefault(message_id, []).append(fut)
        except Exception as e:
            logger.warning("⛔ failed to send to client: %s", e)
            dead_clients.add(client)

    # Clean up any broken sockets early so the next request does not retry them.
    for dc in dead_clients:
        client_sockets.discard(dc)

    if not futures:
        return JSONResponse(status_code=503, content={"error": "No alive proxy‑clients"})

    # ---------------- Wait for first response -----------------
    try:
        done, _ = await asyncio.wait(futures, timeout=RESPONSE_TIMEOUT, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            raise asyncio.TimeoutError()
        response = next(iter(done)).result()
        return JSONResponse(status_code=response.get("status_code", 500), content=response.get("data", {}))
    except asyncio.TimeoutError:
        logger.error("⏱ timeout waiting for backend response to %s", endpoint)
        return JSONResponse(status_code=504, content={"error": "Backend timeout"})
    finally:
        pending_responses.pop(message_id, None)


# ---------------------------------------------------------------------------
# Health check (mounted under /proxy/health by host app)
# ---------------------------------------------------------------------------

@http_proxy_router.get("/health")
async def health():
    return {"status": "proxy healthy", "connected_clients": len(client_sockets)}