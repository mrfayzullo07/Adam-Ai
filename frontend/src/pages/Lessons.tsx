/** Vaziyatli darslar: kategoriya -> mavzu -> Adam bilan rol o'ynash (sessiyaga topic bilan o'tadi). */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, ChevronDown, Mic, Sparkles } from "lucide-react";
import { ErrorState, Spinner } from "../components/Status";
import { haptic } from "../hooks/useTelegram";
import { api, type LessonsResponse, type LessonTopic } from "../lib/api";

const ALL = "all";

export default function Lessons() {
  const navigate = useNavigate();
  const [data, setData] = useState<LessonsResponse | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [category, setCategory] = useState<string>(ALL);
  const [onlyMine, setOnlyMine] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);

  const load = useCallback(() => {
    const ctrl = new AbortController();
    setFailed(null);
    api
      .lessons(ctrl.signal)
      .then(setData)
      .catch((e: Error) => {
        if (e.name !== "AbortError") setFailed(e.message);
      });
    return ctrl;
  }, []);

  useEffect(() => {
    const ctrl = load();
    return () => ctrl.abort();
  }, [load]);

  const groups = useMemo(() => {
    if (!data) return [];
    return data.categories
      .filter((c) => category === ALL || c.id === category)
      .map((c) => ({ ...c, topics: c.topics.filter((t) => !onlyMine || t.recommended) }))
      .filter((c) => c.topics.length > 0);
  }, [data, category, onlyMine]);

  const startLesson = (topic: LessonTopic) => {
    haptic("medium");
    navigate("/session", { state: { topic } });
  };

  if (failed) return <div className="pt-10"><ErrorState message={failed} onRetry={load} /></div>;
  if (!data) return <Spinner />;

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 px-4 pb-28 pt-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-bold">
          <BookOpen className="h-5 w-5 text-accent-2" /> Darslar
        </h1>
        <p className="text-sm text-muted">
          Vaziyatni tanlang — Adam uni tasavvur qildirib, kerakli iboralar, grammatika va talaffuzni o'rgatadi,
          keyin siz bilan rol o'ynaydi.
        </p>
      </div>

      <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1">
        {[{ id: ALL, emoji: "✨", title: "Hammasi" }, ...data.categories].map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => {
              haptic("select");
              setCategory(c.id);
            }}
            className={`shrink-0 rounded-full border px-3 py-1.5 text-sm transition ${
              category === c.id ? "border-accent bg-accent/25 text-white" : "border-line bg-surface-2/60 text-muted"
            }`}
          >
            {c.emoji} {c.title}
          </button>
        ))}
      </div>

      <label className="flex items-center justify-between gap-3 text-sm">
        <span className="text-muted">
          Faqat mening darajamga mos (<b className="text-white">{data.level}</b>)
        </span>
        <input
          type="checkbox"
          className="h-5 w-5 accent-[rgb(129,140,248)]"
          checked={onlyMine}
          onChange={(e) => setOnlyMine(e.target.checked)}
        />
      </label>

      {groups.length === 0 && (
        <div className="card px-4 py-6 text-center text-sm text-muted">
          Bu bo'limda darajangizga mos dars yo'q. «Faqat mening darajamga mos» belgisini olib tashlang.
        </div>
      )}

      {groups.map((c) => (
        <section key={c.id} className="flex flex-col gap-2">
          <div>
            <h2 className="text-base font-semibold">
              {c.emoji} {c.title}
            </h2>
            <p className="text-xs text-muted">{c.description}</p>
          </div>
          {c.topics.map((t) => {
            const open = openId === t.id;
            return (
              <div key={t.id} className="card overflow-hidden">
                <button
                  type="button"
                  className="flex w-full items-center gap-3 px-4 py-3 text-left"
                  onClick={() => {
                    haptic("light");
                    setOpenId(open ? null : t.id);
                  }}
                >
                  <span className="text-2xl">{t.emoji}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium">{t.title}</span>
                    <span className="block truncate text-xs text-muted">{t.task}</span>
                  </span>
                  <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[10px] font-bold text-indigo-100">{t.level}</span>
                  <ChevronDown className={`h-4 w-4 shrink-0 text-muted transition ${open ? "rotate-180" : ""}`} />
                </button>
                {open && (
                  <div className="flex flex-col gap-3 border-t border-line/60 px-4 py-3 text-sm">
                    <p>
                      <span className="text-muted">Tasavvur qiling: </span>
                      {t.situation}
                    </p>
                    <p>
                      <span className="text-muted">Vazifa: </span>
                      {t.task}
                    </p>
                    <div>
                      <div className="mb-1 text-muted">Kalit iboralar:</div>
                      <div className="flex flex-wrap gap-1.5">
                        {t.phrases.map((p) => (
                          <span key={p} className="rounded-full bg-accent/20 px-2.5 py-1 text-xs text-indigo-100">
                            {p}
                          </span>
                        ))}
                      </div>
                    </div>
                    <p className="flex items-start gap-1.5">
                      <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent-2" />
                      <span>
                        <span className="text-muted">Grammatika: </span>
                        {t.grammar}
                      </span>
                    </p>
                    <button type="button" className="btn-primary" onClick={() => startLesson(t)}>
                      <Mic className="h-5 w-5" /> Adam bilan mashq qilish
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </section>
      ))}
    </div>
  );
}
