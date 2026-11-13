import { useCallback, useEffect, useRef, useState } from 'react';

export const MAX_RECORDING_MS = 30_000;

export class MicPermissionError extends Error {}

interface Options {
  /** Each 100 ms chunk of 16 kHz, 16-bit mono PCM. */
  onChunk: (chunk: ArrayBuffer) => void;
  /** Called when the 30 s cap is reached; the recording is already stopped. */
  onAutoStop: () => void;
}

interface Active {
  ctx: AudioContext;
  stream: MediaStream;
  node: AudioWorkletNode;
  source: MediaStreamAudioSourceNode;
  timer: ReturnType<typeof setTimeout>;
}

/**
 * Mic -> AudioWorklet (public/pcm-worklet.js) -> PCM chunks.
 * start() must be called directly from the tap handler: the AudioContext is created
 * synchronously inside the user gesture (needed on iPhone Safari), before any await.
 */
export function useVoiceRecorder({ onChunk, onAutoStop }: Options) {
  const [isRecording, setIsRecording] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const activeRef = useRef<Active | null>(null);
  const onChunkRef = useRef(onChunk);
  const onAutoStopRef = useRef(onAutoStop);
  useEffect(() => {
    onChunkRef.current = onChunk;
    onAutoStopRef.current = onAutoStop;
  });

  const teardown = useCallback(async (active: Active) => {
    clearTimeout(active.timer);
    // Ask the worklet for its last partial chunk, so no audio is lost before "stop".
    await new Promise<void>((resolve) => {
      const done = setTimeout(resolve, 300);
      const prev = active.node.port.onmessage;
      active.node.port.onmessage = (event) => {
        prev?.call(active.node.port, event);
        if (event.data?.type === 'flushed') {
          clearTimeout(done);
          resolve();
        }
      };
      active.node.port.postMessage('flush');
    });
    active.source.disconnect();
    active.node.disconnect();
    active.stream.getTracks().forEach((t) => t.stop());
    await active.ctx.close().catch(() => {});
  }, []);

  const stop = useCallback(async () => {
    const active = activeRef.current;
    if (!active) return;
    activeRef.current = null;
    setIsRecording(false);
    setStartedAt(null);
    await teardown(active);
  }, [teardown]);

  const start = useCallback(async () => {
    if (activeRef.current) return;
    // Created synchronously inside the tap (user gesture), before any await.
    const ctx = new AudioContext();
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
    } catch (err) {
      await ctx.close().catch(() => {});
      const name = (err as DOMException)?.name;
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        throw new MicPermissionError('Microphone access is blocked. Allow the mic for this site in your browser settings.');
      }
      if (name === 'NotFoundError') throw new MicPermissionError('No microphone was found on this device.');
      throw new MicPermissionError("Couldn't start the microphone.");
    }
    try {
      await ctx.audioWorklet.addModule('/pcm-worklet.js');
      if (ctx.state === 'suspended') await ctx.resume();
      const source = ctx.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(ctx, 'pcm-worklet');
      node.port.onmessage = (event) => {
        if (event.data?.type === 'chunk') onChunkRef.current(event.data.buffer as ArrayBuffer);
      };
      // A silent path to the output keeps the worklet running in every browser.
      const mute = ctx.createGain();
      mute.gain.value = 0;
      source.connect(node);
      node.connect(mute).connect(ctx.destination);

      const timer = setTimeout(() => {
        stop().then(() => onAutoStopRef.current());
      }, MAX_RECORDING_MS);
      activeRef.current = { ctx, stream, node, source, timer };
      setIsRecording(true);
      setStartedAt(Date.now());
    } catch (err) {
      stream.getTracks().forEach((t) => t.stop());
      await ctx.close().catch(() => {});
      throw err;
    }
  }, [stop]);

  // Never leave the mic on after leaving the page.
  useEffect(() => () => {
    const active = activeRef.current;
    activeRef.current = null;
    if (active) teardown(active);
  }, [teardown]);

  return { start, stop, isRecording, startedAt };
}
