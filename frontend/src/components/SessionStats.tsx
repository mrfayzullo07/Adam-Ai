/** Sessiya statistikasi: taymer (qolgan vaqt), gaplar, so'zlar, xatolar va skorlar. */
import { useEffect, useState } from "react";
import { Clock, MessageSquare, AlertTriangle, Type } from "lucide-react";
import type { Scores } from "../store/sessionStore";

interface Props {
  startedAt: number | null;
  timeoutSeconds: number;
  sentences: number;
  words: number;
  errors: number;
  scores: Scores | null;
  showScores?: boolean;
}

export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export const SCORE_LABELS: Record<keyof Scores, string> = {
  fluency: "Ravonlik",
  grammar: "Grammatika",
  pronunciation: "Talaffuz",
  comprehension: "Tushunish",
};

export function ScoreBars({ scores }: { scores: Scores }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-2">
      {(Object.keys(SCORE_LABELS) as (keyof Scores)[]).map((key) => {
        const v = scores[key];
        return (
          <div key={key}>
            <div className="mb-1 flex justify-between text-xs">
              <span className="text-muted">{SCORE_LABELS[key]}</span>
              <span className="font-semibold">{v != null ? `${Number(v).toFixed(v % 1 ? 1 : 0)}/5` : "—"}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-ink/70">
              <div
                className="h-full rounded-full bg-gradient-to-r from-accent to-accent-2 transition-[width] duration-500"
                style={{ width: `${v ? (v / 5) * 100 : 0}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function SessionStats({ startedAt, timeoutSeconds, sentences, words, errors, scores, showScores }: Props) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!startedAt) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [startedAt]);

  const elapsed = startedAt ? (now - startedAt) / 1000 : 0;
  const remaining = timeoutSeconds - elapsed;

  const items = [
    { icon: Clock, value: formatDuration(remaining), label: "qoldi", warn: startedAt !== null && remaining < 60 },
    { icon: MessageSquare, value: sentences, label: "gap" },
    { icon: Type, value: words, label: "so'z" },
    { icon: AlertTriangle, value: errors, label: "xato" },
  ];

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-4 gap-2">
        {items.map(({ icon: Icon, value, label, warn }) => (
          <div key={label} className={`card flex flex-col items-center py-2 ${warn ? "border-warn/60" : ""}`}>
            <div className={`flex items-center gap-1 text-sm font-bold ${warn ? "text-warn" : ""}`}>
              <Icon className="h-3.5 w-3.5 opacity-70" />
              {value}
            </div>
            <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
          </div>
        ))}
      </div>
      {showScores && scores && (
        <div className="card px-4 py-3">
          <ScoreBars scores={scores} />
        </div>
      )}
    </div>
  );
}
