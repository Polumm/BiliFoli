import json
import uuid
import asyncio
from typing import Dict, Set, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, FastAPI, Query
from fastapi.responses import JSONResponse, StreamingResponse
from logging_config import setup_logging

logger = setup_logging("proxy-service")
app = FastAPI()
http_proxy_router = APIRouter()

# WebSocket client pools
regular_clients: Set[WebSocket] = set()
stream_clients: Set[WebSocket] = set()

# Pending async results
pending_streams: Dict[str, asyncio.Queue] = {}
pending_responses: Dict[str, List[asyncio.Future]] = {}

RESPONSE_TIMEOUT = 10

# --------------------- WebSocket Registration --------------------- #

async def _register_client(ws: WebSocket, client_type: str):
    await ws.accept()
    client_set = stream_clients if client_type == "stream" else regular_clients
    client_set.add(ws)

    logger.info(f"✅ {client_type} client connected | regular={len(regular_clients)} | stream={len(stream_clients)}")

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)

            if msg.get("mode") == "stream":
                q = pending_streams.get(msg["id"])
                if q:
                    if msg.get("final"):
                        await q.put(None)  # Final event
                    else:
                        chunk = msg["event"]
                        if not chunk.endswith("\n\n"):
                            chunk += "\n\n"
                        await q.put(chunk)
                continue

            # Regular response
            response_id = msg.get("id")
            if response_id in pending_responses:
                for fut in pending_responses.pop(response_id, []):
                    if not fut.done():
                        fut.set_result(msg)

    except WebSocketDisconnect:
        logger.warning(f"⚠️ {client_type} client disconnected")
    except Exception:
        logger.exception(f"❌ {client_type} socket error")
    finally:
        client_set.discard(ws)
        logger.info(f"ℹ️ removed {client_type} client | remaining regular={len(regular_clients)} | stream={len(stream_clients)}")

@http_proxy_router.websocket("/ws/client")
async def ws_client(ws: WebSocket, type: str = Query("regular")):
    await _register_client(ws, client_type=type)

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

# --------------------- Main HTTP Proxy Handler --------------------- #

@http_proxy_router.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_http(full_path: str, request: Request):
    message_id = str(uuid.uuid4())
    method = request.method.upper()
    body = await request.json() if method in {"POST", "PUT", "PATCH"} else None
    endpoint = "/" + full_path.lstrip("/")

    headers = {k: v for k, v in request.headers.items() if k.lower() in {"authorization", "content-type"}}
    is_sse = endpoint.startswith("/api/sse/") and request.headers.get("accept", "").startswith("text/event-stream")
    mode = "stream" if is_sse else "single"

    payload = {
        "id": message_id,
        "mode": mode,
        "endpoint": endpoint,
        "method": method,
        "message": body,
        "headers": headers,
    }

    clients = stream_clients if mode == "stream" else regular_clients

    if not clients:
        return JSONResponse(status_code=503, content={"error": f"No {mode} clients connected"})

    # ── Streaming (SSE) request ──────────────────────────────────────
    if mode == "stream":
        client = next(iter(stream_clients))          # first available
        q: asyncio.Queue[str | None] = asyncio.Queue()
        pending_streams[message_id] = q

        try:
            await client.send_text(json.dumps(payload))
        except Exception as exc:
            logger.warning("❌ Failed to send stream request: %s", exc)
            pending_streams.pop(message_id, None)
            return JSONResponse(
                status_code=503,
                content={"error": "Stream client send failed"},
            )

        async def event_gen():
            """
            Turn the async queue that the WebSocket fills into an SSE stream.

            • send a one-off “probe” so browsers mark EventSource as OPEN
            • heartbeat every HEARTBEAT seconds while idle
            • break when a `None` sentinel arrives
            """
            HEARTBEAT = 15 # settings.sse_heartbeat_seconds
            yield ": probe\n\n"                      # immediately OPEN
            last = asyncio.get_event_loop().time()

            try:
                while True:
                    timeout = HEARTBEAT - (
                        asyncio.get_event_loop().time() - last
                    )
                    timeout = max(0, timeout)

                    try:
                        chunk = await asyncio.wait_for(q.get(), timeout=timeout)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        last = asyncio.get_event_loop().time()
                        continue

                    if chunk is None:                # sentinel → done
                        break

                    yield chunk
                    last = asyncio.get_event_loop().time()

            finally:
                pending_streams.pop(message_id, None)

        return StreamingResponse(
            event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


    # Regular HTTP (non-stream) case
    futures: List[asyncio.Future] = []
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
        logger.error("⏱ Timeout waiting for response to %s", endpoint)
        return JSONResponse(status_code=504, content={"error": "Backend timeout"})
    finally:
        pending_responses.pop(message_id, None)

# --------------------- Health Check --------------------- #

@http_proxy_router.get("/health")
async def health():
    return {
        "status": "proxy healthy",
        "regular_clients": len(regular_clients),
        "stream_clients": len(stream_clients),
    }

# Attach router
app.include_router(http_proxy_router, prefix="/proxy")
