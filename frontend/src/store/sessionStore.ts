/** Jonli sessiya holati (Zustand): ulanish, transkript, xatolar, skorlar, daraja. */
import { create } from "zustand";
import type { PlanInfo } from "../lib/api";

export interface LimitInfo extends PlanInfo {
  message: string;
}

export type SessionStatus = "idle" | "connecting" | "ready" | "reconnecting" | "ended" | "error";
export type MicMode = "free" | "ptt";
export type Role = "user" | "adam";

export interface TranscriptLine {
  id: number;
  role: Role;
  text: string;
  final: boolean;
}

export interface LiveError {
  id: number;
  error_type: "grammar" | "pronunciation" | "vocabulary";
  wrong: string;
  correct: string;
  severity: "low" | "medium" | "high";
  explanation: string | null;
  at: number;
}

export interface Scores {
  fluency: number | null;
  grammar: number | null;
  pronunciation: number | null;
  comprehension: number | null;
}

export interface LevelState {
  level: string;
  next_level: string | null;
  progress: number;
  gain?: number;
  leveled_up?: boolean;
  final?: boolean;
}

export interface SessionSummary {
  session_id: string;
  duration_seconds: number;
  sentences_spoken: number;
  words_spoken: number;
  scores: Scores;
  errors_count: number;
  new_words: string[];
  level: LevelState;
}

const MODE_KEY = "adam.micMode";
const MAX_LINES = 40;

function loadMode(): MicMode {
  try {
    return localStorage.getItem(MODE_KEY) === "ptt" ? "ptt" : "free";
  } catch {
    return "free";
  }
}

interface SessionState {
  status: SessionStatus;
  mode: MicMode;
  micActive: boolean;
  adamSpeaking: boolean;
  lines: TranscriptLine[];
  errors: LiveError[];
  dismissed: number[];
  scores: Scores | null;
  baseLevel: LevelState | null;
  level: LevelState | null;
  stats: { sentences: number; words: number };
  vocab: string[];
  startedAt: number | null;
  timeoutSeconds: number;
  warning: string | null;
  errorMessage: string | null;
  summary: SessionSummary | null;
  placement: boolean;
  placementResult: { level: string; reason: string | null } | null;
  limit: LimitInfo | null;

  setMode: (mode: MicMode) => void;
  setStatus: (status: SessionStatus, errorMessage?: string | null) => void;
  setMicActive: (v: boolean) => void;
  setAdamSpeaking: (v: boolean) => void;
  onReady: (p: {
    level: string;
    next_level: string | null;
    progress: number;
    timeout_seconds: number;
    placement?: boolean;
  }) => void;
  setPlacementResult: (p: { level: string; next_level: string | null; reason: string | null }) => void;
  setLimit: (l: LimitInfo) => void;
  appendTranscript: (role: Role, text: string) => void;
  finalizeLines: () => void;
  addError: (e: Omit<LiveError, "at">) => void;
  dismissError: (id: number) => void;
  setScores: (s: Scores) => void;
  setLevel: (l: LevelState) => void;
  setStats: (sentences: number, words: number) => void;
  addVocab: (word: string) => void;
  setWarning: (w: string | null) => void;
  setSummary: (s: SessionSummary) => void;
  reset: () => void;
}

let lineSeq = 0;

const initial = {
  status: "idle" as SessionStatus,
  micActive: false,
  adamSpeaking: false,
  lines: [] as TranscriptLine[],
  errors: [] as LiveError[],
  dismissed: [] as number[],
  scores: null,
  baseLevel: null,
  level: null,
  stats: { sentences: 0, words: 0 },
  vocab: [] as string[],
  startedAt: null,
  timeoutSeconds: 900,
  warning: null,
  errorMessage: null,
  summary: null,
  placement: false,
  placementResult: null,
  limit: null as LimitInfo | null,
};

export const useSessionStore = create<SessionState>((set) => ({
  ...initial,
  mode: loadMode(),

  setMode: (mode) => {
    try {
      localStorage.setItem(MODE_KEY, mode);
    } catch {
      /* private mode */
    }
    set({ mode });
  },
  setStatus: (status, errorMessage = null) => set({ status, errorMessage }),
  setMicActive: (micActive) => set({ micActive }),
  setAdamSpeaking: (adamSpeaking) => set({ adamSpeaking }),
  onReady: (p) =>
    set((s) => {
      const level = { level: p.level, next_level: p.next_level, progress: p.progress };
      return {
        status: "ready",
        errorMessage: null,
        timeoutSeconds: p.timeout_seconds,
        placement: Boolean(p.placement),
        startedAt: s.startedAt ?? Date.now(),
        baseLevel: s.baseLevel ?? level,
        level: s.level ?? level,
      };
    }),
  setLimit: (limit) => set({ limit }),
  setPlacementResult: (p) =>
    set(() => {
      const level = { level: p.level, next_level: p.next_level, progress: 0 };
      return { placement: false, placementResult: { level: p.level, reason: p.reason }, level, baseLevel: level };
    }),
  appendTranscript: (role, text) =>
    set((s) => {
      const lines = s.lines.slice();
      const last = lines[lines.length - 1];
      if (last && last.role === role && !last.final) {
        lines[lines.length - 1] = { ...last, text: last.text + text };
      } else {
        if (last && !last.final) lines[lines.length - 1] = { ...last, final: true };
        lines.push({ id: ++lineSeq, role, text: text.trimStart(), final: false });
      }
      return { lines: lines.slice(-MAX_LINES) };
    }),
  finalizeLines: () => set((s) => ({ lines: s.lines.map((l) => (l.final ? l : { ...l, final: true })) })),
  addError: (e) => set((s) => ({ errors: [{ ...e, at: Date.now() }, ...s.errors].slice(0, 50) })),
  dismissError: (id) => set((s) => ({ dismissed: [...s.dismissed, id] })),
  setScores: (scores) => set({ scores }),
  setLevel: (level) => set({ level }),
  setStats: (sentences, words) => set({ stats: { sentences, words } }),
  addVocab: (word) => set((s) => (s.vocab.includes(word) ? s : { vocab: [...s.vocab, word] })),
  setWarning: (warning) => set({ warning }),
  setSummary: (summary) =>
    set({ summary, status: "ended", level: summary.level, micActive: false, adamSpeaking: false }),
  reset: () => set({ ...initial, lines: [], errors: [], dismissed: [], vocab: [] }),
}));
