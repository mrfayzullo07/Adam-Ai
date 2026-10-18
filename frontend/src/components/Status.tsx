/** Yuklanish va xato holatlari uchun umumiy komponentlar. */
import { Loader2, RefreshCw, WifiOff } from "lucide-react";

export function Spinner({ label = "Yuklanmoqda…" }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-muted">
      <Loader2 className="h-8 w-8 animate-spin text-accent" />
      <span className="text-sm">{label}</span>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="card mx-4 flex flex-col items-center gap-3 px-6 py-8 text-center">
      <WifiOff className="h-8 w-8 text-bad" />
      <p className="text-sm text-indigo-100/90">{message}</p>
      {onRetry && (
        <button type="button" className="btn-ghost" onClick={onRetry}>
          <RefreshCw className="h-4 w-4" /> Qayta urinish
        </button>
      )}
    </div>
  );
}
