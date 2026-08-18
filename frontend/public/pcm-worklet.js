// Runs on the audio rendering thread. Downsamples the mic's native sample
// rate down to the 16kHz mono PCM16 Gemini Live expects for input audio,
// and posts fixed-size chunks back to the main thread.
const TARGET_SAMPLE_RATE = 16000;
const CHUNK_SAMPLES = 800; // ~50ms at 16kHz

class PCMCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._ratio = sampleRate / TARGET_SAMPLE_RATE;
    this._raw = [];
    this._phase = 0;
    this._outBuffer = [];
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) {
      return true;
    }

    for (let i = 0; i < channel.length; i++) {
      this._raw.push(channel[i]);
    }

    while (this._phase + this._ratio <= this._raw.length) {
      this._outBuffer.push(this._raw[Math.floor(this._phase)]);
      this._phase += this._ratio;
    }

    const consumed = Math.floor(this._phase);
    this._raw.splice(0, consumed);
    this._phase -= consumed;

    while (this._outBuffer.length >= CHUNK_SAMPLES) {
      const chunk = this._outBuffer.splice(0, CHUNK_SAMPLES);
      const pcm16 = new Int16Array(chunk.length);
      for (let i = 0; i < chunk.length; i++) {
        const sample = Math.max(-1, Math.min(1, chunk[i]));
        pcm16[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      }
      this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
    }

    return true;
  }
}

registerProcessor("pcm-capture-processor", PCMCaptureProcessor);
