/** Pastki navigatsiya: Bosh sahifa, Darslar, Gapirish, Natijalar, Sozlamalar. */
import { NavLink } from "react-router-dom";
import { BarChart3, BookOpen, Home, Mic, Settings } from "lucide-react";
import { haptic } from "../hooks/useTelegram";

const ITEMS = [
  { to: "/", label: "Bosh sahifa", icon: Home, end: true },
  { to: "/lessons", label: "Darslar", icon: BookOpen, end: false },
  { to: "/session", label: "Gapirish", icon: Mic, end: false },
  { to: "/progress", label: "Natijalar", icon: BarChart3, end: false },
  { to: "/settings", label: "Sozlamalar", icon: Settings, end: false },
];

export default function BottomNav() {
  return (
    <nav className="safe-bottom fixed inset-x-0 bottom-0 z-20 border-t border-line/60 bg-ink/90 backdrop-blur-md">
      <div className="mx-auto flex max-w-md px-2 pt-1">
        {ITEMS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            onClick={() => haptic("select")}
            className={({ isActive }) =>
              `flex flex-1 flex-col items-center gap-0.5 rounded-xl py-2 text-[11px] font-medium transition ${
                isActive ? "text-white" : "text-muted"
              }`
            }
          >
            {({ isActive }) => (
              <>
                <span
                  className={`flex h-8 w-12 items-center justify-center rounded-full transition ${
                    isActive ? "bg-accent/25 text-accent-2" : ""
                  }`}
                >
                  <Icon className="h-5 w-5" />
                </span>
                {label}
              </>
            )}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
