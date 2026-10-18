/** Telegram WebApp SDK bilan ishlash: init, tema, haptic, BackButton. */
import { useEffect, useMemo } from "react";

export const HEADER_COLOR = "#1a1a2e";

export function getWebApp(): TelegramWebApp | undefined {
  return window.Telegram?.WebApp;
}

/** Telegram ichida ochilganmi (initData mavjud). */
export function isInTelegram(): boolean {
  return Boolean(getWebApp()?.initData);
}

/** Ilova bir marta ishga tushganda chaqiriladi: ready, expand, rang, yopishni tasdiqlash, tema. */
export function initTelegram(): void {
  const tg = getWebApp();
  applyTheme(tg?.themeParams);
  if (!tg) return;
  try {
    tg.ready();
    tg.expand();
    if (tg.isVersionAtLeast("6.1")) {
      tg.setHeaderColor(HEADER_COLOR);
      tg.setBackgroundColor(HEADER_COLOR);
    }
    if (tg.isVersionAtLeast("6.2")) tg.enableClosingConfirmation();
    if (tg.isVersionAtLeast("7.7")) tg.disableVerticalSwipes?.();
    tg.onEvent("themeChanged", () => applyTheme(tg.themeParams));
  } catch (err) {
    console.warn("Telegram init xatosi", err);
  }
}

/** Telegram tema ranglarini CSS o'zgaruvchilarga yozadi (dark default saqlanadi). */
function applyTheme(theme?: TelegramThemeParams): void {
  const root = document.documentElement.style;
  const map: Record<string, string | undefined> = {
    "--tg-button": theme?.button_color,
    "--tg-button-text": theme?.button_text_color,
    "--tg-link": theme?.link_color,
    "--tg-hint": theme?.hint_color,
  };
  for (const [key, value] of Object.entries(map)) {
    if (value) root.setProperty(key, value);
  }
}

export function haptic(kind: "light" | "medium" | "heavy" | "success" | "error" | "warning" | "select"): void {
  const h = getWebApp()?.HapticFeedback;
  if (!h) {
    if (navigator.vibrate && (kind === "medium" || kind === "heavy")) navigator.vibrate(15);
    return;
  }
  try {
    if (kind === "success" || kind === "error" || kind === "warning") h.notificationOccurred(kind);
    else if (kind === "select") h.selectionChanged();
    else h.impactOccurred(kind);
  } catch {
    /* eski Telegram versiyasi */
  }
}

/** To'lov bot chatida bo'ladi: bot'ni `/start plans` bilan ochadi. */
export function openBotPlans(botUsername: string | null | undefined): void {
  if (!botUsername) return;
  const url = `https://t.me/${botUsername}?start=plans`;
  const tg = getWebApp();
  try {
    if (tg?.openTelegramLink && tg.isVersionAtLeast("6.1")) {
      tg.disableClosingConfirmation();
      tg.openTelegramLink(url);
      return;
    }
  } catch {
    /* pastdagi zaxira */
  }
  window.open(url, "_blank");
}

/** Telegram BackButton'ni ko'rsatadi va bosilganda `onBack` chaqiradi. */
export function useBackButton(visible: boolean, onBack: () => void): void {
  useEffect(() => {
    const bb = getWebApp()?.BackButton;
    if (!bb) return;
    if (!visible) {
      bb.hide();
      return;
    }
    bb.show();
    bb.onClick(onBack);
    return () => {
      bb.offClick(onBack);
      bb.hide();
    };
  }, [visible, onBack]);
}

export function useTelegram() {
  return useMemo(() => {
    const tg = getWebApp();
    return {
      tg,
      user: tg?.initDataUnsafe?.user,
      inTelegram: Boolean(tg?.initData),
      platform: tg?.platform ?? "web",
    };
  }, []);
}
