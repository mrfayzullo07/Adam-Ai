/** Vaqt limiti tugaganda: sabab, yangilanish vaqti va Pro'ga o'tish tugmasi. */
import { useNavigate } from "react-router-dom";
import { Clock, Crown } from "lucide-react";
import type { PlanInfo } from "../lib/api";
import { formatDateTime } from "../lib/plan";

export default function LimitCard({ plan, message }: { plan: PlanInfo; message?: string }) {
  const navigate = useNavigate();
  const isFree = plan.plan === "free";
  return (
    <div className="card flex flex-col gap-3 border-warn/60 px-4 py-4">
      <div className="flex items-start gap-3">
        <Clock className="mt-0.5 h-6 w-6 shrink-0 text-warn" />
        <div>
          <div className="font-semibold">{isFree ? "Bepul vaqtingiz tugadi" : "Tarif limitingiz tugadi"}</div>
          <p className="text-sm text-muted">
            {message ??
              (isFree
                ? "Adam bilan davom etish uchun Pro'ga o'ting yoki limit yangilanishini kuting."
                : "Limit yangilanishini kuting yoki cheksiz Max tarifiga o'ting.")}
          </p>
          {plan.resets_at && (
            <p className="mt-1 text-sm">
              ⏰ Limit yangilanadi: <b>{formatDateTime(plan.resets_at)}</b>
              {isFree && <span className="text-muted"> — botga xabar yuboraman</span>}
            </p>
          )}
        </div>
      </div>
      <button type="button" className="btn-primary" onClick={() => navigate("/plans")}>
        <Crown className="h-5 w-5" /> {isFree ? "Pro'ga o'tish" : "Max'ga o'tish"}
      </button>
    </div>
  );
}
