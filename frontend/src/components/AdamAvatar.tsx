/** Adam avatari: gapirganda ovoz balandligiga qarab "nafas oladi", tinglaganda yengil suzadi. */
import { useEffect, useRef } from "react";

interface Props {
  speaking: boolean;
  listening: boolean;
  getLevel: () => number;
  size?: number;
}

export default function AdamAvatar({ speaking, listening, getLevel, size = 132 }: Props) {
  const glowRef = useRef<HTMLDivElement>(null);
  const coreRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let raf = 0;
    let smooth = 0;
    const tick = () => {
      const lvl = speaking ? getLevel() : 0;
      smooth += (lvl - smooth) * 0.25;
      if (glowRef.current) {
        glowRef.current.style.transform = `scale(${1 + smooth * 0.45})`;
        glowRef.current.style.opacity = String(0.35 + smooth * 0.6);
      }
      if (coreRef.current) coreRef.current.style.transform = `scale(${1 + smooth * 0.08})`;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [speaking, getLevel]);

  return (
    <div className="relative flex items-center justify-center" style={{ width: size, height: size }} aria-label="Adam">
      <div
        ref={glowRef}
        className="absolute inset-0 rounded-full blur-2xl transition-opacity"
        style={{ background: "radial-gradient(circle, #7c5cff 0%, #22d3ee 60%, transparent 72%)", opacity: 0.35 }}
      />
      {listening && <div className="absolute inset-3 rounded-full border-2 border-accent-2/50 animate-ring" />}
      <div
        ref={coreRef}
        className={`relative flex items-center justify-center rounded-full shadow-2xl shadow-accent/40 ${
          !speaking ? "animate-float" : ""
        }`}
        style={{
          width: size * 0.72,
          height: size * 0.72,
          background: "conic-gradient(from 210deg, #7c5cff, #5b8cff, #22d3ee, #7c5cff)",
        }}
      >
        <div className="flex h-[86%] w-[86%] items-center justify-center rounded-full bg-ink/85">
          <span className="bg-gradient-to-br from-white to-accent-2 bg-clip-text text-4xl font-black text-transparent">A</span>
        </div>
      </div>
    </div>
  );
}
