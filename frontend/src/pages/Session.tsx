/**
 * Asosiy ovozli sessiya ekrani: Avatar + LevelBadge + Statistika + Transcript + ErrorPanel + MicButton.
 * Holatlar: start -> ulanish -> jonli suhbat (kerak bo'lsa daraja testi) -> yakuniy xulosa.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { AlertCircle, BarChart3, BookOpen, RotateCcw, Settings as SettingsIcon, Square, Sparkles, Target, X } from "lucide-react";
import AdamAvatar from "../components/AdamAvatar";
import ErrorPanel from "../components/ErrorPanel";
import LimitCard from "../components/LimitCard";
import LevelBadge from "../components/LevelBadge";
import MicButton, { type MicVisualState } from "../components/MicButton";
import SessionStats, { formatDuration, ScoreBars } from "../components/SessionStats";
import Transcript from "../components/Transcript";
import { MicError, useAudio } from "../hooks/useAudio";
import { useGeminiWS } from "../hooks/useGeminiWS";
import { getWebApp, haptic, useBackButton } from "../hooks/useTelegram";
import type { LessonTopic } from "../lib/api";
import { isExhausted, PLAN_ICON, remainingLabel } from "../lib/plan";
import { EXPLAIN_OPTIONS, GOAL_OPTIONS, LEVEL_NAMES, MIC_OPTIONS } from "../lib/settingsOptions";
import { useSessionStore } from "../store/sessionStore";
import { useUserStore } from "../store/userStore";

/** Adam gapirayotganda shu RMS dan baland ovoz "foydalanuvchi gapiryapti" deb hisoblanadi (aks-sado pastroq). */
const BARGE_IN_RMS = 0.045;
/** Shuncha ketma-ket baland chunk (100 ms) bo'lsa Adam'ni bo'lishga ruxsat */
const BARGE_IN_CHUNKS = 3;
/** Shovqin darvozasi: shundan past ovoz hech qachon nutq deb hisoblanmaydi */
const SPEECH_MIN_RMS = 0.015;
/** Nutq = fon shovqinidan shuncha marta baland */
const SPEECH_OVER_NOISE = 2.5;
/** Nutq boshlanishi uchun ketma-ket baland chunk'lar (100 ms) */
const SPEECH_OPEN_CHUNKS = 2;
/** Gap tugagach darvoza shuncha chunk ochiq turadi (so'z oxirlari kesilmasin) */
const SPEECH_HANGOVER_CHUNKS = 8;
/** Darvoza ochilganda yuboriladigan oldingi chunk'lar (so'z boshi yo'qolmasin) */
const SPEECH_PREROLL_CHUNKS = 3;

export default function Session() {
  const navigate = useNavigate();
  const location = useLocation();
  const topic = (location.state as { topic?: LessonTopic } | null)?.topic ?? null;
  const audio = useAudio();
  const s = useSessionStore();
  const me = useUserStore((st) => st.me);
  const reloadMe = useUserStore((st) => st.load);
  const [micError, setMicError] = useState<string | null>(null);
  const gate = useRef({ open: false, loud: 0, pre: [] as ArrayBuffer[] });
  const noise = useRef({ open: false, loud: 0, hang: 0, floor: 0.005, pre: [] as ArrayBuffer[] });
  const pttPressed = useRef(false);
  const modeRef = useRef(s.mode);
  modeRef.current = s.mode;

  const ws = useGeminiWS({
    onAudio: audio.playPcm,
    onInterrupted: audio.stopPlayback,
  });

  /**
   * Mikrofon chunk'lari: ptt rejimda faqat bosib turilganda yuboriladi.
   * free rejimda Adam gapirayotganda uning o'z ovozi (aks-sado) Gemini'ga ketmasligi uchun
   * faqat baland, davomli nutq o'tkaziladi — shunda foydalanuvchi baribir Adam'ni bo'la oladi.
   */
  const isOutputActive = audio.isOutputActive;
  const onChunk = useCallback(
    (pcm: ArrayBuffer, rms: number) => {
      if (modeRef.current === "ptt") {
        if (pttPressed.current) ws.sendAudio(pcm);
        return;
      }
      const g = gate.current;
      if (!isOutputActive()) {
        // Jimlikda fon shovqini o'rniga raqamli jimlik yuboramiz: Gemini shovqinni so'z deb
        // "eshitmaydi", lekin VAD gap tugaganini baribir aniqlaydi
        const n = noise.current;
        if (g.open) {
          // Foydalanuvchi Adam'ni bo'lib gapiryapti — gapi kesilmasin
          n.open = true;
          n.hang = SPEECH_HANGOVER_CHUNKS;
        }
        g.open = false;
        g.loud = 0;
        g.pre = [];
        const threshold = Math.max(SPEECH_MIN_RMS, n.floor * SPEECH_OVER_NOISE);
        const loud = rms > threshold;
        if (n.open) {
          ws.sendAudio(pcm);
          n.hang = loud ? SPEECH_HANGOVER_CHUNKS : n.hang - 1;
          if (n.hang <= 0) n.open = false;
          return;
        }
        const k = loud ? 0.03 : 0.1;
        n.floor = Math.min(0.05, n.floor * (1 - k) + rms * k);
        n.loud = loud ? n.loud + 1 : 0;
        n.pre.push(pcm);
        if (n.pre.length > SPEECH_PREROLL_CHUNKS) n.pre.shift();
        if (n.loud >= SPEECH_OPEN_CHUNKS) {
          n.open = true;
          n.loud = 0;
          n.hang = SPEECH_HANGOVER_CHUNKS;
          n.pre.forEach((chunk) => ws.sendAudio(chunk));
          n.pre = [];
          return;
        }
        ws.sendAudio(new ArrayBuffer(pcm.byteLength));
        return;
      }
      noise.current.open = false;
      noise.current.loud = 0;
      if (g.open) {
        ws.sendAudio(pcm);
        return;
      }
      g.pre.push(pcm);
      if (g.pre.length > BARGE_IN_CHUNKS) g.pre.shift();
      g.loud = rms > BARGE_IN_RMS ? g.loud + 1 : 0;
      if (g.loud >= BARGE_IN_CHUNKS) {
        g.open = true;
        g.pre.forEach((chunk) => ws.sendAudio(chunk));
        g.pre = [];
      }
    },
    [ws, isOutputActive],
  );

  const startMic = useCallback(async () => {
    try {
      setMicError(null);
      await audio.startRecording(onChunk);
      useSessionStore.getState().setMicActive(modeRef.current === "free");
      return true;
    } catch (err) {
      const msg = err instanceof MicError ? err.message : "Mikrofonni ishga tushirib bo'lmadi.";
      setMicError(msg);
      haptic("error");
      return false;
    }
  }, [audio, onChunk]);

  const stopMic = useCallback(() => {
    audio.stopRecording();
    useSessionStore.getState().setMicActive(false);
  }, [audio]);

  // Adam gapirayotganini store'ga uzatamiz (avatar va tugma holati uchun)
  useEffect(() => {
    useSessionStore.getState().setAdamSpeaking(audio.isPlaying);
  }, [audio.isPlaying]);

  // Qolgan vaqt / tarif eskirmasin
  useEffect(() => {
    void reloadMe();
  }, [reloadMe]);

  // Ogohlantirish 6 soniyadan keyin yo'qoladi
  useEffect(() => {
    if (!s.warning) return;
    haptic("warning");
    const t = window.setTimeout(() => useSessionStore.getState().setWarning(null), 6000);
    return () => window.clearTimeout(t);
  }, [s.warning]);

  // Sessiya tugasa yoki xato bo'lsa mikrofonni yopamiz
  useEffect(() => {
    if (s.status === "ended" || s.status === "error") {
      stopMic();
      audio.stopPlayback();
    }
    // Daraja/progress o'zgargan bo'lishi mumkin — profilni yangilaymiz
    if (s.status === "ended") void reloadMe();
  }, [s.status, stopMic, audio, reloadMe]);

  // Sahifadan chiqishda: mikrofonni yopish va sessiyani yakunlash
  useEffect(
    () => () => {
      void ws.end();
      useSessionStore.getState().reset();
    },
    [ws],
  );

  /** Start tugmasi (foydalanuvchi bosishi ichida — iOS audio + mikrofon ruxsati uchun shart). */
  const start = async () => {
    haptic("medium");
    useSessionStore.getState().reset();
    try {
      await audio.unlock();
    } catch {
      /* startMic xabar beradi */
    }
    const ok = await startMic();
    if (!ok) return;
    ws.connect(modeRef.current, topic?.id ?? null);
  };

  const clearTopic = () => {
    haptic("light");
    navigate("/session", { replace: true, state: null });
  };

  const finish = async () => {
    haptic("medium");
    stopMic();
    audio.stopPlayback();
    await ws.end();
  };

  const toggleFree = async () => {
    haptic("light");
    if (s.micActive) {
      stopMic();
      ws.sendJSON({ type: "audio_stream_end" });
    } else {
      await startMic();
    }
  };

  const pressStart = () => {
    haptic("light");
    audio.stopPlayback();
    pttPressed.current = true;
    useSessionStore.getState().setMicActive(true);
    ws.sendJSON({ type: "activity_start" });
  };

  const pressEnd = () => {
    pttPressed.current = false;
    useSessionStore.getState().setMicActive(false);
    ws.sendJSON({ type: "activity_end" });
  };

  const goHome = useCallback(() => navigate("/"), [navigate]);
  useBackButton(true, goHome);

  // Faol sessiyada Telegram yopishni tasdiqlash so'raydi
  useEffect(() => {
    const tg = getWebApp();
    if (!tg?.isVersionAtLeast?.("6.2")) return;
    if (s.status === "ready" || s.status === "reconnecting") tg.enableClosingConfirmation();
  }, [s.status]);

  const active = s.status === "connecting" || s.status === "ready" || s.status === "reconnecting";

  // ---------------------------------------------------------------- yakuniy xulosa
  if (s.status === "ended" && s.summary) {
    const sum = s.summary;
    const lvl = sum.level;
    return (
      <div className="mx-auto flex min-h-full max-w-md flex-col gap-4 px-4 pb-8 pt-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <Sparkles className="h-8 w-8 text-accent-2" />
          <h1 className="text-2xl font-bold">Barakalla! 🎉</h1>
          <p className="text-sm text-muted">Sessiya yakunlandi va natijalar saqlandi</p>
        </div>
        {s.placementResult && (
          <div className="card border-good/50 px-4 py-3 text-center">
            <div className="text-sm text-muted">Darajangiz aniqlandi</div>
            <div className="text-2xl font-black">
              {s.placementResult.level} — {LEVEL_NAMES[s.placementResult.level as keyof typeof LEVEL_NAMES] ?? ""}
            </div>
            {s.placementResult.reason && <p className="mt-1 text-xs italic text-indigo-100/80">{s.placementResult.reason}</p>}
          </div>
        )}
        <LevelBadge
          level={lvl.level}
          nextLevel={lvl.next_level}
          progress={lvl.progress}
          baseProgress={s.baseLevel?.progress}
          leveledUp={lvl.leveled_up}
        />
        <div className="grid grid-cols-4 gap-2">
          {[
            { v: formatDuration(sum.duration_seconds), l: "vaqt" },
            { v: sum.sentences_spoken, l: "gap" },
            { v: sum.words_spoken, l: "so'z" },
            { v: sum.errors_count, l: "xato" },
          ].map((it) => (
            <div key={it.l} className="card flex flex-col items-center py-3">
              <span className="text-lg font-bold">{it.v}</span>
              <span className="text-[10px] uppercase tracking-wide text-muted">{it.l}</span>
            </div>
          ))}
        </div>
        {Object.values(sum.scores).some((v) => v != null) && (
          <div className="card px-4 py-3">
            <div className="mb-2 text-sm font-semibold">Baholar</div>
            <ScoreBars scores={sum.scores} />
          </div>
        )}
        {sum.new_words.length > 0 && (
          <div className="card px-4 py-3">
            <div className="mb-2 text-sm font-semibold">Yangi so'zlar</div>
            <div className="flex flex-wrap gap-1.5">
              {sum.new_words.map((w) => (
                <span key={w} className="rounded-full bg-accent/20 px-2.5 py-1 text-xs font-medium text-indigo-100">
                  {w}
                </span>
              ))}
            </div>
          </div>
        )}
        {s.limit && <LimitCard plan={s.limit} message={s.limit.message} />}
        <ErrorPanel errors={s.errors} dismissed={[]} onDismiss={() => undefined} max={5} />
        <div className="mt-2 grid gap-2">
          {!s.limit && (
            <button type="button" className="btn-primary" onClick={start}>
              <RotateCcw className="h-5 w-5" /> Yana gaplashish
            </button>
          )}
          <button type="button" className="btn-ghost" onClick={() => navigate("/progress")}>
            <BarChart3 className="h-4 w-4" /> Natijalarni ko'rish
          </button>
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------- start / xato ekrani
  if (!active) {
    const limitPlan = s.limit ?? (me && isExhausted(me.plan) ? me.plan : null);
    return (
      <div className="mx-auto flex min-h-full max-w-md flex-col gap-5 px-4 pb-8 pt-8">
        <div className="flex flex-col items-center gap-3 text-center">
          <AdamAvatar speaking={false} listening={false} getLevel={audio.getOutputLevel} />
          <h1 className="text-2xl font-bold">{topic ? "Bugungi dars" : "Adam bilan gaplashamiz"}</h1>
          <p className="max-w-xs text-sm text-muted">
            Adam o'zbekcha tushuntiradi va inglizcha mashq qildiradi. Quloqchin bilan gaplashish yanada qulay 🎧
          </p>
        </div>
        {limitPlan && <LimitCard plan={limitPlan} message={s.limit?.message} />}
        {(s.errorMessage || micError) && !limitPlan && (
          <div className="card flex items-start gap-3 border-bad/50 px-4 py-3 text-sm">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-bad" />
            <span>{micError ?? s.errorMessage}</span>
          </div>
        )}
        {topic ? (
          <div className="card flex items-start gap-3 border-accent/60 px-4 py-3">
            <span className="text-2xl">{topic.emoji}</span>
            <div className="min-w-0 flex-1 text-sm">
              <div className="font-semibold">
                {topic.title} <span className="text-xs text-muted">· {topic.level}</span>
              </div>
              <div className="text-muted">{topic.task}</div>
            </div>
            <button type="button" onClick={clearTopic} aria-label="Mavzuni olib tashlash">
              <X className="h-5 w-5 text-muted" />
            </button>
          </div>
        ) : (
          <button
            type="button"
            className="card flex items-center gap-3 px-4 py-3 text-left text-sm"
            onClick={() => navigate("/lessons")}
          >
            <BookOpen className="h-5 w-5 shrink-0 text-accent-2" />
            <span className="flex-1">
              <span className="block font-semibold">Mavzu tanlash</span>
              <span className="block text-muted">Maktab, ish, sayohat, do'kon… vaziyatlarda rol o'ynab mashq qiling</span>
            </span>
          </button>
        )}
        {me?.user.needs_placement ? (
          <div className="card flex items-start gap-3 border-accent/60 px-4 py-3">
            <Target className="mt-0.5 h-5 w-5 shrink-0 text-accent-2" />
            <div className="text-sm">
              <div className="font-semibold">Avval darajangizni aniqlaymiz</div>
              <div className="text-muted">Adam 5-6 ta oddiy savol beradi. Bilmasangiz «bilmayman» deng — hechqisi yo'q.</div>
            </div>
          </div>
        ) : null}
        {me && (
          <button type="button" className="card flex items-center gap-3 px-4 py-3 text-left" onClick={() => navigate("/settings")}>
            <div className="min-w-0 flex-1 text-sm">
              <div>
                <span className="text-muted">Daraja: </span>
                <span className="font-semibold">
                  {me.user.needs_placement ? "aniqlanadi" : `${me.user.cefr_level} — ${LEVEL_NAMES[me.user.cefr_level]}`}
                </span>
              </div>
              <div>
                <span className="text-muted">Tushuntirish: </span>
                {EXPLAIN_OPTIONS.find((o) => o.value === me.user.explain_lang)?.title}
              </div>
              <div>
                <span className="text-muted">Maqsad: </span>
                {GOAL_OPTIONS.find((o) => o.value === me.user.goal)?.title}
                <span className="text-muted"> · </span>
                {MIC_OPTIONS.find((o) => o.value === s.mode)?.title}
              </div>
              <div>
                <span className="text-muted">Tarif: </span>
                {PLAN_ICON[me.plan.plan]} {me.plan.plan_title}
                <span className="text-muted"> · qolgan: </span>
                {remainingLabel(me.plan)}
              </div>
            </div>
            <SettingsIcon className="h-5 w-5 shrink-0 text-muted" />
          </button>
        )}
        {!limitPlan && (
          <button type="button" className="btn-primary mt-2" onClick={start}>
            🎤 Gaplashishni boshlash
          </button>
        )}
        <p className="text-center text-xs text-muted">Bitta sessiya {Math.round(s.timeoutSeconds / 60)} daqiqagacha</p>
      </div>
    );
  }

  // ---------------------------------------------------------------- jonli sessiya
  const micState: MicVisualState =
    s.status !== "ready"
      ? "connecting"
      : s.micActive
        ? "listening"
        : s.adamSpeaking
          ? "adam"
          : audio.isRecording || s.mode === "free"
            ? "idle"
            : "disabled";

  const statusText =
    s.status === "connecting"
      ? "Adam'ga ulanmoqda…"
      : s.status === "reconnecting"
        ? "Aloqa tiklanmoqda…"
        : s.adamSpeaking
          ? "Adam gapiryapti"
          : s.micActive
            ? "Sizni tinglayapman"
            : "Navbat sizda";

  return (
    <div className="mx-auto flex h-full max-w-md flex-col">
      <header className="flex items-center gap-2 px-4 pt-3">
        <div className="min-w-0 flex-1">
          {s.placement ? (
            <div className="card flex items-center gap-2 px-3 py-2.5 text-sm">
              <Target className="h-4 w-4 text-accent-2" /> Daraja aniqlanmoqda…
            </div>
          ) : s.level && (
            <LevelBadge
              compact
              level={s.level.level}
              nextLevel={s.level.next_level}
              progress={s.level.progress}
              baseProgress={s.baseLevel?.progress}
              leveledUp={s.level.leveled_up}
            />
          )}
        </div>
        <button
          type="button"
          onClick={finish}
          className="flex h-11 items-center gap-1.5 rounded-xl border border-line bg-surface-2/70 px-3 text-sm font-medium active:scale-95"
          aria-label="Sessiyani tugatish"
        >
          <Square className="h-4 w-4 fill-current" /> Tugatish
        </button>
      </header>

      {topic && (
        <div className="truncate px-4 pt-2 text-center text-xs text-muted">
          {topic.emoji} {topic.title}
        </div>
      )}

      <div className="flex flex-col items-center pt-2">
        <AdamAvatar
          size={s.lines.length > 0 ? 92 : 132}
          speaking={s.adamSpeaking}
          listening={s.micActive}
          getLevel={audio.getOutputLevel}
        />
        <div className="text-sm font-medium text-indigo-100/90">{statusText}</div>
      </div>

      <div className="px-4 pt-2">
        <SessionStats
          startedAt={s.startedAt}
          timeoutSeconds={s.timeoutSeconds}
          sentences={s.stats.sentences}
          words={s.stats.words}
          errors={s.errors.length}
          scores={s.scores}
        />
      </div>

      {s.warning && (
        <div className="mx-4 mt-2 flex items-center justify-between gap-2 rounded-xl bg-warn/15 px-3 py-2 text-sm text-warn">
          <span>{s.warning}</span>
          <button type="button" onClick={() => s.setWarning(null)} aria-label="Yopish">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      <Transcript lines={s.lines} />

      <ErrorPanel errors={s.errors} dismissed={s.dismissed} onDismiss={s.dismissError} />

      {micError && <p className="px-4 pt-2 text-center text-sm text-bad">{micError}</p>}

      <div className="safe-bottom flex justify-center pt-2">
        <MicButton
          state={micState}
          mode={s.mode}
          getLevel={audio.getMicLevel}
          onToggle={toggleFree}
          onPressStart={pressStart}
          onPressEnd={pressEnd}
        />
      </div>
    </div>
  );
}
