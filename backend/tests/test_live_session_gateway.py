import asyncio
import contextlib
import json
import socket
import threading
import time

import uvicorn
import websockets

from services.live_session_gateway.live_session import LiveModelSession, LiveServerEvent, SessionRegistry


class FakeLiveModelSession(LiveModelSession):
    def __init__(self):
        self.sent_audio = []
        self.sent_video = []
        self.closed = False
        self._events: "asyncio.Queue[LiveServerEvent]" = asyncio.Queue()

    async def send_audio_chunk(self, pcm16: bytes) -> None:
        self.sent_audio.append(pcm16)

    async def send_video_frame(self, jpeg: bytes) -> None:
        self.sent_video.append(jpeg)

    async def push_event(self, event: LiveServerEvent) -> None:
        await self._events.put(event)

    async def receive(self):
        while True:
            yield await self._events.get()

    async def close(self) -> None:
        self.closed = True


def _factory(fake: FakeLiveModelSession):
    async def factory():
        return fake

    return factory


# ---------------------------------------------------------- registry logic --


async def test_create_starts_a_pump_that_drains_into_outbound():
    fake = FakeLiveModelSession()
    registry = SessionRegistry(open_model_session=_factory(fake), grace_seconds=60)
    state = await registry.create()

    await fake.push_event(LiveServerEvent(type="output_transcript", text="hello"))
    event = await asyncio.wait_for(state.outbound.get(), timeout=1)
    assert event.text == "hello"


async def test_detach_then_reattach_within_grace_period_reuses_the_same_model_session():
    fake = FakeLiveModelSession()
    registry = SessionRegistry(open_model_session=_factory(fake), grace_seconds=60)
    state = await registry.create()
    registry.attach(state.session_id)

    registry.detach(state.session_id)
    await registry.sweep_expired()  # grace period hasn't elapsed -> must not evict

    reattached = registry.attach(state.session_id)
    assert reattached is not None
    assert reattached.model_session is fake
    assert not fake.closed


async def test_events_sent_while_detached_are_delivered_after_reattaching():
    fake = FakeLiveModelSession()
    registry = SessionRegistry(open_model_session=_factory(fake), grace_seconds=60)
    state = await registry.create()
    registry.detach(state.session_id)

    await fake.push_event(LiveServerEvent(type="output_transcript", text="buffered while away"))
    await asyncio.sleep(0.01)  # let the pump task drain the fake's queue

    reattached = registry.attach(state.session_id)
    event = await asyncio.wait_for(reattached.outbound.get(), timeout=1)
    assert event.text == "buffered while away"


async def test_expired_session_is_evicted_and_closed():
    fake = FakeLiveModelSession()
    registry = SessionRegistry(open_model_session=_factory(fake), grace_seconds=0)
    state = await registry.create()
    registry.detach(state.session_id)

    await asyncio.sleep(0.01)
    await registry.sweep_expired()

    assert registry.get(state.session_id) is None
    assert fake.closed is True


# ------------------------------------------------------ full websocket route --
# real uvicorn in a background thread + a real websockets client. Starlette's
# TestClient WS bridge kept flaking on its own portal teardown here (nothing
# to do with our code), so just run the real thing instead.


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def _running_gateway(monkeypatch, session_factory):
    from services.live_session_gateway import main as gateway_main

    monkeypatch.setattr(gateway_main, "registry", SessionRegistry(open_model_session=session_factory, grace_seconds=60))

    port = _free_port()
    config = uvicorn.Config(gateway_main.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.02)
        else:
            raise RuntimeError("gateway didn't start in time")
        yield f"ws://127.0.0.1:{port}/ws/session"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_websocket_session_survives_a_reconnect_with_the_same_session_id(monkeypatch):
    fake = FakeLiveModelSession()

    with _running_gateway(monkeypatch, _factory(fake)) as url:

        async def scenario():
            async with websockets.connect(url) as ws1:
                await ws1.send(json.dumps({"session_id": None}))
                ready = json.loads(await ws1.recv())
                assert ready["type"] == "session_ready"
                session_id = ready["session_id"]

            async with websockets.connect(url) as ws2:
                await ws2.send(json.dumps({"session_id": session_id}))
                ready2 = json.loads(await ws2.recv())
                assert ready2["session_id"] == session_id

        asyncio.run(scenario())

    assert not fake.closed  # the model session survived the gap, it was never recreated


def test_websocket_relays_transcript_events_to_the_browser(monkeypatch):
    fake = FakeLiveModelSession()
    fake._events.put_nowait(LiveServerEvent(type="output_transcript", text="that's your amlodipine", final=True))

    with _running_gateway(monkeypatch, _factory(fake)) as url:

        async def scenario():
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps({"session_id": None}))
                ready = json.loads(await ws.recv())
                assert ready["type"] == "session_ready"

                message = json.loads(await ws.recv())
                assert message == {"type": "output_transcript", "text": "that's your amlodipine", "final": True}

        asyncio.run(scenario())


def test_websocket_sends_a_clean_error_when_the_model_session_cannot_be_created(monkeypatch):
    from common.gcp_clients import ClientInitError

    async def failing_factory():
        raise ClientInitError("GCP_PROJECT_ID is not set; cannot init the Vertex AI GenAI client")

    with _running_gateway(monkeypatch, failing_factory) as url:

        async def scenario():
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps({"session_id": None}))
                message = json.loads(await ws.recv())
                assert message["type"] == "error"
                assert "GCP_PROJECT_ID" in message["message"]

        asyncio.run(scenario())
