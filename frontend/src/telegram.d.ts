/** telegram-web-app.js uchun minimal tiplar (faqat ishlatiladigan qismlar). */
export {};

declare global {
  interface TelegramThemeParams {
    bg_color?: string;
    text_color?: string;
    hint_color?: string;
    link_color?: string;
    button_color?: string;
    button_text_color?: string;
    secondary_bg_color?: string;
    header_bg_color?: string;
    accent_text_color?: string;
    section_bg_color?: string;
    destructive_text_color?: string;
  }

  interface TelegramWebAppUser {
    id: number;
    first_name: string;
    last_name?: string;
    username?: string;
    language_code?: string;
  }

  interface TelegramBackButton {
    show(): void;
    hide(): void;
    onClick(cb: () => void): void;
    offClick(cb: () => void): void;
  }

  interface TelegramHaptic {
    impactOccurred(style: "light" | "medium" | "heavy" | "rigid" | "soft"): void;
    notificationOccurred(type: "error" | "success" | "warning"): void;
    selectionChanged(): void;
  }

  interface TelegramWebApp {
    initData: string;
    initDataUnsafe: { user?: TelegramWebAppUser; start_param?: string };
    version: string;
    platform: string;
    colorScheme: "light" | "dark";
    themeParams: TelegramThemeParams;
    isExpanded: boolean;
    viewportHeight: number;
    viewportStableHeight: number;
    BackButton: TelegramBackButton;
    HapticFeedback: TelegramHaptic;
    ready(): void;
    expand(): void;
    close(): void;
    setHeaderColor(color: string): void;
    setBackgroundColor(color: string): void;
    enableClosingConfirmation(): void;
    disableClosingConfirmation(): void;
    disableVerticalSwipes?(): void;
    isVersionAtLeast(version: string): boolean;
    onEvent(event: string, cb: () => void): void;
    offEvent(event: string, cb: () => void): void;
    showAlert(message: string, cb?: () => void): void;
    openTelegramLink?(url: string): void;
  }

  interface Window {
    Telegram?: { WebApp: TelegramWebApp };
    webkitAudioContext?: typeof AudioContext;
  }
}
