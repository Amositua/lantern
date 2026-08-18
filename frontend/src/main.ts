import "./style.css";
import { AudioPlaybackQueue } from "./audio-playback";
import { startCamera, startFrameCapture, startMicCapture } from "./media";
import { ConnectionStatus, LiveSessionClient, TranscriptSpeaker } from "./session";

const DEFAULT_GATEWAY_WS_URL = "ws://localhost:8086/ws/session";
const GATEWAY_WS_URL = (import.meta.env.VITE_LIVE_SESSION_GATEWAY_WS_URL as string | undefined) ?? DEFAULT_GATEWAY_WS_URL;

const STATUS_LABELS: Record<ConnectionStatus, string> = {
  connecting: "Connecting…",
  connected: "Listening",
  reconnecting: "Reconnected — picking the conversation back up…",
  closed: "Disconnected",
};

const app = document.querySelector<HTMLDivElement>("#app");

if (app) {
  app.innerHTML = `
    <main class="lantern">
      <h1>Lantern</h1>
      <p class="lede">
        Point the camera, say what you need. This is the perception session only —
        Lantern isn't taking any action yet.
      </p>

      <button id="start-button" type="button">Start session</button>
      <p id="status" class="status" aria-live="polite">Not connected</p>

      <div class="panels">
        <section aria-label="Camera feed" class="panel camera-panel">
          <h2>Camera</h2>
          <video id="camera" autoplay playsinline muted></video>
        </section>

        <section aria-label="Voice transcript" class="panel transcript-panel">
          <h2>Transcript</h2>
          <ul id="transcript" aria-live="polite"></ul>
        </section>
      </div>
    </main>
  `;

  wireUp();
}

function wireUp(): void {
  const startButton = document.querySelector<HTMLButtonElement>("#start-button")!;
  const statusEl = document.querySelector<HTMLParagraphElement>("#status")!;
  const videoEl = document.querySelector<HTMLVideoElement>("#camera")!;
  const transcriptEl = document.querySelector<HTMLUListElement>("#transcript")!;

  let stopMic: (() => void) | null = null;
  let stopFrames: (() => void) | null = null;
  let playback: AudioPlaybackQueue | null = null;
  let currentLine: HTMLLIElement | null = null;
  let currentSpeaker: TranscriptSpeaker | null = null;

  const setStatus = (status: ConnectionStatus) => {
    statusEl.textContent = STATUS_LABELS[status];
    statusEl.dataset.status = status;
  };

  const closeCurrentLine = () => {
    currentLine = null;
    currentSpeaker = null;
  };

  const appendTranscript = (speaker: TranscriptSpeaker, text: string, final: boolean) => {
    if (currentSpeaker !== speaker || currentLine === null) {
      currentLine = document.createElement("li");
      currentLine.className = `line line-${speaker}`;
      transcriptEl.appendChild(currentLine);
      currentSpeaker = speaker;
    }
    currentLine.textContent = `${speaker === "user" ? "You" : "Lantern"}: ${text}`;
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
    if (final) {
      closeCurrentLine();
    }
  };

  const client = new LiveSessionClient(GATEWAY_WS_URL, {
    onReady: () => {},
    onTranscript: appendTranscript,
    onAudio: (pcm16) => playback?.enqueue(pcm16),
    onTurnComplete: closeCurrentLine,
    onError: (message) => {
      statusEl.textContent = `Something went wrong: ${message}`;
      statusEl.dataset.status = "closed";
    },
    onStatusChange: setStatus,
  });

  startButton.addEventListener("click", () => {
    void (async () => {
      startButton.disabled = true;
      try {
        const stream = await startCamera(videoEl);

        playback = new AudioPlaybackQueue();
        await playback.resume();

        const mic = await startMicCapture(stream, (chunk) => client.sendAudioChunk(chunk));
        stopMic = mic.stop;
        stopFrames = startFrameCapture(videoEl, (frame) => client.sendVideoFrame(frame));

        client.connect();
        startButton.textContent = "Session running";
      } catch (error) {
        statusEl.textContent = `Could not start: ${(error as Error).message}`;
        startButton.disabled = false;
      }
    })();
  });

  window.addEventListener("beforeunload", () => {
    client.close();
    stopMic?.();
    stopFrames?.();
    playback?.close();
  });
}
