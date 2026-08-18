"""Real LiveModelSession, backed by Gemini Live.

Only piece of the gateway we can't test without a live Vertex AI project —
everything else runs against the fake in tests/.
"""
from typing import AsyncIterator

from common.config import get_settings
from common.gcp_clients import get_genai_client

from .live_session import LiveModelSession, LiveServerEvent

INPUT_AUDIO_MIME = "audio/pcm;rate=16000"
INPUT_VIDEO_MIME = "image/jpeg"


class GeminiLiveModelSession(LiveModelSession):
    def __init__(self, live_connect, genai_session):
        self._live_connect = live_connect
        self._session = genai_session

    async def send_audio_chunk(self, pcm16: bytes) -> None:
        from google.genai import types

        await self._session.send_realtime_input(media=types.Blob(data=pcm16, mime_type=INPUT_AUDIO_MIME))

    async def send_video_frame(self, jpeg: bytes) -> None:
        from google.genai import types

        await self._session.send_realtime_input(media=types.Blob(data=jpeg, mime_type=INPUT_VIDEO_MIME))

    async def receive(self) -> AsyncIterator[LiveServerEvent]:
        async for message in self._session.receive():
            content = getattr(message, "server_content", None)
            if content is None:
                continue

            input_transcript = getattr(content, "input_transcription", None)
            if input_transcript is not None and input_transcript.text:
                yield LiveServerEvent(type="input_transcript", text=input_transcript.text, final=True)

            output_transcript = getattr(content, "output_transcription", None)
            if output_transcript is not None and output_transcript.text:
                yield LiveServerEvent(type="output_transcript", text=output_transcript.text, final=True)

            model_turn = getattr(content, "model_turn", None)
            if model_turn is not None:
                for part in getattr(model_turn, "parts", []) or []:
                    inline_data = getattr(part, "inline_data", None)
                    if inline_data is not None and inline_data.data:
                        yield LiveServerEvent(type="audio", audio=inline_data.data)

            if getattr(content, "turn_complete", False):
                yield LiveServerEvent(type="turn_complete")

    async def close(self) -> None:
        await self._live_connect.__aexit__(None, None, None)


async def open_gemini_live_session() -> LiveModelSession:
    from google.genai import types

    settings = get_settings()
    client = get_genai_client()

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=(
            "You are Lantern, a calm and patient voice-and-vision assistant. Speak "
            "plainly, one step at a time. You only perceive and talk in this session "
            "— you never place an order or move money yourself."
        ),
    )

    live_connect = client.aio.live.connect(model=settings.gemini_flash_model, config=config)
    genai_session = await live_connect.__aenter__()
    return GeminiLiveModelSession(live_connect, genai_session)
