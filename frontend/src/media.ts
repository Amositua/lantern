export async function startCamera(videoEl: HTMLVideoElement): Promise<MediaStream> {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: "environment" },
    audio: true,
  });
  videoEl.srcObject = stream;
  await videoEl.play();
  return stream;
}

export async function startMicCapture(
  stream: MediaStream,
  onChunk: (pcm16: ArrayBuffer) => void,
): Promise<{ stop: () => void }> {
  const audioContext = new AudioContext();
  await audioContext.audioWorklet.addModule("/pcm-worklet.js");

  const source = audioContext.createMediaStreamSource(stream);
  const worklet = new AudioWorkletNode(audioContext, "pcm-capture-processor");
  worklet.port.onmessage = (event: MessageEvent<ArrayBuffer>) => onChunk(event.data);
  source.connect(worklet);

  return {
    stop: () => {
      worklet.port.onmessage = null;
      source.disconnect();
      worklet.disconnect();
      void audioContext.close();
    },
  };
}

export function startFrameCapture(
  videoEl: HTMLVideoElement,
  onFrame: (base64Jpeg: string) => void,
  intervalMs = 1000,
): () => void {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");

  const timer = window.setInterval(() => {
    if (!context || videoEl.videoWidth === 0) {
      return;
    }
    canvas.width = videoEl.videoWidth;
    canvas.height = videoEl.videoHeight;
    context.drawImage(videoEl, 0, 0, canvas.width, canvas.height);
    const dataUrl = canvas.toDataURL("image/jpeg", 0.7);
    const base64 = dataUrl.slice(dataUrl.indexOf(",") + 1);
    onFrame(base64);
  }, intervalMs);

  return () => window.clearInterval(timer);
}
