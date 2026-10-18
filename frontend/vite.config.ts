/** Vite konfiguratsiyasi: React + Tailwind v4, dev'da backendga proxy (/api, /ws). */
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.VITE_DEV_BACKEND || "http://localhost:8000";
  const proxy = {
    "/api": { target: backend, changeOrigin: true },
    "/ws": { target: backend.replace(/^http/, "ws"), ws: true, changeOrigin: true },
  };
  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      host: true,
      // Telegram'da test qilish uchun tunnel (cloudflared/ngrok) manzillariga ruxsat
      allowedHosts: true,
      proxy,
    },
    // Tunnel orqali Telegram'da test: `npm run build && npm run preview` (dev rejimi tunnelda juda sekin)
    preview: {
      port: 5173,
      host: true,
      allowedHosts: true,
      proxy,
    },
    build: {
      target: "es2020",
      sourcemap: false,
    },
  };
});
