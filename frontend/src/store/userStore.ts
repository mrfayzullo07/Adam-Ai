/** Foydalanuvchi profili va Adam sozlamalari (barcha sahifalar uchun umumiy). */
import { create } from "zustand";
import { api, type MeResponse, type UserSettings } from "../lib/api";
import { useSessionStore } from "./sessionStore";

interface UserState {
  me: MeResponse | null;
  loading: boolean;
  error: string | null;
  load: () => Promise<void>;
  save: (patch: Partial<UserSettings>) => Promise<void>;
}

export const useUserStore = create<UserState>((set, get) => ({
  me: null,
  loading: false,
  error: null,

  load: async () => {
    set({ loading: true, error: null });
    try {
      const me = await api.me();
      set({ me, loading: false });
      useSessionStore.getState().setMode(me.user.mic_mode);
    } catch (e) {
      set({ loading: false, error: (e as Error).message || "Ma'lumotlarni yuklab bo'lmadi" });
    }
  },

  save: async (patch) => {
    const user = await api.saveSettings(patch);
    const prev = get().me;
    if (prev) {
      set({
        me: {
          ...prev,
          user,
          level: {
            level: user.cefr_level,
            next_level: prev.level.level === user.cefr_level ? prev.level.next_level : nextLevel(user.cefr_level),
            progress: user.level_progress,
          },
        },
      });
    }
    if (patch.mic_mode) useSessionStore.getState().setMode(patch.mic_mode);
  },
}));

const LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"];

export function nextLevel(level: string): string | null {
  const i = LEVELS.indexOf(level);
  return i >= 0 && i < LEVELS.length - 1 ? LEVELS[i + 1] : null;
}
