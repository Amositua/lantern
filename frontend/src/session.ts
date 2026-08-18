export type TranscriptSpeaker = "user" | "lantern";
export type ConnectionStatus = "connecting" | "connected" | "reconnecting" | "closed";

export interface SessionEvents {
  onReady: (sessionId: string) => void;
  onTranscript: (speaker: TranscriptSpeaker, text: string, final: boolean) => void;
  onAudio: (pcm16: ArrayBuffer) => void;
  onTurnComplete: () => void;
  onError: (message: string) => void;
  onStatusChange: (status: ConnectionStatus) => void;
}

const RECONNECT_DELAYS_MS = [500, 1000, 2000, 4000, 5000];

// keeps the gateway's session_id around so a reconnect re-attaches to
// the same live session instead of starting over
export class LiveSessionClient {
  private ws: WebSocket | null = null;
  private sessionId: string | null = null;
  private reconnectAttempt = 0;
  private closedByUser = false;
  private reconnectTimer: number | null = null;

  constructor(
    private readonly url: string,
    private readonly events: SessionEvents,
  ) {}

  connect(): void {
    this.closedByUser = false;
    this.events.onStatusChange(this.sessionId ? "reconnecting" : "connecting");

    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ session_id: this.sessionId }));
    };

    ws.onmessage = (event: MessageEvent<string>) => this.handleMessage(event.data);

    ws.onclose = () => {
      this.events.onStatusChange("closed");
      if (!this.closedByUser) {
        this.scheduleReconnect();
      }
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  private handleMessage(raw: string): void {
    let message: Record<string, unknown>;
    try {
      message = JSON.parse(raw);
    } catch {
      return;
    }

    switch (message.type) {
      case "session_ready":
        this.sessionId = message.session_id as string;
        this.reconnectAttempt = 0;
        this.events.onStatusChange("connected");
        this.events.onReady(this.sessionId);
        break;
      case "input_transcript":
        this.events.onTranscript("user", message.text as string, Boolean(message.final));
        break;
      case "output_transcript":
        this.events.onTranscript("lantern", message.text as string, Boolean(message.final));
        break;
      case "turn_complete":
        this.events.onTurnComplete();
        break;
      case "audio":
        this.events.onAudio(base64ToArrayBuffer(message.audio as string));
        break;
      case "error":
        this.events.onError(message.message as string);
        break;
    }
  }

  private scheduleReconnect(): void {
    const delay = RECONNECT_DELAYS_MS[Math.min(this.reconnectAttempt, RECONNECT_DELAYS_MS.length - 1)];
    this.reconnectAttempt += 1;
    this.reconnectTimer = window.setTimeout(() => this.connect(), delay);
  }

  sendAudioChunk(pcm16: ArrayBuffer): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(pcm16);
    }
  }

  sendVideoFrame(base64Jpeg: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "video_frame", data: base64Jpeg }));
    }
  }

  close(): void {
    this.closedByUser = true;
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
    }
    this.ws?.close();
  }
}

function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}
