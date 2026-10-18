/** Progress: haftalik/oylik grafik, umumiy statistika, o'rtacha baholar, xatolar tahlili, so'zlar ro'yxati. */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookA, Clock, Flame, Languages, Mic2, MessageSquare, Type, BookOpen } from "lucide-react";
import LevelBadge from "../components/LevelBadge";
import { ScoreBars } from "../components/SessionStats";
import { ErrorState, Spinner } from "../components/Status";
import { api, type ErrorsResponse, type ProgressResponse, type VocabularyItem } from "../lib/api";
import { haptic, useBackButton } from "../hooks/useTelegram";

type Tab = "stats" | "errors" | "words";
const WEEKDAYS = ["Ya", "Du", "Se", "Ch", "Pa", "Ju", "Sh"];

function WeeklyChart({ days }: { days: ProgressResponse["days"] }) {
  const max = Math.max(1, ...days.map((d) => d.total_sentences));
  const many = days.length > 10;
  return (
    <div className="card px-4 py-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-semibold">Gaplar soni</span>
        <span className="text-xs text-muted">{days.reduce((a, d) => a + d.total_sentences, 0)} jami</span>
      </div>
      <div className="flex h-36 items-end gap-1">
        {days.map((d) => {
          const date = new Date(`${d.date}T00:00:00`);
          const h = (d.total_sentences / max) * 100;
          return (
            <div key={d.date} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
              {!many && d.total_sentences > 0 && <span className="text-[10px] text-muted">{d.total_sentences}</span>}
              <div
                className={`w-full rounded-t-md transition-[height] duration-700 ${
                  d.total_sentences > 0 ? "bg-gradient-to-t from-accent to-accent-2" : "bg-surface-2"
                }`}
                style={{ height: `${Math.max(h, 4)}%` }}
                title={`${d.date}: ${d.total_sentences} gap, ${d.sessions_count} sessiya`}
              />
              {!many && <span className="text-[10px] text-muted">{WEEKDAYS[date.getDay()]}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const ERROR_TYPES = [
  { key: "grammar", label: "Grammatika", icon: BookA, color: "bg-accent" },
  { key: "pronunciation", label: "Talaffuz", icon: Mic2, color: "bg-accent-2" },
  { key: "vocabulary", label: "Lug'at", icon: Languages, color: "bg-warn" },
] as const;

const SEV_COLOR: Record<string, string> = { low: "bg-good", medium: "bg-warn", high: "bg-bad" };

export default function Progress() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("stats");
  const [days, setDays] = useState<7 | 30>(7);
  const [progress, setProgress] = useState<ProgressResponse | null>(null);
  const [errors, setErrors] = useState<ErrorsResponse | null>(null);
  const [vocab, setVocab] = useState<VocabularyItem[] | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const goHome = useCallback(() => navigate("/"), [navigate]);
  useBackButton(true, goHome);

  const load = useCallback(() => {
    const ctrl = new AbortController();
    setFailed(null);
    Promise.all([api.progress(days, ctrl.signal), api.errors(50, ctrl.signal), api.vocabulary(300, ctrl.signal)])
      .then(([p, e, v]) => {
        setProgress(p);
        setErrors(e);
        setVocab(v);
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") setFailed(err.message || "Yuklab bo'lmadi");
      });
    return ctrl;
  }, [days]);

  useEffect(() => {
    const ctrl = load();
    return () => ctrl.abort();
  }, [load]);

  const totalErrors = useMemo(
    () => (errors ? Object.values(errors.by_type).reduce((a, b) => a + b, 0) : 0),
    [errors],
  );

  const tabs: { key: Tab; label: string }[] = [
    { key: "stats", label: "Statistika" },
    { key: "errors", label: "Xatolar" },
    { key: "words", label: "So'zlar" },
  ];

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 px-4 pb-28 pt-6">
      <h1 className="text-xl font-bold">Mening natijalarim</h1>

      <div className="grid grid-cols-3 gap-1 rounded-2xl bg-surface/80 p-1">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => {
              haptic("select");
              setTab(t.key);
            }}
            className={`rounded-xl py-2 text-sm font-medium transition ${
              tab === t.key ? "bg-accent text-white shadow" : "text-muted"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {failed ? (
        <ErrorState message={failed} onRetry={load} />
      ) : !progress || !errors || !vocab ? (
        <Spinner />
      ) : tab === "stats" ? (
        <>
          <LevelBadge level={progress.level.level} nextLevel={progress.level.next_level} progress={progress.level.progress} />

          <div className="flex justify-end gap-1">
            {([7, 30] as const).map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDays(d)}
                className={`rounded-lg px-3 py-1 text-xs font-medium ${days === d ? "bg-surface-2 text-white" : "text-muted"}`}
              >
                {d === 7 ? "Hafta" : "Oy"}
              </button>
            ))}
          </div>
          <WeeklyChart days={progress.days} />

          <div className="grid grid-cols-3 gap-2">
            {[
              { icon: Flame, v: progress.streak_days, l: "kun ketma-ket" },
              { icon: MessageSquare, v: progress.totals.sessions, l: "sessiya" },
              { icon: Clock, v: progress.totals.minutes, l: "daqiqa" },
              { icon: MessageSquare, v: progress.totals.sentences, l: "gap" },
              { icon: Type, v: progress.totals.words, l: "so'z" },
              { icon: BookOpen, v: progress.totals.vocabulary, l: "lug'at" },
            ].map(({ icon: Icon, v, l }) => (
              <div key={l} className="card flex flex-col items-center py-3">
                <Icon className="h-4 w-4 text-muted" />
                <span className="mt-1 text-lg font-bold">{v}</span>
                <span className="text-[10px] uppercase tracking-wide text-muted">{l}</span>
              </div>
            ))}
          </div>

          <div className="card px-4 py-3">
            <div className="mb-2 text-sm font-semibold">O'rtacha baholar</div>
            {Object.values(progress.average_scores).some((v) => v != null) ? (
              <ScoreBars scores={progress.average_scores} />
            ) : (
              <p className="text-sm text-muted">Baholar birinchi sessiyadan keyin paydo bo'ladi.</p>
            )}
          </div>
        </>
      ) : tab === "errors" ? (
        <>
          <div className="card px-4 py-3">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-sm font-semibold">Xatolar tahlili</span>
              <span className="text-xs text-muted">{totalErrors} ta jami</span>
            </div>
            {totalErrors === 0 ? (
              <p className="text-sm text-muted">Hali xato qayd etilmagan. Gaplashishni boshlang!</p>
            ) : (
              <div className="flex flex-col gap-2.5">
                {ERROR_TYPES.map(({ key, label, icon: Icon, color }) => {
                  const count = errors.by_type[key] ?? 0;
                  return (
                    <div key={key}>
                      <div className="mb-1 flex items-center justify-between text-xs">
                        <span className="flex items-center gap-1.5 text-indigo-100/90">
                          <Icon className="h-3.5 w-3.5" /> {label}
                        </span>
                        <span className="font-semibold">{count}</span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-ink/70">
                        <div className={`h-full rounded-full ${color}`} style={{ width: `${(count / totalErrors) * 100}%` }} />
                      </div>
                    </div>
                  );
                })}
                <div className="mt-1 flex gap-3 text-xs text-muted">
                  <span>🟢 kichik: {errors.by_severity.low ?? 0}</span>
                  <span>🟡 o'rta: {errors.by_severity.medium ?? 0}</span>
                  <span>🔴 jiddiy: {errors.by_severity.high ?? 0}</span>
                </div>
              </div>
            )}
          </div>
          <div className="flex flex-col gap-2">
            {errors.items.map((e) => (
              <div key={e.id} className="card flex overflow-hidden">
                <div className={`w-1.5 shrink-0 ${SEV_COLOR[e.severity] ?? "bg-warn"}`} />
                <div className="selectable px-3 py-2.5 text-sm">
                  <span className="text-bad line-through decoration-bad/70">{e.wrong_text}</span>
                  <span className="mx-1.5 text-muted">→</span>
                  <span className="font-semibold text-good">{e.correct_text}</span>
                  {e.explanation && <p className="mt-1 text-xs italic text-indigo-100/70">{e.explanation}</p>}
                </div>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="card px-4 py-3">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-sm font-semibold">Ishlatgan so'zlaringiz</span>
            <span className="text-xs text-muted">{vocab.length} ta</span>
          </div>
          {vocab.length === 0 ? (
            <p className="text-sm text-muted">Adam siz to'g'ri ishlatgan yangi so'zlarni shu yerda yig'ib boradi.</p>
          ) : (
            <div className="selectable flex flex-wrap gap-1.5">
              {vocab.map((v) => (
                <span key={v.word} className="rounded-full bg-accent/20 px-2.5 py-1 text-xs font-medium text-indigo-100">
                  {v.word}
                  {v.times_used > 1 && <span className="ml-1 text-accent-2">×{v.times_used}</span>}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
