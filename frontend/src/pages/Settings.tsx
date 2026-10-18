/** Adam sozlamalari: daraja, tushuntirish tili, tezlik, maqsad, mikrofon. Har o'zgarish darhol saqlanadi. */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, ChevronRight, Target } from "lucide-react";
import OptionList from "../components/OptionList";
import { ErrorState, Spinner } from "../components/Status";
import { haptic, useBackButton } from "../hooks/useTelegram";
import type { UserSettings } from "../lib/api";
import { formatDateTime, limitLabel, PLAN_ICON, remainingLabel } from "../lib/plan";
import {
  EXPLAIN_OPTIONS,
  GOAL_OPTIONS,
  LEVEL_NAMES,
  LEVEL_OPTIONS,
  MIC_OPTIONS,
  PACE_OPTIONS,
} from "../lib/settingsOptions";
import { useUserStore } from "../store/userStore";

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <div>
        <h2 className="text-base font-bold">{title}</h2>
        {hint && <p className="text-xs text-muted">{hint}</p>}
      </div>
      {children}
    </section>
  );
}

export default function Settings() {
  const navigate = useNavigate();
  const { me, error, load, save } = useUserStore();
  const [toast, setToast] = useState<string | null>(null);
  const [showLevels, setShowLevels] = useState(false);

  const goHome = useCallback(() => navigate("/"), [navigate]);
  useBackButton(true, goHome);

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 1800);
    return () => window.clearTimeout(t);
  }, [toast]);

  const update = async (patch: Partial<UserSettings>, message = "Saqlandi") => {
    try {
      await save(patch);
      haptic("success");
      setToast(message);
    } catch {
      haptic("error");
      setToast("Saqlab bo'lmadi, qayta urinib ko'ring");
    }
  };

  if (error && !me) return <div className="pt-10"><ErrorState message={error} onRetry={load} /></div>;
  if (!me) return <Spinner />;
  const u = me.user;

  return (
    <div className="mx-auto flex max-w-md flex-col gap-6 px-4 pb-28 pt-6">
      <h1 className="text-xl font-bold">Sozlamalar</h1>

      <Section title="Tarifim">
        <button type="button" className="card flex items-center gap-3 px-4 py-3 text-left" onClick={() => navigate("/plans")}>
          <span className="text-2xl">{PLAN_ICON[me.plan.plan]}</span>
          <div className="min-w-0 flex-1">
            <div className="font-bold">{me.plan.plan_title}</div>
            <div className="text-xs text-muted">
              {limitLabel(me.plan.limit_seconds, me.plan.window_hours)} · qolgan: {remainingLabel(me.plan)}
            </div>
            {me.plan.plan_expires_at && (
              <div className="text-xs text-muted">Amal qiladi: {formatDateTime(me.plan.plan_expires_at)} gacha</div>
            )}
          </div>
          <span className="flex items-center text-sm text-accent-2">
            {me.plan.plan === "max" ? "Batafsil" : "Yangilash"} <ChevronRight className="h-4 w-4" />
          </span>
        </button>
      </Section>

      <Section title="Mening darajam" hint="Adam savollarni shu darajaga moslab beradi.">
        <div className="card flex items-center justify-between px-4 py-3">
          <div>
            <div className="text-lg font-bold">
              {u.needs_placement ? "Aniqlanmoqda…" : `${u.cefr_level} — ${LEVEL_NAMES[u.cefr_level]}`}
            </div>
            <div className="text-xs text-muted">
              {u.needs_placement ? "Keyingi suhbatda Adam darajangizni aniqlaydi" : `Keyingi darajagacha: ${u.level_progress}%`}
            </div>
          </div>
          <button type="button" className="btn-ghost py-2" onClick={() => setShowLevels((v) => !v)}>
            {showLevels ? "Yopish" : "O'zgartirish"}
          </button>
        </div>
        {showLevels && (
          <>
            <OptionList
              options={LEVEL_OPTIONS}
              value={u.needs_placement ? null : u.cefr_level}
              onChange={(v) => {
                setShowLevels(false);
                void update({ cefr_level: v }, `Daraja: ${v}`);
              }}
            />
            <p className="text-xs text-muted">Darajani qo'lda o'zgartirsangiz, keyingi darajagacha bo'lgan foiz 0% dan boshlanadi.</p>
          </>
        )}
        <button
          type="button"
          className="btn-ghost"
          onClick={() => void update({ needs_placement: true }, "Keyingi suhbatda Adam darajangizni aniqlaydi")}
        >
          <Target className="h-4 w-4" /> Adam darajamni qayta aniqlasin
        </button>
      </Section>

      <Section title="Tushuntirish tili" hint="Adam qaysi tilda ko'proq gapirsin?">
        <OptionList options={EXPLAIN_OPTIONS} value={u.explain_lang} onChange={(v) => void update({ explain_lang: v })} />
      </Section>

      <Section title="Gapirish tezligi">
        <OptionList options={PACE_OPTIONS} value={u.speech_pace} onChange={(v) => void update({ speech_pace: v })} compact />
      </Section>

      <Section title="Maqsadim" hint="Mavzular shunga qarab tanlanadi.">
        <OptionList options={GOAL_OPTIONS} value={u.goal} onChange={(v) => void update({ goal: v })} compact />
      </Section>

      <Section title="Mikrofon">
        <OptionList options={MIC_OPTIONS} value={u.mic_mode} onChange={(v) => void update({ mic_mode: v })} />
      </Section>

      <p className="text-center text-xs text-muted">O'zgarishlar keyingi suhbatdan boshlab ishlaydi.</p>

      {toast && (
        <div className="fixed inset-x-0 bottom-24 z-30 flex justify-center px-4">
          <div className="flex items-center gap-2 rounded-full bg-surface-2 px-4 py-2 text-sm shadow-lg animate-fade-up">
            <Check className="h-4 w-4 text-good" /> {toast}
          </div>
        </div>
      )}
    </div>
  );
}
