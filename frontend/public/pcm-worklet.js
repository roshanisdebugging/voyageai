// Voice step 1: converts mic audio (44.1/48 kHz float) to 16 kHz, 16-bit mono PCM.
// Posts {type:'chunk', buffer} every 1,600 samples (100 ms). On 'flush' it posts what's left,
// then {type:'flushed'}, so the app can send "stop" only after the last audio.
const TARGET_RATE = 16000;
const CHUNK_SAMPLES = 1600;

class PcmWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE; // `sampleRate` is a global in the worklet scope
    this.pos = 0;
    this.acc = 0;
    this.accCount = 0;
    this.out = new Int16Array(CHUNK_SAMPLES);
    this.count = 0;
    this.port.onmessage = (event) => {
      if (event.data === 'flush') {
        if (this.count > 0) this.post(this.out.slice(0, this.count));
        this.out = new Int16Array(CHUNK_SAMPLES);
        this.count = 0;
        this.port.postMessage({ type: 'flushed' });
      }
    };
  }

  post(samples) {
    const buffer = samples.buffer;
    this.port.postMessage({ type: 'chunk', buffer }, [buffer]);
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    for (let i = 0; i < channel.length; i++) {
      // Average the input samples that fall into one output sample (simple low-pass + downsample).
      this.acc += channel[i];
      this.accCount += 1;
      this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        const v = Math.max(-1, Math.min(1, this.acc / this.accCount));
        this.acc = 0;
        this.accCount = 0;
        this.out[this.count++] = v < 0 ? v * 0x8000 : v * 0x7fff;
        if (this.count === CHUNK_SAMPLES) {
          this.post(this.out);
          this.out = new Int16Array(CHUNK_SAMPLES);
          this.count = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor('pcm-worklet', PcmWorklet);
