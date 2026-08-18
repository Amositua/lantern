"""Session lifecycle for the Live Session Gateway.

Key idea: the Gemini Live connection isn't tied to the browser's
WebSocket. A session's model connection and pump task keep running even
with no browser attached, so a reconnect just re-attaches instead of
starting the conversation over.
"""
import abc
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable, Dict, Literal, Optional

from common.logging_utils import get_logger

logger = get_logger("live_session_gateway.live_session")

EventType = Literal["input_transcript", "output_transcript", "audio", "turn_complete", "error"]


@dataclass
class LiveServerEvent:
    type: EventType
    text: Optional[str] = None
    final: Optional[bool] = None
    audio: Optional[bytes] = None


class LiveModelSession(abc.ABC):
    """What the gateway needs from a live model session. Real impl in
    gemini_live.py, fake one in tests/."""

    @abc.abstractmethod
    async def send_audio_chunk(self, pcm16: bytes) -> None: ...

    @abc.abstractmethod
    async def send_video_frame(self, jpeg: bytes) -> None: ...

    @abc.abstractmethod
    def receive(self) -> AsyncIterator[LiveServerEvent]: ...

    @abc.abstractmethod
    async def close(self) -> None: ...


SessionFactory = Callable[[], Awaitable[LiveModelSession]]


@dataclass
class SessionState:
    session_id: str
    model_session: LiveModelSession
    pump_task: "asyncio.Task"
    outbound: "asyncio.Queue[LiveServerEvent]"
    attached: bool = False
    detached_at: Optional[float] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SessionRegistry:
    """Tracks every open Gemini Live session and who's attached to it."""

    OUTBOUND_QUEUE_SIZE = 256  # enough buffer for a quick reconnect, not enough to grow forever if abandoned

    def __init__(self, open_model_session: SessionFactory, grace_seconds: float = 60.0):
        self._open_model_session = open_model_session
        self._grace_seconds = grace_seconds
        self._sessions: Dict[str, SessionState] = {}

    async def create(self) -> SessionState:
        session_id = uuid.uuid4().hex
        model_session = await self._open_model_session()
        outbound: "asyncio.Queue[LiveServerEvent]" = asyncio.Queue(maxsize=self.OUTBOUND_QUEUE_SIZE)
        pump_task = asyncio.create_task(self._pump(session_id, model_session, outbound))
        state = SessionState(session_id=session_id, model_session=model_session, pump_task=pump_task, outbound=outbound)
        self._sessions[session_id] = state
        return state

    def get(self, session_id: str) -> Optional[SessionState]:
        return self._sessions.get(session_id)

    def attach(self, session_id: str) -> Optional[SessionState]:
        state = self._sessions.get(session_id)
        if state is None:
            return None
        state.attached = True
        state.detached_at = None
        return state

    def detach(self, session_id: str) -> None:
        state = self._sessions.get(session_id)
        if state is None:
            return
        state.attached = False
        state.detached_at = time.monotonic()

    async def sweep_expired(self) -> None:
        """Evict + close anything past its grace period with nobody attached."""
        now = time.monotonic()
        expired = [
            session_id
            for session_id, state in self._sessions.items()
            if not state.attached and state.detached_at is not None and now - state.detached_at > self._grace_seconds
        ]
        for session_id in expired:
            await self._evict(session_id)

    async def _evict(self, session_id: str) -> None:
        state = self._sessions.pop(session_id, None)
        if state is None:
            return
        state.pump_task.cancel()
        try:
            await state.model_session.close()
        except Exception:  # noqa: BLE001 - eviction must not crash on a misbehaving close()
            logger.warning("error closing model session %s", session_id, exc_info=True)

    async def _pump(self, session_id: str, model_session: LiveModelSession, outbound: "asyncio.Queue[LiveServerEvent]") -> None:
        # runs regardless of whether a browser is attached right now
        try:
            async for event in model_session.receive():
                if outbound.full():
                    outbound.get_nowait()  # drop oldest, don't block the pump
                await outbound.put(event)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - don't let a broken upstream session take the process down
            logger.warning("live model session %s ended unexpectedly", session_id, exc_info=True)
