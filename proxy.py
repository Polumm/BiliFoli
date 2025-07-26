import json
import uuid
import asyncio
from typing import Dict, Set, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

from logging_config import setup_logging

logger = setup_logging("proxy-service")
app = FastAPI()

http_proxy_router = APIRouter()

# Maintain compatibility with old client connections
client_sockets: Set[WebSocket] = set()
regular_clients: Set[WebSocket] = set()
stream_clients: Set[WebSocket] = set()
pending_streams: Dict[str, asyncio.Queue] = {}
pending_responses: Dict[str, List[asyncio.Future]] = {}

RESPONSE_TIMEOUT = 10

async def _register_client(ws: WebSocket, mode: str):
    await ws.accept()
    if mode == "stream":
        stream_clients.add(ws)
        client_sockets.add(ws)
    else:
        regular_clients.add(ws)
        client_sockets.add(ws)
    logger.info(f"✅ {mode} client connected | total={len(client_sockets)}")

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)

            if msg.get("mode") == "stream":
                q = pending_streams.get(msg["id"])
                if q:
                    await q.put(None if msg.get("final") else msg["event"])
                continue

            response_id = msg.get("id")
            if response_id and response_id in pending_responses:
                futures = pending_responses.pop(response_id, [])
                for fut in futures:
                    if not fut.done():
                        fut.set_result(msg)

    except WebSocketDisconnect:
        logger.warning(f"⚠️ {mode} client disconnected")
    except Exception:
        logger.exception(f"❌ {mode} socket error")
    finally:
        if mode == "stream":
            stream_clients.discard(ws)
        else:
            regular_clients.discard(ws)
        client_sockets.discard(ws)
        logger.info(f"ℹ️ removed {mode} client | remaining={len(client_sockets)}")

@http_proxy_router.websocket("/ws/client")
async def ws_client(ws: WebSocket):
    await _register_client(ws, mode="regular")

@http_proxy_router.websocket("/ws/sse-client")
async def ws_sse_client(ws: WebSocket):
    await _register_client(ws, mode="stream")

@http_proxy_router.websocket("/ws/backend")
async def ws_backend(ws: WebSocket):
    await ws.accept()
    logger.info("ℹ️ backend WebSocket connected (placeholder)")
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        logger.warning("⚠️ backend placeholder disconnected")
    finally:
        logger.info("ℹ️ backend WebSocket closed")

@http_proxy_router.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_http(full_path: str, request: Request):
    message_id = str(uuid.uuid4())
    method = request.method.upper()
    body = await request.json() if method in {"POST", "PUT", "PATCH"} else None
    endpoint = "/" + full_path.lstrip("/")

    headers = {k: v for k, v in request.headers.items() if k.lower() in {"authorization", "content-type"}}

    is_sse = request.headers.get("accept", "").startswith("text/event-stream")
    mode = "stream" if is_sse else "single"

    payload = {"id": message_id, "mode": mode, "endpoint": endpoint, "method": method, "message": body, "headers": headers}

    clients = stream_clients if mode == "stream" else regular_clients

    if not clients:
        return JSONResponse(status_code=503, content={"error": f"No {mode} clients connected"})

    if mode == "stream":
        client = next(iter(clients))
        q = asyncio.Queue()
        pending_streams[message_id] = q

        await client.send_text(json.dumps(payload))

        async def event_gen():
            try:
                while True:
                    chunk = await q.get()
                    if chunk is None:
                        break
                    yield chunk
            finally:
                pending_streams.pop(message_id, None)

        return StreamingResponse(event_gen(), media_type="text/event-stream")

    futures = []
    for client in clients:
        fut = asyncio.get_event_loop().create_future()
        futures.append(fut)
        await client.send_text(json.dumps(payload))
        pending_responses.setdefault(message_id, []).append(fut)

    try:
        done, _ = await asyncio.wait(futures, timeout=RESPONSE_TIMEOUT, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            raise asyncio.TimeoutError()
        response = next(iter(done)).result()
        return JSONResponse(status_code=response.get("status_code", 500), content=response.get("data", {}))
    except asyncio.TimeoutError:
        return JSONResponse(status_code=504, content={"error": "Backend timeout"})
    finally:
        pending_responses.pop(message_id, None)

app.include_router(http_proxy_router, prefix="/proxy")