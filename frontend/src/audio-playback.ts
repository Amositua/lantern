/** Schedules incoming PCM16 audio chunks back-to-back for gapless playback. */
export class AudioPlaybackQueue {
  private context: AudioContext;
  private nextStartTime = 0;

  constructor(sampleRate = 24000) {
    this.context = new AudioContext({ sampleRate });
  }

  enqueue(pcm16: ArrayBuffer): void {
    const int16 = new Int16Array(pcm16);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 0x8000;
    }

    const buffer = this.context.createBuffer(1, float32.length, this.context.sampleRate);
    buffer.copyToChannel(float32, 0);

    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);

    const startAt = Math.max(this.context.currentTime, this.nextStartTime);
    source.start(startAt);
    this.nextStartTime = startAt + buffer.duration;
  }

  async resume(): Promise<void> {
    if (this.context.state === "suspended") {
      await this.context.resume();
    }
  }

  close(): void {
    void this.context.close();
  }
}
