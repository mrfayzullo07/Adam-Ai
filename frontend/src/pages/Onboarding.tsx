/** Birinchi kirish: 3 ta oddiy savol (daraja, maqsad, tushuntirish tili) -> Adam shunga moslashadi. */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Loader2 } from "lucide-react";
import AdamAvatar from "../components/AdamAvatar";
import OptionList from "../components/OptionList";
import { haptic } from "../hooks/useTelegram";
import type { ExplainLang, Goal } from "../lib/api";
import {
  EXPLAIN_OPTIONS,
  GOAL_OPTIONS,
  SELF_LEVEL_OPTIONS,
  recommendedExplain,
  recommendedPace,
  type SelfLevel,
} from "../lib/settingsOptions";
import { useUserStore } from "../store/userStore";

const STEPS = [
  { title: "Ingliz tilini qanchalik bilasiz?", hint: "To'g'ri javob yo'q — keyin sozlamalardan o'zgartirish mumkin." },
  { title: "Nima uchun o'rganyapsiz?", hint: "Adam mavzularni shunga qarab tanlaydi." },
  { title: "Adam qaysi tilda tushuntirsin?", hint: "Boshlovchilar uchun «Ko'proq o'zbekcha» tavsiya etiladi." },
];

export default function Onboarding() {
  const navigate = useNavigate();
  const me = useUserStore((s) => s.me);
  const save = useUserStore((s) => s.save);
  const [step, setStep] = useState(0);
  const [self, setSelf] = useState<SelfLevel | null>(null);
  const [goal, setGoal] = useState<Goal | null>(null);
  const [explain, setExplain] = useState<ExplainLang | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selfOpt = SELF_LEVEL_OPTIONS.find((o) => o.value === self);
  const recommended = selfOpt ? recommendedExplain(selfOpt.level) : "uz";

  const next = (s: number) => {
    haptic("light");
    setStep(s);
  };

  const finish = async (explainLang: ExplainLang) => {
    if (!selfOpt || !goal) return;
    setSaving(true);
    setError(null);
    try {
      await save({
        cefr_level: selfOpt.level,
        needs_placement: Boolean(selfOpt.placement),
        goal,
        explain_lang: explainLang,
        speech_pace: recommendedPace(selfOpt.level),
        onboarded: true,
      });
      haptic("success");
      navigate("/session", { replace: true });
    } catch (e) {
      setError((e as Error).message || "Saqlab bo'lmadi");
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-full max-w-md flex-col gap-5 px-4 pb-8 pt-5">
      <div className="flex items-center gap-3">
        {step > 0 ? (
          <button type="button" className="rounded-xl p-2 text-muted active:text-white" onClick={() => next(step - 1)} aria-label="Orqaga">
            <ArrowLeft className="h-5 w-5" />
          </button>
        ) : (
          <span className="w-9" />
        )}
        <div className="flex flex-1 gap-1.5">
          {STEPS.map((_, i) => (
            <div key={i} className={`h-1.5 flex-1 rounded-full ${i <= step ? "bg-accent" : "bg-surface-2"}`} />
          ))}
        </div>
        <span className="w-9 text-right text-xs text-muted">{step + 1}/3</span>
      </div>

      {step === 0 && (
        <div className="flex flex-col items-center gap-2 text-center">
          <AdamAvatar size={96} speaking={false} listening={false} getLevel={() => 0} />
          <h1 className="text-xl font-bold">Salom{me?.user.first_name ? `, ${me.user.first_name}` : ""}! Men Adam 👋</h1>
          <p className="text-sm text-muted">Sizga mos darslar uchun 3 ta savol beraman.</p>
        </div>
      )}

      <div>
        <h2 className="text-lg font-bold">{STEPS[step].title}</h2>
        <p className="mt-1 text-sm text-muted">{STEPS[step].hint}</p>
      </div>

      {step === 0 && (
        <OptionList
          options={SELF_LEVEL_OPTIONS}
          value={self}
          onChange={(v) => {
            setSelf(v);
            window.setTimeout(() => next(1), 150);
          }}
        />
      )}
      {step === 1 && (
        <OptionList
          options={GOAL_OPTIONS}
          value={goal}
          onChange={(v) => {
            setGoal(v);
            window.setTimeout(() => next(2), 150);
          }}
        />
      )}
      {step === 2 && (
        <>
          <OptionList
            options={EXPLAIN_OPTIONS}
            value={explain ?? recommended}
            onChange={setExplain}
            badge={{ [recommended]: "tavsiya" } as Partial<Record<ExplainLang, string>>}
          />
          {error && <p className="text-center text-sm text-bad">{error}</p>}
          <button type="button" className="btn-primary mt-2" disabled={saving} onClick={() => finish(explain ?? recommended)}>
            {saving ? <Loader2 className="h-5 w-5 animate-spin" /> : "🎤 Adam bilan boshlash"}
          </button>
          {selfOpt?.placement && (
            <p className="text-center text-xs text-muted">Adam avval bir nechta oddiy savol berib darajangizni aniqlaydi.</p>
          )}
        </>
      )}
    </div>
  );
}
