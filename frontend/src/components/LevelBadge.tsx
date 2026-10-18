/** CEFR daraja nishoni: "A1 → A2: 42%" + progress bar (sessiya davomida prognoz bilan). */
import { TrendingUp } from "lucide-react";

interface Props {
  level: string;
  nextLevel: string | null;
  progress: number;
  /** Sessiya boshidagi progress — prognoz farqini ko'rsatish uchun */
  baseProgress?: number;
  leveledUp?: boolean;
  compact?: boolean;
}

export default function LevelBadge({ level, nextLevel, progress, baseProgress, leveledUp, compact }: Props) {
  const pct = Math.max(0, Math.min(100, Math.round(progress)));
  const delta = baseProgress !== undefined && !leveledUp ? pct - baseProgress : 0;

  return (
    <div className={`card ${compact ? "px-3 py-2" : "px-4 py-3"}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="rounded-lg bg-gradient-to-br from-accent to-accent-2 px-2 py-0.5 text-sm font-black text-white">
            {level}
          </span>
          {nextLevel ? (
            <span className="text-sm text-muted">
              → <span className="font-semibold text-white">{nextLevel}</span>: {pct}%
            </span>
          ) : (
            <span className="text-sm text-muted">eng yuqori daraja 🏆</span>
          )}
        </div>
        {leveledUp ? (
          <span className="flex items-center gap-1 text-xs font-semibold text-good">
            <TrendingUp className="h-3.5 w-3.5" /> Yangi daraja!
          </span>
        ) : delta !== 0 ? (
          <span className={`text-xs font-semibold ${delta > 0 ? "text-good" : "text-bad"}`}>
            {delta > 0 ? "+" : ""}
            {delta}%
          </span>
        ) : null}
      </div>
      {nextLevel && (
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-ink/70">
          <div
            className="h-full rounded-full bg-gradient-to-r from-accent to-accent-2 transition-[width] duration-700"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
    </div>
  );
}
