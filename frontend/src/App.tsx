/** Ilova ildizi: Telegram SDK init, marshrutlar, pastki navigatsiya. */
import { useEffect } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import BottomNav from "./components/BottomNav";
import { ErrorState, Spinner } from "./components/Status";
import { initTelegram, isInTelegram } from "./hooks/useTelegram";
import Home from "./pages/Home";
import Lessons from "./pages/Lessons";
import Onboarding from "./pages/Onboarding";
import Plans from "./pages/Plans";
import Progress from "./pages/Progress";
import Session from "./pages/Session";
import Settings from "./pages/Settings";
import { useUserStore } from "./store/userStore";

function TabsLayout() {
  return (
    <div className="h-full overflow-y-auto">
      <Outlet />
      <BottomNav />
    </div>
  );
}

/** Profil yuklanguncha kutadi; birinchi kirishda Onboarding'ga yo'naltiradi. */
function ProfileGate() {
  const { me, error, load } = useUserStore();
  const location = useLocation();

  useEffect(() => {
    if (!me) void load();
  }, [me, load]);

  if (!me) {
    return error ? (
      <div className="pt-16">
        <ErrorState message={error} onRetry={() => void load()} />
      </div>
    ) : (
      <Spinner />
    );
  }
  if (!me.user.onboarded && location.pathname !== "/onboarding") return <Navigate to="/onboarding" replace />;
  return <Outlet />;
}

function OutsideTelegram() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-8 text-center">
      <div className="text-5xl">🤖</div>
      <h1 className="text-xl font-bold">Adam faqat Telegram ichida ishlaydi</h1>
      <p className="text-sm text-muted">Botni oching va «🎤 Adam bilan gapirish» tugmasini bosing.</p>
    </div>
  );
}

export default function App() {
  useEffect(() => {
    initTelegram();
  }, []);

  // Production'da Telegram'dan tashqarida ochilsa — yo'naltiruvchi ekran
  if (!import.meta.env.DEV && !isInTelegram()) return <OutsideTelegram />;

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<ProfileGate />}>
          <Route element={<TabsLayout />}>
            <Route path="/" element={<Home />} />
            <Route path="/lessons" element={<Lessons />} />
            <Route path="/progress" element={<Progress />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
          <Route path="/session" element={<Session />} />
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/plans" element={<Plans />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
