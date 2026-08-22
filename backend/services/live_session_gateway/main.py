import asyncio
import base64
import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from common.config import get_settings
from common.gcp_clients import ClientInitError, get_genai_client, get_genai_live_client
from common.health import run_checks
from common.logging_utils import get_logger

from .gemini_live import open_gemini_live_session
from .live_session import LiveServerEvent, SessionRegistry, SessionState

logger = get_logger("live_session_gateway")
settings = get_settings()

GRACE_SECONDS = 60.0
SWEEP_INTERVAL_SECONDS = 10.0

registry = SessionRegistry(open_model_session=open_gemini_live_session, grace_seconds=GRACE_SECONDS)


async def _sweep_loop() -> None:
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        await registry.sweep_expired()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    sweep_task = asyncio.create_task(_sweep_loop())
    try:
        yield
    finally:
        sweep_task.cancel()


app = FastAPI(title="Lantern Live Session Gateway", lifespan=_lifespan)


@app.get("/health")
def health() -> dict:
    return {"service": "live_session_gateway", "status": "ok", "environment": settings.environment}


@app.get("/health/deep")
def health_deep() -> dict:
    checks = run_checks({"vertex_genai": get_genai_client, "vertex_genai_live": get_genai_live_client})
    return {"service": "live_session_gateway", "checks": checks}


def _event_to_wire(event: LiveServerEvent) -> dict:
    payload = {"type": event.type}
    if event.text is not None:
        payload["text"] = event.text
    if event.final is not None:
        payload["final"] = event.final
    if event.audio is not None:
        payload["audio"] = base64.b64encode(event.audio).decode("ascii")
    return payload


async def _outbound_loop(ws: WebSocket, state: SessionState) -> None:
    while True:
        event = await state.outbound.get()
        await ws.send_text(json.dumps(_event_to_wire(event)))


async def _inbound_loop(ws: WebSocket, state: SessionState) -> None:
    while True:
        message = await ws.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))

        if "bytes" in message and message["bytes"] is not None:
            await state.model_session.send_audio_chunk(message["bytes"])
            continue

        text = message.get("text")
        if not text:
            continue
        try:
            control = json.loads(text)
        except ValueError:
            logger.warning("session %s sent malformed control message", state.session_id)
            continue

        if control.get("type") == "video_frame" and control.get("data"):
            await state.model_session.send_video_frame(base64.b64decode(control["data"]))


@app.websocket("/ws/session")
async def live_session_ws(ws: WebSocket) -> None:
    await ws.accept()

    requested_session_id: Optional[str] = None
    try:
        init_raw = await ws.receive_text()
        init = json.loads(init_raw)
        requested_session_id = init.get("session_id")
    except (ValueError, KeyError):
        pass

    state = registry.attach(requested_session_id) if requested_session_id else None
    if state is None:
        try:
            state = await registry.create()
        except ClientInitError as exc:
            await ws.send_text(json.dumps({"type": "error", "message": str(exc)}))
            await ws.close(code=1011)
            return
        registry.attach(state.session_id)

    await ws.send_text(json.dumps({"type": "session_ready", "session_id": state.session_id}))

    inbound = asyncio.create_task(_inbound_loop(ws, state))
    outbound = asyncio.create_task(_outbound_loop(ws, state))
    try:
        done, pending = await asyncio.wait({inbound, outbound}, return_when=asyncio.FIRST_EXCEPTION)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
    except WebSocketDisconnect:
        logger.info("session %s: browser disconnected, keeping the model session warm", state.session_id)
    finally:
        registry.detach(state.session_id)
