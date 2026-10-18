/** Bosh sahifa: salomlashish, daraja, streak, bugungi statistika, oxirgi sessiya xulosasi. */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CalendarDays, ChevronRight, Flame, Lightbulb, MessageSquare, Type } from "lucide-react";
import AdamAvatar from "../components/AdamAvatar";
import LevelBadge from "../components/LevelBadge";
import { ScoreBars, formatDuration } from "../components/SessionStats";
import { ErrorState, Spinner } from "../components/Status";
import { api, type MeResponse } from "../lib/api";
import { haptic, useBackButton, useTelegram } from "../hooks/useTelegram";

const TIPS = [
  "Har kuni 10 daqiqa gapirish — haftada bir marta 1 soatdan samaraliroq.",
  "Xato qilishdan qo'rqmang: Adam har bir xatoni tushuntirib beradi.",
  "Javobni to'liq gap bilan bering: “Yes” emas, “Yes, I like it”.",
  "Quloqchin bilan gaplashsangiz, Adam sizni aniqroq eshitadi.",
  "Yangi so'zni darhol o'z gapingizda ishlating — shunda u esda qoladi.",
];

function greeting(): string {
  const h = new Date().getHours();
  if (h < 5) return "Xayrli tun";
  if (h < 12) return "Xayrli tong";
  if (h < 18) return "Xayrli kun";
  return "Xayrli kech";
}

function formatDate(iso: string): string {
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  const months = ["yan", "fev", "mar", "apr", "may", "iyn", "iyl", "avg", "sen", "okt", "noy", "dek"];
  return `${d.getDate()}-${months[d.getMonth()]}, ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function Home() {
  const navigate = useNavigate();
  const { user } = useTelegram();
  const [data, setData] = useState<MeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tip] = useState(() => TIPS[Math.floor(Math.random() * TIPS.length)]);

  useBackButton(false, () => undefined);

  const load = useCallback(() => {
    const ctrl = new AbortController();
    setError(null);
    api
      .me(ctrl.signal)
      .then(setData)
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(e.message || "Ma'lumotlarni yuklab bo'lmadi");
      });
    return ctrl;
  }, []);

  useEffect(() => {
    const ctrl = load();
    return () => ctrl.abort();
  }, [load]);

  const name = data?.user.first_name || user?.first_name || "do'stim";
  const last = data?.last_session;

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 px-4 pb-28 pt-6">
      <header className="flex items-center gap-3">
        <AdamAvatar size={64} speaking={false} listening={false} getLevel={() => 0} />
        <div>
          <p className="text-sm text-muted">{greeting()},</p>
          <h1 className="text-xl font-bold">{name} 👋</h1>
        </div>
      </header>

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : !data ? (
        <Spinner />
      ) : (
        <>
          <LevelBadge level={data.level.level} nextLevel={data.level.next_level} progress={data.level.progress} />

          <div className="grid grid-cols-3 gap-2">
            <div className="card flex flex-col items-center py-3">
              <Flame className={`h-5 w-5 ${data.streak_days > 0 ? "text-orange-400" : "text-muted"}`} />
              <span className="mt-1 text-lg font-bold">{data.streak_days}</span>
              <span className="text-[10px] uppercase tracking-wide text-muted">kun ketma-ket</span>
            </div>
            <div className="card flex flex-col items-center py-3">
              <MessageSquare className="h-5 w-5 text-accent-2" />
              <span className="mt-1 text-lg font-bold">{data.today?.total_sentences ?? 0}</span>
              <span className="text-[10px] uppercase tracking-wide text-muted">bugun gap</span>
            </div>
            <div className="card flex flex-col items-center py-3">
              <Type className="h-5 w-5 text-accent" />
              <span className="mt-1 text-lg font-bold">{data.today?.total_words ?? 0}</span>
              <span className="text-[10px] uppercase tracking-wide text-muted">bugun so'z</span>
            </div>
          </div>

          <button
            type="button"
            className="btn-primary py-5 text-lg"
            onClick={() => {
              haptic("medium");
              navigate("/session");
            }}
          >
            🎤 Adam bilan gapirish
          </button>
          <button
            type="button"
            className="btn-ghost"
            onClick={() => {
              haptic("light");
              navigate("/lessons");
            }}
          >
            📚 Vaziyatli darslar: maktab, ish, sayohat…
          </button>
          {data.today?.sessions_count ? (
            <p className="-mt-2 text-center text-xs text-muted">Bugun {data.today.sessions_count} ta sessiya o'tkazdingiz 💪</p>
          ) : (
            <p className="-mt-2 text-center text-xs text-muted">Bugungi birinchi sessiyangizni boshlang!</p>
          )}

          {last && (
            <button type="button" className="card px-4 py-3 text-left" onClick={() => navigate("/progress")}>
              <div className="mb-2 flex items-center justify-between">
                <span className="flex items-center gap-2 text-sm font-semibold">
                  <CalendarDays className="h-4 w-4 text-accent-2" /> Oxirgi sessiya
                </span>
                <span className="flex items-center text-xs text-muted">
                  {formatDate(last.started_at)} <ChevronRight className="h-4 w-4" />
                </span>
              </div>
              <div className="mb-3 flex gap-4 text-sm text-indigo-100/90">
                <span>⏱ {formatDuration(last.duration_seconds ?? 0)}</span>
                <span>💬 {last.sentences_spoken} gap</span>
                <span>📝 {last.words_spoken} so'z</span>
              </div>
              {last.fluency_score != null && (
                <ScoreBars
                  scores={{
                    fluency: last.fluency_score,
                    grammar: last.grammar_score,
                    pronunciation: last.pronunciation_score,
                    comprehension: last.comprehension_score,
                  }}
                />
              )}
            </button>
          )}

          <div className="card flex gap-3 px-4 py-3">
            <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-warn" />
            <p className="text-sm text-indigo-100/90">{tip}</p>
          </div>
        </>
      )}
    </div>
  );
}
