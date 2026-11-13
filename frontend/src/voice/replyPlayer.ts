/**
 * Plays the spoken voice reply (voicefirst.md step 1b).
 *
 * iPhone Safari blocks audio that starts without a user gesture, and the reply arrives seconds
 * after the tap. So there is ONE playback AudioContext, created/resumed by prime() inside the mic
 * tap handler (the same gesture that starts recording) and kept open. Replies are decoded with
 * decodeAudioData and played through an AudioBufferSourceNode on that context.
 * Separate from the recorder's AudioContext, which is closed when recording stops.
 */
class ReplyPlayer {
  private ctx: AudioContext | null = null;
  private source: AudioBufferSourceNode | null = null;
  private finish: (() => void) | null = null;
  private generation = 0; // bumped by stop(): a reply stopped while decoding never starts late
  isPlaying = false;

  /** Call synchronously inside a user gesture, before any await. */
  prime() {
    if (!this.ctx || this.ctx.state === 'closed') this.ctx = new AudioContext();
    if (this.ctx.state === 'suspended') void this.ctx.resume();
    // A silent one-sample buffer, started inside the gesture, unlocks playback on iOS.
    try {
      const silent = this.ctx.createBuffer(1, 1, this.ctx.sampleRate);
      const node = this.ctx.createBufferSource();
      node.buffer = silent;
      node.connect(this.ctx.destination);
      node.start(0);
    } catch {
      /* not fatal */
    }
  }

  /**
   * Plays base64 audio (WAV from Sarvam). Resolves when playback finishes or is stopped.
   * onStart fires the moment sound starts (for timing).
   */
  async play(base64: string, _mime = 'audio/wav', onStart?: () => void): Promise<void> {
    this.stop();
    const myGeneration = this.generation;
    if (!this.ctx || this.ctx.state === 'closed') throw new Error('Playback was not started from a tap.');
    if (this.ctx.state === 'suspended') await this.ctx.resume();

    const bin = atob(base64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const buffer = await this.ctx.decodeAudioData(bytes.buffer);
    if (myGeneration !== this.generation || !this.ctx) return; // stopped (barge-in) while decoding

    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.ctx.destination);
    this.source = source;
    return new Promise<void>((resolve) => {
      this.finish = resolve;
      source.onended = () => {
        if (this.source === source) {
          this.source = null;
          this.isPlaying = false;
          this.finish = null;
        }
        resolve();
      };
      this.isPlaying = true;
      source.start();
      onStart?.();
    });
  }

  /** Stops playback at once (barge-in, new recording, logout). */
  stop() {
    this.generation++;
    const source = this.source;
    this.source = null;
    if (source) {
      source.onended = null;
      try { source.stop(); } catch { /* already stopped */ }
      source.disconnect();
    }
    this.isPlaying = false;
    const finish = this.finish;
    this.finish = null;
    finish?.();
  }

  /** Stops and releases the playback context (unmount / logout). */
  close() {
    this.stop();
    const ctx = this.ctx;
    this.ctx = null;
    void ctx?.close().catch(() => {});
  }
}

export const replyPlayer = new ReplyPlayer();
