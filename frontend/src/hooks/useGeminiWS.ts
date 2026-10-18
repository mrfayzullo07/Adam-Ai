/**
 * Backend /ws/audio bilan WebSocket aloqasi.
 *  - binary: client->server PCM16 16 kHz; server->client PCM16 24 kHz
 *  - JSON: transkriptlar, xatolar, skorlar, daraja, ogohlantirishlar, yakuniy xulosa
 *  - kutilmagan uzilishda exponential backoff bilan qayta ulanadi (1s, 2s, 4s, 8s, 16s)
 */
import { useCallback, useEffect, useMemo, useRef } from "react";
import { getInitData, wsUrl } from "../lib/api";
import { haptic } from "./useTelegram";
import { useSessionStore, type MicMode, type SessionSummary } from "../store/sessionStore";

const MAX_RECONNECTS = 5;
const PING_INTERVAL = 20_000;
/** Bu kodlar bilan yopilsa qayta ulanmaymiz. */
const FATAL_CLOSE = new Set([1000, 4401, 4402, 4503]);
const FATAL_SERVER_ERRORS = new Set(["unauthorized", "gemini_unavailable", "rate_limited"]);

export interface WSCallbacks {
  onAudio: (data: ArrayBuffer) => void;
  onInterrupted: () => void;
  onConnected?: () => void;
  onClosed?: () => void;
}

type ServerEvent = { type: string; [key: string]: unknown };

export function useGeminiWS(callbacks: WSCallbacks) {
  const cb = useRef(callbacks);
  cb.current = callbacks;

  const wsRef = useRef<WebSocket | null>(null);
  const modeRef = useRef<MicMode>("free");
  const topicRef = useRef<string | null>(null);
  const intentional = useRef(false);
  const attempts = useRef(0);
  const retryTimer = useRef<number | null>(null);
  const pingTimer = useRef<number | null>(null);
  const endResolver = useRef<(() => void) | null>(null);
  const fatalError = useRef(false);

  const clearTimers = () => {
    if (retryTimer.current) window.clearTimeout(retryTimer.current);
    if (pingTimer.current) window.clearInterval(pingTimer.current);
    retryTimer.current = null;
    pingTimer.current = null;
  };

  const handleEvent = useCallback((ev: ServerEvent) => {
    const s = useSessionStore.getState();
    switch (ev.type) {
      case "ready":
        attempts.current = 0;
        s.onReady(ev as never);
        cb.current.onConnected?.();
        break;
      case "user_transcript":
        s.appendTranscript("user", String(ev.text ?? ""));
        break;
      case "adam_transcript":
        s.appendTranscript("adam", String(ev.text ?? ""));
        break;
      case "turn_complete": {
        s.finalizeLines();
        const stats = ev.stats as { sentences_spoken: number; words_spoken: number } | undefined;
        if (stats) s.setStats(stats.sentences_spoken, stats.words_spoken);
        break;
      }
      case "interrupted":
        cb.current.onInterrupted();
        s.finalizeLines();
        break;
      case "error":
        s.addError(ev as never);
        haptic("warning");
        break;
      case "scores":
        s.setScores(ev as never);
        break;
      case "level_update":
        s.setLevel(ev as never);
        break;
      case "limit_reached":
        s.setLimit(ev as never);
        haptic("warning");
        if (s.status !== "ready") {
          // Sessiya boshlanmasdan limit tugagan
          fatalError.current = true;
          s.setStatus("error", String(ev.message ?? "Vaqt limiti tugadi"));
        }
        break;
      case "placement_result":
        s.setPlacementResult({
          level: String(ev.level),
          next_level: (ev.next_level as string | null) ?? null,
          reason: (ev.reason as string | null) ?? null,
        });
        haptic("success");
        break;
      case "vocabulary":
        s.addVocab(String(ev.word ?? ""));
        break;
      case "warning":
        s.setWarning(String(ev.message ?? ""));
        break;
      case "session_end":
        intentional.current = true;
        s.setSummary(ev as unknown as SessionSummary);
        haptic("success");
        endResolver.current?.();
        break;
      case "server_error": {
        const code = String(ev.code ?? "");
        const message = String(ev.message ?? "Xatolik yuz berdi");
        // Qayta ulanish paytida eski sessiya hali yopilmagan bo'lishi mumkin — active_session'ni qayta sinaymiz
        const retryable = code === "active_session" && s.status === "reconnecting" && attempts.current < MAX_RECONNECTS;
        if (FATAL_SERVER_ERRORS.has(code) || (code === "active_session" && !retryable)) {
          fatalError.current = true;
          s.setStatus("error", message);
          haptic("error");
        }
        break;
      }
      default:
        break;
    }
  }, []);

  const open = useCallback(() => {
    const initData = getInitData();
    if (!initData) {
      useSessionStore.getState().setStatus("error", "Ilovani Telegram ichidan oching");
      return;
    }
    fatalError.current = false;
    const topicParam = topicRef.current ? `&topic=${encodeURIComponent(topicRef.current)}` : "";
    const url = wsUrl(`/ws/audio?init_data=${encodeURIComponent(initData)}&mode=${modeRef.current}${topicParam}`);
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      pingTimer.current = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping", t: Date.now() }));
      }, PING_INTERVAL);
    };

    ws.onmessage = (msg: MessageEvent<ArrayBuffer | string>) => {
      if (typeof msg.data !== "string") {
        cb.current.onAudio(msg.data);
        return;
      }
      try {
        handleEvent(JSON.parse(msg.data) as ServerEvent);
      } catch (err) {
        console.warn("WS xabarini o'qib bo'lmadi", err);
      }
    };

    ws.onclose = (e: CloseEvent) => {
      clearTimers();
      if (wsRef.current === ws) wsRef.current = null;
      cb.current.onClosed?.();
      endResolver.current?.();
      const store = useSessionStore.getState();
      if (intentional.current || fatalError.current || FATAL_CLOSE.has(e.code) || store.status === "ended") {
        if (!fatalError.current && store.status !== "ended" && store.status !== "error") store.setStatus("idle");
        return;
      }
      if (attempts.current >= MAX_RECONNECTS) {
        store.setStatus("error", "Aloqa uzildi. Internetni tekshirib, qayta urinib ko'ring.");
        return;
      }
      const delay = Math.min(16_000, 1000 * 2 ** attempts.current);
      attempts.current += 1;
      store.setStatus("reconnecting");
      retryTimer.current = window.setTimeout(open, delay);
    };

    ws.onerror = () => {
      /* onclose albatta chaqiriladi — qayta ulanish o'sha yerda */
    };
  }, [handleEvent]);

  const connect = useCallback(
    (mode: MicMode, topic: string | null = null) => {
      clearTimers();
      wsRef.current?.close(1000);
      modeRef.current = mode;
      topicRef.current = topic;
      intentional.current = false;
      attempts.current = 0;
      useSessionStore.getState().setStatus("connecting");
      open();
    },
    [open],
  );

  const sendAudio = useCallback((data: ArrayBuffer) => {
    const ws = wsRef.current;
    // Sekin tarmoqda bufer to'lib ketsa eski audio'ni tashlab yuboramiz (kechikish to'planmasin)
    if (ws && ws.readyState === WebSocket.OPEN && ws.bufferedAmount < 256_000) ws.send(data);
  }, []);

  const sendJSON = useCallback((payload: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
  }, []);

  /** Sessiyani to'g'ri yakunlaydi: "end" yuboradi va session_end xulosasini kutadi (max 6 s). */
  const end = useCallback(async () => {
    intentional.current = true;
    clearTimers();
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      if (useSessionStore.getState().status !== "ended") useSessionStore.getState().setStatus("idle");
      return;
    }
    await new Promise<void>((resolve) => {
      const timer = window.setTimeout(resolve, 6000);
      endResolver.current = () => {
        window.clearTimeout(timer);
        endResolver.current = null;
        resolve();
      };
      ws.send(JSON.stringify({ type: "end" }));
    });
    ws.close(1000);
  }, []);

  const disconnect = useCallback(() => {
    intentional.current = true;
    clearTimers();
    wsRef.current?.close(1000);
    wsRef.current = null;
  }, []);

  useEffect(() => disconnect, [disconnect]);

  return useMemo(() => ({ connect, sendAudio, sendJSON, end, disconnect }), [connect, sendAudio, sendJSON, end, disconnect]);
}
