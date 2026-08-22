import "./style.css";
import { Appointment, Medication, describeFailure, proposeAppointmentAction, proposeReorder } from "./api";
import { AudioPlaybackQueue } from "./audio-playback";
import { startCamera, startFrameCapture, startMicCapture } from "./media";
import { AuditPanel } from "./panels/audit-panel";
import { LifeGraphPanel } from "./panels/life-graph-panel";
import { ProposedActionPanel } from "./panels/proposed-action-panel";
import { ConnectionStatus, LiveSessionClient, TranscriptSpeaker } from "./session";

const DEFAULT_GATEWAY_WS_URL = "ws://localhost:8086/ws/session";
const GATEWAY_WS_URL = (import.meta.env.VITE_LIVE_SESSION_GATEWAY_WS_URL as string | undefined) ?? DEFAULT_GATEWAY_WS_URL;
const USER_ID = (import.meta.env.VITE_DEMO_USER_ID as string | undefined) ?? "demo-user";

const STATUS_LABELS: Record<ConnectionStatus, string> = {
  connecting: "Connecting…",
  connected: "Listening",
  reconnecting: "Reconnected — picking the conversation back up…",
  closed: "Not connected",
};

const app = document.querySelector<HTMLDivElement>("#app");

if (app) {
  app.innerHTML = `
    <div class="app-shell">
      <header class="app-header">
        <div class="brand">
          <span class="brand-mark" id="brand-mark" aria-hidden="true"></span>
          <div class="brand-text">
            <h1>Lantern</h1>
            <p class="lede">Point the camera, say what you need. Lantern proposes, you confirm — nothing happens without your say-so.</p>
          </div>
        </div>
        <div class="session-controls">
          <button id="start-button" type="button">Start session</button>
          <p id="status" class="status" aria-live="polite">Not connected</p>
        </div>
      </header>

      <main class="dashboard">
        <section aria-label="Camera feed" class="panel camera-panel">
          <h2>Camera</h2>
          <video id="camera" autoplay playsinline muted></video>
        </section>

        <section aria-label="Voice transcript" class="panel transcript-panel">
          <h2>Transcript</h2>
          <ul id="transcript" aria-live="polite"></ul>
        </section>

        <section aria-label="Proposed action" class="panel proposed-action-panel" aria-live="polite">
          <h2>Proposed action</h2>
          <div id="proposed-action-body"></div>
        </section>

        <section aria-label="What Lantern believes about you" class="panel life-graph-panel">
          <div class="panel-heading-row">
            <h2>What Lantern believes about you</h2>
            <button id="life-graph-refresh" class="link-button" type="button">Refresh</button>
          </div>
          <div id="life-graph-body"><p class="empty-state">Loading…</p></div>
        </section>

        <section aria-label="Activity log" class="panel audit-panel" aria-live="polite">
          <div class="panel-heading-row">
            <h2>Activity log</h2>
            <button id="audit-refresh" class="link-button" type="button">Refresh</button>
          </div>
          <div id="audit-body"><p class="empty-state">Loading…</p></div>
        </section>
      </main>
    </div>
  `;

  wireUp();
}

function wireUp(): void {
  const startButton = document.querySelector<HTMLButtonElement>("#start-button")!;
  const statusEl = document.querySelector<HTMLParagraphElement>("#status")!;
  const brandMark = document.querySelector<HTMLSpanElement>("#brand-mark")!;
  const videoEl = document.querySelector<HTMLVideoElement>("#camera")!;
  const transcriptEl = document.querySelector<HTMLUListElement>("#transcript")!;
  const proposedActionBody = document.querySelector<HTMLDivElement>("#proposed-action-body")!;
  const lifeGraphBody = document.querySelector<HTMLDivElement>("#life-graph-body")!;
  const auditBody = document.querySelector<HTMLDivElement>("#audit-body")!;
  const lifeGraphRefreshButton = document.querySelector<HTMLButtonElement>("#life-graph-refresh")!;
  const auditRefreshButton = document.querySelector<HTMLButtonElement>("#audit-refresh")!;

  const refreshBelief = () => {
    void lifeGraphPanel.refresh();
    void auditPanel.refresh();
  };

  const proposedActionPanel = new ProposedActionPanel(proposedActionBody, USER_ID, refreshBelief);
  const auditPanel = new AuditPanel(auditBody, USER_ID);
  const lifeGraphPanel = new LifeGraphPanel(
    lifeGraphBody,
    USER_ID,
    (medication: Medication) => void requestReorder(medication),
    (appointment: Appointment) => void requestAppointmentConfirm(appointment),
  );

  const showChecking = (label: string) => {
    proposedActionBody.replaceChildren();
    const loading = document.createElement("p");
    loading.className = "empty-state";
    loading.textContent = `Checking your ${label}…`;
    proposedActionBody.appendChild(loading);
  };

  const showProposeFailure = (context: string, error: unknown, friendly: string) => {
    const text = describeFailure(context, error, friendly);
    const message = document.createElement("p");
    message.className = "empty-state";
    message.textContent = text;
    proposedActionBody.replaceChildren(message);
  };

  const requestReorder = async (medication: Medication): Promise<void> => {
    showChecking(medication.name);
    try {
      const proposal = await proposeReorder(USER_ID, medication.id);
      proposedActionPanel.showReorderProposal(proposal);
      proposedActionBody.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) {
      showProposeFailure(
        "propose reorder failed",
        error,
        `Lantern couldn't check on ${medication.name} right now. Try again in a moment.`,
      );
    }
  };

  const requestAppointmentConfirm = async (appointment: Appointment): Promise<void> => {
    showChecking(`${appointment.provider} appointment`);
    try {
      const proposal = await proposeAppointmentAction(USER_ID, appointment.id, "confirm_attendance");
      proposedActionPanel.showAppointmentProposal(proposal);
      proposedActionBody.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) {
      showProposeFailure(
        "propose appointment action failed",
        error,
        `Lantern couldn't check on your ${appointment.provider} appointment right now. Try again in a moment.`,
      );
    }
  };

  lifeGraphRefreshButton.addEventListener("click", () => void lifeGraphPanel.refresh());
  auditRefreshButton.addEventListener("click", () => void auditPanel.refresh());

  void lifeGraphPanel.refresh();
  void auditPanel.refresh();

  let stopMic: (() => void) | null = null;
  let stopFrames: (() => void) | null = null;
  let playback: AudioPlaybackQueue | null = null;
  let currentLine: HTMLLIElement | null = null;
  let currentSpeaker: TranscriptSpeaker | null = null;

  const setStatus = (status: ConnectionStatus) => {
    statusEl.textContent = STATUS_LABELS[status];
    statusEl.dataset.status = status;
    brandMark.dataset.status = status;
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
        statusEl.textContent = `Lantern needs camera and microphone access to start: ${(error as Error).message}`;
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
