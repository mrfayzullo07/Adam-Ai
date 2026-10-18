/** Sozlama variantlari va o'zbekcha nomlari (Onboarding va Sozlamalar sahifasi uchun). */
import type { CefrLevel, ExplainLang, Goal, MicModeSetting, SpeechPace } from "./api";

export interface Option<T extends string> {
  value: T;
  title: string;
  desc: string;
  emoji: string;
}

export const LEVEL_NAMES: Record<CefrLevel, string> = {
  A1: "Boshlang'ich",
  A2: "Elementar",
  B1: "O'rta",
  B2: "O'rtadan yuqori",
  C1: "Yuqori",
  C2: "Mukammal",
};

export const LEVEL_OPTIONS: Option<CefrLevel>[] = [
  { value: "A1", emoji: "🌱", title: "A1 — Boshlang'ich", desc: "Endi boshlayapman, bir nechta so'z bilaman" },
  { value: "A2", emoji: "🌿", title: "A2 — Elementar", desc: "Oddiy gaplarni tushunaman va ayta olaman" },
  { value: "B1", emoji: "🌳", title: "B1 — O'rta", desc: "Kundalik mavzularda gaplasha olaman" },
  { value: "B2", emoji: "🚀", title: "B2 — O'rtadan yuqori", desc: "Bemalol gaplashaman, ba'zan xato qilaman" },
  { value: "C1", emoji: "⭐", title: "C1 — Yuqori", desc: "Murakkab mavzularda erkin gaplashaman" },
  { value: "C2", emoji: "🏆", title: "C2 — Mukammal", desc: "Ona tilidek bilaman" },
];

/** Onboarding'dagi sodda savol: "Ingliz tilini qanchalik bilasiz?" */
export type SelfLevel = "zero" | "little" | "middle" | "good" | "unknown";

export const SELF_LEVEL_OPTIONS: (Option<SelfLevel> & { level: CefrLevel; placement?: boolean })[] = [
  { value: "zero", level: "A1", emoji: "🌱", title: "Umuman bilmayman", desc: "Noldan boshlayman" },
  { value: "little", level: "A2", emoji: "🌿", title: "Bir oz bilaman", desc: "Salomlashish, oddiy gaplar" },
  { value: "middle", level: "B1", emoji: "🌳", title: "O'rtacha bilaman", desc: "Gaplasha olaman, lekin xato qilaman" },
  { value: "good", level: "B2", emoji: "🚀", title: "Yaxshi bilaman", desc: "Bemalol gaplashaman" },
  {
    value: "unknown",
    level: "A1",
    placement: true,
    emoji: "🎯",
    title: "Bilmayman — Adam aniqlasin",
    desc: "Adam 5-6 ta savol berib darajangizni aniqlaydi",
  },
];

export const GOAL_OPTIONS: Option<Goal>[] = [
  { value: "general", emoji: "💬", title: "Kundalik suhbat", desc: "Tanishish, oila, ish, xarid" },
  { value: "travel", emoji: "✈️", title: "Sayohat", desc: "Aeroport, mehmonxona, taksi, restoran" },
  { value: "work", emoji: "💼", title: "Ish uchun", desc: "Ish suhbati, hamkasblar, telefon" },
  { value: "ielts", emoji: "🎓", title: "IELTS / o'qish", desc: "Speaking savollari, chet elda o'qish" },
];

export const EXPLAIN_OPTIONS: Option<ExplainLang>[] = [
  { value: "uz", emoji: "🇺🇿", title: "Ko'proq o'zbekcha", desc: "Har bir inglizcha gap tarjima qilinadi" },
  { value: "mix", emoji: "🔀", title: "Aralash", desc: "Yarmi o'zbekcha, yarmi inglizcha" },
  { value: "en", emoji: "🇬🇧", title: "Ko'proq inglizcha", desc: "O'zbekcha faqat kerak bo'lganda" },
];

export const PACE_OPTIONS: Option<SpeechPace>[] = [
  { value: "slow", emoji: "🐢", title: "Sekin", desc: "Aniq va sekin gapiradi" },
  { value: "normal", emoji: "🗣️", title: "Oddiy", desc: "Tabiiy tezlikda" },
];

export const MIC_OPTIONS: Option<MicModeSetting>[] = [
  { value: "free", emoji: "🎙️", title: "Erkin suhbat", desc: "Bir marta bosing va bemalol gapiring" },
  { value: "ptt", emoji: "👆", title: "Bosib gapirish", desc: "Tugmani bosib turib gapiring" },
];

export function recommendedExplain(level: CefrLevel): ExplainLang {
  if (level === "A1" || level === "A2") return "uz";
  if (level === "B1") return "mix";
  return "en";
}

export function recommendedPace(level: CefrLevel): SpeechPace {
  return level === "A1" || level === "A2" ? "slow" : "normal";
}
