/** Oxirgi 4-6 gap: foydalanuvchi o'ngda, Adam chapda; o'zbekcha qism italik, inglizcha qalin. */
import { useEffect, useMemo, useRef } from "react";
import { segmentByLanguage } from "../lib/lang";
import type { TranscriptLine } from "../store/sessionStore";

interface Props {
  lines: TranscriptLine[];
  max?: number;
}

function AdamText({ text }: { text: string }) {
  const segments = useMemo(() => segmentByLanguage(text), [text]);
  return (
    <>
      {segments.map((seg, i) =>
        seg.uz ? (
          <span key={i} className="italic text-indigo-100/80">
            {seg.text}
          </span>
        ) : (
          <span key={i} className="font-semibold text-white">
            {seg.text}
          </span>
        ),
      )}
    </>
  );
}

export default function Transcript({ lines, max = 6 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const visible = lines.slice(-max);
  const lastText = visible[visible.length - 1]?.text;

  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: "smooth" });
  }, [visible.length, lastText]);

  if (visible.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center px-6 text-center text-sm text-muted">
        Adam hozir salomlashadi. Javob berish uchun mikrofonni yoqing 🎧
      </div>
    );
  }

  return (
    <div ref={ref} className="no-scrollbar selectable flex flex-1 flex-col gap-2.5 overflow-y-auto px-4 py-2">
      {visible.map((line) =>
        line.role === "adam" ? (
          <div key={line.id} className="max-w-[88%] self-start animate-fade-up">
            <div className="mb-0.5 text-[11px] font-medium uppercase tracking-wide text-accent-2/80">Adam</div>
            <div
              className={`rounded-2xl rounded-tl-md bg-surface-2/80 px-3.5 py-2.5 text-[15px] leading-relaxed ${
                line.final ? "" : "opacity-90"
              }`}
            >
              <AdamText text={line.text} />
            </div>
          </div>
        ) : (
          <div key={line.id} className="max-w-[85%] self-end animate-fade-up">
            <div
              className={`rounded-2xl rounded-tr-md bg-accent/85 px-3.5 py-2.5 text-[15px] leading-relaxed text-white ${
                line.final ? "" : "opacity-75"
              }`}
            >
              {line.text}
            </div>
          </div>
        ),
      )}
    </div>
  );
}
