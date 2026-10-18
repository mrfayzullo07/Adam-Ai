/** Katta, bosish oson variant kartalari (bitta tanlov). */
import { Check } from "lucide-react";
import { haptic } from "../hooks/useTelegram";
import type { Option } from "../lib/settingsOptions";

interface Props<T extends string> {
  options: Option<T>[];
  value: T | null;
  onChange: (v: T) => void;
  compact?: boolean;
  badge?: Partial<Record<T, string>>;
}

export default function OptionList<T extends string>({ options, value, onChange, compact, badge }: Props<T>) {
  return (
    <div className={compact ? "grid grid-cols-2 gap-2" : "grid gap-2"}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => {
              haptic("select");
              onChange(o.value);
            }}
            className={`card flex items-center gap-3 px-4 text-left transition active:scale-[0.99] ${
              compact ? "py-3" : "py-3.5"
            } ${active ? "border-accent bg-accent/15" : ""}`}
          >
            <span className="text-2xl leading-none">{o.emoji}</span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2 font-semibold">
                {o.title}
                {badge?.[o.value] && (
                  <span className="rounded-full bg-good/20 px-2 py-0.5 text-[10px] font-semibold text-good">
                    {badge[o.value]}
                  </span>
                )}
              </span>
              {!compact && <span className="block text-xs text-muted">{o.desc}</span>}
            </span>
            {active && <Check className="h-5 w-5 shrink-0 text-accent-2" />}
          </button>
        );
      })}
    </div>
  );
}
