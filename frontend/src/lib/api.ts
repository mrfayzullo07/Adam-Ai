/** Backend REST kliyenti va tiplar. Har so'rovda `Authorization: tma <initData>`. */

export interface LevelInfo {
  level: string;
  next_level: string | null;
  progress: number;
}

export interface SessionOut {
  id: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  sentences_spoken: number;
  words_spoken: number;
  fluency_score: number | null;
  grammar_score: number | null;
  pronunciation_score: number | null;
  comprehension_score: number | null;
  mode: string;
  level_at_start: string;
  summary: string | null;
}

export interface DailyProgress {
  date: string;
  sessions_count: number;
  total_sentences: number;
  total_words: number;
  cefr_level: string;
}

export type CefrLevel = "A1" | "A2" | "B1" | "B2" | "C1" | "C2";
export type ExplainLang = "uz" | "mix" | "en";
export type SpeechPace = "slow" | "normal";
export type Goal = "general" | "travel" | "work" | "ielts";
export type MicModeSetting = "free" | "ptt";

export interface UserSettings {
  cefr_level: CefrLevel;
  explain_lang: ExplainLang;
  speech_pace: SpeechPace;
  goal: Goal;
  mic_mode: MicModeSetting;
  needs_placement: boolean;
  onboarded: boolean;
}

export interface UserOut extends UserSettings {
  telegram_id: number;
  username: string | null;
  first_name: string;
  level_progress: number;
}

export type PlanCode = "free" | "pro" | "max";

export interface PlanInfo {
  plan: PlanCode;
  plan_title: string;
  plan_expires_at: string | null;
  limit_seconds: number | null;
  window_hours: number | null;
  used_seconds: number;
  remaining_seconds: number | null;
  resets_at: string | null;
}

export interface PlanCatalogItem {
  code: PlanCode;
  title: string;
  price: number;
  limit_seconds: number | null;
  window_hours: number | null;
  groups: boolean;
}

export interface PlansResponse {
  plans: PlanCatalogItem[];
  plan_days: number;
  bot_username: string | null;
  current: PlanInfo;
}

export interface MeResponse {
  user: UserOut;
  level: LevelInfo;
  streak_days: number;
  today: DailyProgress | null;
  last_session: SessionOut | null;
  plan: PlanInfo;
}

export interface ProgressResponse {
  level: LevelInfo;
  streak_days: number;
  days: DailyProgress[];
  totals: Record<"sessions" | "minutes" | "sentences" | "words" | "vocabulary" | "errors", number>;
  average_scores: Record<"fluency" | "grammar" | "pronunciation" | "comprehension", number | null>;
}

export interface ErrorItem {
  id: number;
  session_id: string;
  error_type: "grammar" | "pronunciation" | "vocabulary";
  wrong_text: string;
  correct_text: string;
  severity: "low" | "medium" | "high";
  explanation: string | null;
  created_at: string;
}

export interface ErrorsResponse {
  items: ErrorItem[];
  by_type: Record<string, number>;
  by_severity: Record<string, number>;
}

export interface VocabularyItem {
  word: string;
  first_seen_at: string;
  times_used: number;
}

export interface LessonTopic {
  id: string;
  emoji: string;
  title: string;
  level: string;
  situation: string;
  task: string;
  phrases: string[];
  grammar: string;
  recommended: boolean;
}

export interface LessonCategory {
  id: string;
  emoji: string;
  title: string;
  description: string;
  topics: LessonTopic[];
}

export interface LessonsResponse {
  level: string;
  categories: LessonCategory[];
}

/** Backend manzili: prod'da VITE_API_URL, dev'da bo'sh (Vite proxy). */
export const API_URL: string = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export function wsUrl(path: string): string {
  if (API_URL) return API_URL.replace(/^http/, "ws") + path;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}

/** Telegram initData; dev'da brauzerda test uchun `dev:<id>`. */
export function getInitData(): string {
  const tg = window.Telegram?.WebApp;
  if (tg?.initData) return tg.initData;
  if (import.meta.env.DEV) return `dev:${import.meta.env.VITE_DEV_TELEGRAM_ID || "100001"}`;
  return "";
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, signal?: AbortSignal, init?: { method: string; body: unknown }): Promise<T> {
  const initData = getInitData();
  if (!initData) throw new ApiError(401, "Ilovani Telegram orqali oching");
  const headers: Record<string, string> = { Authorization: `tma ${initData}` };
  if (init) headers["Content-Type"] = "application/json";
  const res = await fetch(`${API_URL}${path}`, {
    method: init?.method ?? "GET",
    headers,
    body: init ? JSON.stringify(init.body) : undefined,
    signal,
  });
  if (!res.ok) {
    throw new ApiError(res.status, res.status === 401 ? "Avtorizatsiya xatosi" : `Server xatosi (${res.status})`);
  }
  return (await res.json()) as T;
}

export const api = {
  me: (s?: AbortSignal) => request<MeResponse>("/api/me", s),
  progress: (days = 7, s?: AbortSignal) => request<ProgressResponse>(`/api/progress?days=${days}`, s),
  sessions: (limit = 20, s?: AbortSignal) => request<SessionOut[]>(`/api/sessions?limit=${limit}`, s),
  errors: (limit = 50, s?: AbortSignal) => request<ErrorsResponse>(`/api/errors?limit=${limit}`, s),
  vocabulary: (limit = 200, s?: AbortSignal) => request<VocabularyItem[]>(`/api/vocabulary?limit=${limit}`, s),
  saveSettings: (body: Partial<UserSettings>) => request<UserOut>("/api/settings", undefined, { method: "PUT", body }),
  plans: (s?: AbortSignal) => request<PlansResponse>("/api/plans", s),
  lessons: (s?: AbortSignal) => request<LessonsResponse>("/api/lessons", s),
};
