/** Tarif va vaqt limiti uchun formatlash yordamchilari. */
import type { PlanCode, PlanInfo } from "./api";

export const PLAN_ICON: Record<PlanCode, string> = { free: "🆓", pro: "💎", max: "👑" };

export function formatDurationUz(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h) return m ? `${h} soat ${m} daqiqa` : `${h} soat`;
  if (m) return sec ? `${m} daqiqa ${sec} soniya` : `${m} daqiqa`;
  return `${sec} soniya`;
}

export function formatPrice(amount: number): string {
  return `${amount.toLocaleString("ru-RU").replace(/\u00a0/g, " ")} so'm`;
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function limitLabel(limit: number | null, windowHours: number | null): string {
  if (limit == null) return "Cheksiz gaplashish";
  return `Har ${windowHours} soatda ${formatDurationUz(limit)}`;
}

/** "Qolgan vaqt: 1 daqiqa 20 soniya" yoki "Cheksiz". */
export function remainingLabel(p: PlanInfo): string {
  if (p.remaining_seconds == null) return "Cheksiz ♾";
  return formatDurationUz(p.remaining_seconds);
}

export function isExhausted(p: PlanInfo | null | undefined): boolean {
  return Boolean(p && p.remaining_seconds != null && p.remaining_seconds <= 0);
}
