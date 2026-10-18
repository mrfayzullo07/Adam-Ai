/** Tariflar: Free / Pro / Max. To'lov bot chatida (karta + chek) amalga oshiriladi. */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, Crown, Users } from "lucide-react";
import { ErrorState, Spinner } from "../components/Status";
import { haptic, openBotPlans, useBackButton } from "../hooks/useTelegram";
import { api, type PlanCatalogItem, type PlansResponse } from "../lib/api";
import { formatDateTime, formatPrice, limitLabel, PLAN_ICON, remainingLabel } from "../lib/plan";

function features(p: PlanCatalogItem): string[] {
  const list = [limitLabel(p.limit_seconds, p.window_hours), "O'zbekcha tushuntirish, xatolarni tuzatish"];
  if (p.code === "free") list.push("Limit yangilanganda botdan xabar");
  if (p.code === "pro") list.push("Kunlik mashq uchun yetarli vaqt");
  if (p.groups) {
    list.push("Adam'ni guruhlarga qo'shish: tarjima va tushuntirish");
    list.push("Kanalga har kuni avtomatik dars");
  }
  return list;
}

export default function Plans() {
  const navigate = useNavigate();
  const [data, setData] = useState<PlansResponse | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const goBack = useCallback(() => navigate(-1), [navigate]);
  useBackButton(true, goBack);

  const load = useCallback(() => {
    const ctrl = new AbortController();
    setFailed(null);
    api
      .plans(ctrl.signal)
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

  if (failed) return <div className="pt-10"><ErrorState message={failed} onRetry={load} /></div>;
  if (!data) return <Spinner />;
  const cur = data.current;

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 px-4 pb-10 pt-6">
      <div>
        <h1 className="text-xl font-bold">Tariflar</h1>
        <p className="text-sm text-muted">
          Hozir: <b className="text-white">{PLAN_ICON[cur.plan]} {cur.plan_title}</b> · qolgan vaqt: {remainingLabel(cur)}
          {cur.plan_expires_at && <> · {formatDateTime(cur.plan_expires_at)} gacha</>}
        </p>
      </div>

      {data.plans.map((p) => {
        const current = p.code === cur.plan;
        const paid = p.price > 0;
        return (
          <div
            key={p.code}
            className={`card flex flex-col gap-3 px-4 py-4 ${current ? "border-accent bg-accent/10" : ""} ${
              p.code === "max" ? "border-warn/50" : ""
            }`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-lg font-bold">
                <span className="text-2xl">{PLAN_ICON[p.code]}</span> {p.title}
                {current && <span className="rounded-full bg-accent/30 px-2 py-0.5 text-[11px] font-medium">joriy</span>}
              </div>
              <div className="text-right">
                <div className="font-bold">{paid ? formatPrice(p.price) : "Bepul"}</div>
                {paid && <div className="text-[11px] text-muted">{data.plan_days} kun</div>}
              </div>
            </div>
            <ul className="flex flex-col gap-1.5 text-sm">
              {features(p).map((f) => (
                <li key={f} className="flex items-start gap-2">
                  {f.startsWith("Adam'ni guruh") ? (
                    <Users className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
                  ) : (
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-good" />
                  )}
                  {f}
                </li>
              ))}
            </ul>
            {paid && (
              <button
                type="button"
                className={p.code === "max" ? "btn-primary" : "btn-ghost"}
                disabled={!data.bot_username}
                onClick={() => {
                  haptic("medium");
                  openBotPlans(data.bot_username);
                }}
              >
                <Crown className="h-4 w-4" /> {current ? "Muddatni uzaytirish" : `${p.title}'ni sotib olish`}
              </button>
            )}
          </div>
        );
      })}

      <div className="card px-4 py-3 text-xs text-muted">
        💳 To'lov qanday bo'ladi: tugmani bosing → bot chatida tarifni tanlang → kartaga o'tkazing → chek skrinshotini
        yuboring. Chekni Adam avtomatik tekshiradi va tarif darhol yoqiladi.
      </div>
    </div>
  );
}
