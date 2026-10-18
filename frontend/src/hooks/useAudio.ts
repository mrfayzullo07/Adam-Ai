/**
 * Audio dvigateli (Web Audio API + AudioWorklet):
 *  - startRecording(onChunk): getUserMedia (16 kHz, mono, AEC, NS) -> worklet -> Int16 PCM 100 ms chunk
 *  - stopRecording(): mikrofonni to'liq yopadi (Telegram'dagi qizil indikator o'chadi)
 *  - playPcm(buf): kelgan 24 kHz PCM16 ni AudioBufferSourceNode orqali uzluksiz navbat bilan ijro etadi
 *  - stopPlayback(): barge-in (interrupted) bo'lganda navbatni darhol to'xtatadi
 *  - getMicLevel / getOutputLevel: animatsiyalar uchun 0..1 daraja (re-render qilmaydi)
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export const INPUT_RATE = 16000;
export const OUTPUT_RATE = 24000;
const WORKLET_URL = "/worklets/pcm-recorder.js";
/** Navbat bo'sh bo'lganda (yangi gap yoki tarmoq kechikishi) shuncha zaxira bilan boshlaymiz — tutilish bo'lmasin */
const JITTER_LEAD_S = 0.18;
/** Adam ovozi tugagandan keyin xonadagi aks-sado shuncha vaqt mikrofonga tushishi mumkin */
const ECHO_TAIL_S = 0.35;

export type MicErrorCode = "denied" | "not_found" | "unsupported" | "busy" | "unknown";

export class MicError extends Error {
  constructor(
    public code: MicErrorCode,
    message: string,
  ) {
    super(message);
  }
}

function toMicError(err: unknown): MicError {
  const name = (err as DOMException)?.name;
  if (name === "NotAllowedError" || name === "SecurityError")
    return new MicError("denied", "Mikrofonga ruxsat berilmadi. Telegram sozlamalaridan ruxsat bering.");
  if (name === "NotFoundError" || name === "OverconstrainedError")
    return new MicError("not_found", "Mikrofon topilmadi.");
  if (name === "NotReadableError") return new MicError("busy", "Mikrofon boshqa ilova tomonidan band.");
  return new MicError("unknown", "Mikrofonni ishga tushirib bo'lmadi.");
}

export interface AudioApi {
  startRecording: (onChunk: (pcm: ArrayBuffer, rms: number) => void) => Promise<void>;
  stopRecording: () => void;
  unlock: () => Promise<void>;
  playPcm: (data: ArrayBuffer) => void;
  stopPlayback: () => void;
  getMicLevel: () => number;
  getOutputLevel: () => number;
  /** Hozir Adam ovozi ijro etilyaptimi (render'siz, aniq qiymat) */
  isOutputActive: () => boolean;
  isRecording: boolean;
  isPlaying: boolean;
}

export function useAudio(): AudioApi {
  const ctxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const workletLoaded = useRef(false);
  const micLevel = useRef(0);

  const outGain = useRef<GainNode | null>(null);
  const analyser = useRef<AnalyserNode | null>(null);
  const analyserBuf = useRef<Uint8Array<ArrayBuffer> | null>(null);
  const playing = useRef(new Set<AudioBufferSourceNode>());
  const nextTime = useRef(0);

  const [isRecording, setRecording] = useState(false);
  const [isPlaying, setPlaying] = useState(false);

  /** AudioContext'ni yaratadi/uyg'otadi. iOS uchun foydalanuvchi bosishi ichida chaqirilishi kerak. */
  const ensureContext = useCallback(async (): Promise<AudioContext> => {
    let ctx = ctxRef.current;
    if (!ctx || ctx.state === "closed") {
      const Ctor = window.AudioContext || window.webkitAudioContext;
      if (!Ctor) throw new MicError("unsupported", "Brauzer Web Audio'ni qo'llab-quvvatlamaydi.");
      ctx = new Ctor({ latencyHint: "interactive" });
      ctxRef.current = ctx;
      workletLoaded.current = false;

      const gain = ctx.createGain();
      const an = ctx.createAnalyser();
      an.fftSize = 512;
      gain.connect(an);
      an.connect(ctx.destination);
      outGain.current = gain;
      analyser.current = an;
      analyserBuf.current = new Uint8Array(new ArrayBuffer(an.fftSize));
      nextTime.current = 0;
    }
    if (ctx.state === "suspended") await ctx.resume();
    return ctx;
  }, []);

  const unlock = useCallback(async () => {
    await ensureContext();
  }, [ensureContext]);

  const stopRecording = useCallback(() => {
    try {
      workletRef.current?.port.postMessage({ type: "flush" });
      workletRef.current?.disconnect();
      sourceRef.current?.disconnect();
    } catch {
      /* allaqachon uzilgan */
    }
    if (workletRef.current) workletRef.current.port.onmessage = null;
    workletRef.current = null;
    sourceRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    micLevel.current = 0;
    setRecording(false);
  }, []);

  const startRecording = useCallback(
    async (onChunk: (pcm: ArrayBuffer, rms: number) => void) => {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new MicError("unsupported", "Bu qurilmada mikrofon qo'llab-quvvatlanmaydi.");
      }
      const ctx = await ensureContext();
      if (!ctx.audioWorklet) throw new MicError("unsupported", "AudioWorklet qo'llab-quvvatlanmaydi. Telegram'ni yangilang.");
      stopRecording();

      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
          video: false,
        });
      } catch (err) {
        throw toMicError(err);
      }

      if (!workletLoaded.current) {
        await ctx.audioWorklet.addModule(WORKLET_URL);
        workletLoaded.current = true;
      }

      const source = ctx.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(ctx, "pcm-recorder", {
        numberOfInputs: 1,
        numberOfOutputs: 0,
        channelCount: 1,
        channelCountMode: "explicit",
        processorOptions: { targetRate: INPUT_RATE, chunkMs: 100 },
      });
      node.port.onmessage = (e: MessageEvent<{ type: string; buffer: ArrayBuffer; level: number }>) => {
        if (e.data?.type !== "chunk") return;
        micLevel.current = Math.min(1, e.data.level * 4);
        onChunk(e.data.buffer, e.data.level);
      };
      source.connect(node);

      streamRef.current = stream;
      sourceRef.current = source;
      workletRef.current = node;
      setRecording(true);
    },
    [ensureContext, stopRecording],
  );

  const playPcm = useCallback((data: ArrayBuffer) => {
    const ctx = ctxRef.current;
    const gain = outGain.current;
    if (!ctx || !gain || data.byteLength < 2) return;
    const int16 = new Int16Array(data, 0, Math.floor(data.byteLength / 2));
    const buffer = ctx.createBuffer(1, int16.length, OUTPUT_RATE);
    const ch = buffer.getChannelData(0);
    for (let i = 0; i < int16.length; i++) ch[i] = int16[i] / (int16[i] < 0 ? 0x8000 : 0x7fff);

    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(gain);
    // Jitter-bufer: navbat tugab qolgan bo'lsa (underrun) zaxira bilan qayta boshlaymiz,
    // aks holda oldingi bo'lak oxiriga uzluksiz ulaymiz
    const underrun = nextTime.current < ctx.currentTime + 0.02;
    const startAt = underrun ? ctx.currentTime + JITTER_LEAD_S : nextTime.current;
    src.start(startAt);
    nextTime.current = startAt + buffer.duration;
    playing.current.add(src);
    setPlaying(true);
    src.onended = () => {
      playing.current.delete(src);
      if (playing.current.size === 0) setPlaying(false);
    };
  }, []);

  const stopPlayback = useCallback(() => {
    playing.current.forEach((src) => {
      try {
        src.onended = null;
        src.stop();
        src.disconnect();
      } catch {
        /* allaqachon to'xtagan */
      }
    });
    playing.current.clear();
    nextTime.current = 0;
    setPlaying(false);
  }, []);

  const getMicLevel = useCallback(() => micLevel.current, []);
  const isOutputActive = useCallback(() => {
    if (playing.current.size > 0) return true;
    const ctx = ctxRef.current;
    return !!ctx && nextTime.current > 0 && ctx.currentTime < nextTime.current + ECHO_TAIL_S;
  }, []);

  const getOutputLevel = useCallback(() => {
    const an = analyser.current;
    const buf = analyserBuf.current;
    if (!an || !buf || playing.current.size === 0) return 0;
    an.getByteTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) {
      const v = (buf[i] - 128) / 128;
      sum += v * v;
    }
    return Math.min(1, Math.sqrt(sum / buf.length) * 3);
  }, []);

  // Komponent yo'qolganda hammasini tozalash
  useEffect(
    () => () => {
      stopRecording();
      stopPlayback();
      ctxRef.current?.close().catch(() => undefined);
      ctxRef.current = null;
    },
    [stopRecording, stopPlayback],
  );

  return useMemo(
    () => ({
      startRecording,
      stopRecording,
      unlock,
      playPcm,
      stopPlayback,
      getMicLevel,
      getOutputLevel,
      isOutputActive,
      isRecording,
      isPlaying,
    }),
    [
      startRecording,
      stopRecording,
      unlock,
      playPcm,
      stopPlayback,
      getMicLevel,
      getOutputLevel,
      isOutputActive,
      isRecording,
      isPlaying,
    ],
  );
}
