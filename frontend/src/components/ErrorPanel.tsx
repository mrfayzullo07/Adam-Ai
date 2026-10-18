/** Real-time xatolar: oxirgi 3 ta, jiddiylik rangi bilan, yopish mumkin. */
import { BookA, Languages, Mic2, X } from "lucide-react";
import type { LiveError } from "../store/sessionStore";

interface Props {
  errors: LiveError[];
  dismissed: number[];
  onDismiss: (id: number) => void;
  max?: number;
}

const SEVERITY: Record<LiveError["severity"], { bar: string; label: string; chip: string }> = {
  low: { bar: "bg-good", label: "kichik", chip: "bg-good/15 text-good" },
  medium: { bar: "bg-warn", label: "o'rta", chip: "bg-warn/15 text-warn" },
  high: { bar: "bg-bad", label: "jiddiy", chip: "bg-bad/15 text-bad" },
};

const TYPE: Record<LiveError["error_type"], { icon: typeof BookA; label: string }> = {
  grammar: { icon: BookA, label: "Grammatika" },
  pronunciation: { icon: Mic2, label: "Talaffuz" },
  vocabulary: { icon: Languages, label: "Lug'at" },
};

export default function ErrorPanel({ errors, dismissed, onDismiss, max = 3 }: Props) {
  const visible = errors.filter((e) => !dismissed.includes(e.id)).slice(0, max);
  if (visible.length === 0) return null;

  return (
    <div className="flex flex-col gap-2 px-4">
      {visible.map((e) => {
        const sev = SEVERITY[e.severity] ?? SEVERITY.medium;
        const type = TYPE[e.error_type] ?? TYPE.grammar;
        const Icon = type.icon;
        return (
          <div key={e.id} className="card relative flex overflow-hidden animate-fade-up">
            <div className={`w-1.5 shrink-0 ${sev.bar}`} />
            <div className="min-w-0 flex-1 px-3 py-2.5">
              <div className="mb-1 flex items-center gap-2 text-xs text-muted">
                <Icon className="h-3.5 w-3.5" />
                <span>{type.label}</span>
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${sev.chip}`}>{sev.label}</span>
              </div>
              <div className="selectable text-sm leading-snug">
                <span className="text-bad line-through decoration-bad/70">{e.wrong}</span>
                <span className="mx-1.5 text-muted">→</span>
                <span className="font-semibold text-good">{e.correct}</span>
              </div>
              {e.explanation && <p className="mt-1 text-xs italic text-indigo-100/70">{e.explanation}</p>}
            </div>
            <button
              type="button"
              aria-label="Yopish"
              onClick={() => onDismiss(e.id)}
              className="flex w-10 shrink-0 items-start justify-center pt-2.5 text-muted active:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
