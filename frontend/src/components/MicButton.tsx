/**
 * Katta mikrofon tugmasi.
 *  - free rejim: bosish = yoqish/o'chirish
 *  - ptt rejim: bosib turish = gapirish, qo'yib yuborish = yuborish
 * Holatga qarab rang va pulsatsiya; mikrofon balandligi real vaqtda ko'rsatiladi.
 */
import { useEffect, useRef } from "react";
import { Loader2, Mic, MicOff, Volume2 } from "lucide-react";
import type { MicMode } from "../store/sessionStore";

export type MicVisualState = "connecting" | "idle" | "listening" | "adam" | "disabled";

interface Props {
  state: MicVisualState;
  mode: MicMode;
  getLevel: () => number;
  onToggle: () => void;
  onPressStart: () => void;
  onPressEnd: () => void;
}

const STYLES: Record<MicVisualState, string> = {
  connecting: "bg-surface-2 text-muted",
  idle: "text-white shadow-accent/40",
  listening: "bg-rose-500 text-white shadow-rose-500/40",
  adam: "bg-cyan-500/90 text-white shadow-cyan-400/40",
  disabled: "bg-surface-2 text-muted opacity-60",
};

export default function MicButton({ state, mode, getLevel, onToggle, onPressStart, onPressEnd }: Props) {
  const meterRef = useRef<HTMLDivElement>(null);
  const pressed = useRef(false);

  useEffect(() => {
    let raf = 0;
    let smooth = 0;
    const tick = () => {
      const lvl = state === "listening" ? getLevel() : 0;
      smooth += (lvl - smooth) * 0.3;
      if (meterRef.current) meterRef.current.style.transform = `scale(${1 + smooth * 0.5})`;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [state, getLevel]);

  const disabled = state === "connecting" || state === "disabled";

  const pressStart = (e: React.PointerEvent<HTMLButtonElement>) => {
    if (mode !== "ptt" || disabled) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    pressed.current = true;
    onPressStart();
  };
  const pressEnd = () => {
    if (mode !== "ptt" || !pressed.current) return;
    pressed.current = false;
    onPressEnd();
  };

  const label =
    state === "connecting"
      ? "Ulanmoqda…"
      : state === "listening"
        ? mode === "ptt"
          ? "Gapiring… (qo'yib yuboring)"
          : "Tinglayapman — to'xtatish uchun bosing"
        : state === "adam"
          ? mode === "ptt"
            ? "Adam gapiryapti — bosib turib bo'lishingiz mumkin"
            : "Adam gapiryapti — gapirsangiz to'xtaydi"
          : mode === "ptt"
            ? "Bosib turib gapiring"
            : "Gapirish uchun bosing";

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="relative flex h-32 w-32 items-center justify-center">
        {state === "listening" && (
          <>
            <span className="absolute inset-3 rounded-full bg-rose-500/40 animate-ring" />
            <span className="absolute inset-3 rounded-full bg-rose-500/30 animate-ring [animation-delay:0.6s]" />
          </>
        )}
        {state === "idle" && <span className="absolute inset-3 rounded-full bg-accent/30 animate-ring" />}
        <div ref={meterRef} className="absolute inset-4 rounded-full bg-white/10" />
        <button
          type="button"
          aria-label={label}
          disabled={disabled}
          onClick={mode === "free" ? onToggle : undefined}
          onPointerDown={pressStart}
          onPointerUp={pressEnd}
          onPointerCancel={pressEnd}
          onContextMenu={(e) => e.preventDefault()}
          className={`relative z-10 flex h-24 w-24 touch-none items-center justify-center rounded-full shadow-2xl transition-all duration-200 active:scale-95 ${STYLES[state]}`}
          style={
            state === "idle"
              ? { background: "linear-gradient(135deg, var(--color-accent), #5b8cff 60%, var(--color-accent-2))" }
              : undefined
          }
        >
          {state === "connecting" ? (
            <Loader2 className="h-10 w-10 animate-spin" />
          ) : state === "adam" ? (
            <Volume2 className="h-10 w-10" />
          ) : state === "disabled" ? (
            <MicOff className="h-10 w-10" />
          ) : (
            <Mic className="h-10 w-10" />
          )}
        </button>
      </div>
      <p className="h-5 text-center text-sm text-muted">{label}</p>
    </div>
  );
}
