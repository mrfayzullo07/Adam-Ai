# Adam — ingliz tili ovozli AI repetitori (Telegram Mini App + Gemini Live)

Adam o'zbekistonlik boshlovchilar uchun real-time ovozli repetitor: foydalanuvchi mikrofon orqali
gapiradi, Gemini Live API darhol ovozli javob beradi. Adam o'zbekcha tushuntiradi (ovoz + subtitr,
italik), inglizcha mashq qildiradi, xatolarni real vaqtda ko'rsatadi va CEFR darajasini (A1–C2) kuzatadi.

```
Telegram ── /start ──► aiogram bot ──► "🎤 Adam bilan gapirish" (WebApp)
                                              │
Mini App (React, Vercel) ── mic ─► AudioWorklet ─► PCM16 16 kHz ─► WSS /ws/audio ─► FastAPI ─► Gemini Live
            ▲                                                         │  (tool calls: log_error,
            └──── PCM16 24 kHz + JSON (transkript, xato, skor) ◄──────┘   update_scores, ...)
                                                                      │
                                                     PostgreSQL (statistika) + Redis (lock, rate-limit)
```

## Imkoniyatlar

- **Real-time ovozli suhbat** — Gemini Live (`gemini-3.8-live`, zaxira model bilan), barge-in (gapini bo'lish).
- **Ikki mikrofon rejimi** — *Erkin suhbat* (Gemini VAD) va *Bosib gapirish* (activity_start/end). Tanlov saqlanadi.
- **O'zbekcha tushuntirish + inglizcha mashq** — darajaga qarab til nisbati (A1: ~70% o'zbekcha → B2+: faqat inglizcha).
  Transkriptda o'zbekcha gaplar italik, inglizcha qalin.
- **Real-time xatolar** — Adam har tuzatishda `log_error` chaqiradi → ErrorPanel (jiddiylik rangi, o'zbekcha izoh).
- **Gibrid CEFR** — backend skorlar, davomiylik va xatolardan progress hisoblaydi ("A1 → A2: 42%"),
  Adam `suggest_level` bilan faqat tavsiya beradi. Sessiya davomida prognoz jonli yangilanadi.
- **Xotira** — har sessiyaga oxirgi 5 xato, daraja va oxirgi sessiya xulosasi (statistika, xatolar, so'zlar, oxirgi gaplar) system prompt'ga qo'shiladi.
- **Progress** — haftalik/oylik grafik, streak, o'rtacha baholar, xatolar tahlili, lug'at.
- **Xavfsizlik** — initData HMAC-SHA256 (har API/WS), Redis "1 user = 1 sessiya" lock, rate-limit, CORS faqat FRONTEND_URL, audio saqlanmaydi.

## Loyiha tuzilmasi

```
backend/
  app/
    main.py            FastAPI, CORS, lifespan (DB + Redis + bot)
    config.py          pydantic-settings (.env)
    database.py        async SQLAlchemy (Postgres/asyncpg yoki lokal SQLite)
    models.py          users, sessions, errors, progress, vocabulary
    schemas.py         API sxemalari
    redis_client.py    Redis yoki in-memory fallback, SessionLock, rate-limit
    bot/               aiogram: /start, /help; polling (dev) / webhook (prod)
    gemini/
      client.py        Live config (VAD, ovoz, transkripsiya, tools) + model fallback
      session.py       AdamBridge: client WS <-> Gemini (upstream/downstream/watchdog)
      tools.py         log_error, update_scores, record_vocabulary, suggest_level
      prompt.py        ADAM_SYSTEM_PROMPT + dinamik context
    services/
      level.py         gibrid CEFR algoritmi
      session_service.py  sessiya holati, kontekst, yakunlash (DB)
    api/
      auth.py          initData validatsiya + POST /api/auth
      ws.py            /ws/audio
      progress.py      /api/me, /api/progress, /api/sessions, /api/errors, /api/vocabulary
    utils/audio.py     float32 <-> PCM16
  tests/               26 ta test (auth, ws+lock, audio, tools, session end)
  Dockerfile, docker-compose.yml, railway.json
frontend/
  public/worklets/pcm-recorder.js   AudioWorklet (48k -> 16 kHz Int16, 100 ms)
  src/hooks/useAudio.ts             mikrofon + 24 kHz ijro navbati
  src/hooks/useGeminiWS.ts          WS + reconnect (exponential backoff)
  src/hooks/useTelegram.ts          SDK init, tema, haptic, BackButton
  src/store/sessionStore.ts         Zustand
  src/pages/{Home,Session,Progress}.tsx
  src/components/{MicButton,Transcript,ErrorPanel,LevelBadge,SessionStats,AdamAvatar,...}.tsx
```

## Lokal ishga tushirish (Docker shart emas)

Talab: Python 3.11+, Node 20+.

### 1. Backend

```powershell
cd backend
py -3.11 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # TELEGRAM_BOT_TOKEN, GEMINI_API_KEY ni to'ldiring
# Brauzerda Telegram'siz test uchun .env da: ALLOW_DEV_AUTH=true
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

`DATABASE_URL` va `REDIS_URL` bo'sh bo'lsa: SQLite (`backend/adam.db`) va in-memory Redis ishlatiladi.
Development'da bot **polling** rejimida ishlaydi (alohida jarayon kerak emas).

### 2. Frontend

```powershell
cd frontend
npm install
npm run dev                 # http://localhost:5173 (/api va /ws backendga proxy qilinadi)
```

Brauzerda `dev:<VITE_DEV_TELEGRAM_ID>` bilan avtomatik kiriladi (faqat `npm run dev` va backendda `ALLOW_DEV_AUTH=true`).

### 3. Telegram ichida lokal test (ixtiyoriy)

Telegram WebApp faqat HTTPS ochadi. Frontendni tunnel orqali chiqaring:

```powershell
cloudflared tunnel --url http://localhost:5173
```

Chiqqan `https://....trycloudflare.com` manzilini `backend/.env` dagi `WEBAPP_URL` ga yozing va backendni qayta ishga tushiring → botda /start.

### 4. Docker bilan to'liq stek (Postgres + Redis)

```bash
cd backend && docker compose up --build
```

## Testlar

```powershell
cd backend
.venv\Scripts\python -m pytest -q
```

| # | Test fayli | Nimani tekshiradi |
|---|------------|-------------------|
| 1 | `test_auth.py` | initData HMAC: to'g'ri / buzilgan / eskirgan / boshqa token; API 401 |
| 2 | `test_ws.py` | initData'siz WS → 4401; ikkinchi sessiya → 4429; to'liq oqim soxta Gemini bilan |
| 3 | `test_audio.py` | float32 ↔ PCM16 roundtrip, clipping, chunk validatsiya |
| 4 | `test_tools.py` | log_error DB yozuvi + event, skor chegaralash, vocabulary upsert, prompt |
| 5 | `test_session_end.py` | finalize → sessions/progress/users, daraja algoritmi, streak |

Frontend: `npm run build` (TypeScript strict tekshiruvi bilan).

## WebSocket protokoli (`/ws/audio?init_data=<urlencoded>&mode=free|ptt`)

| Yo'nalish | Turi | Tavsif |
|-----------|------|--------|
| client → server | binary | PCM16 LE, 16 kHz, mono, ~100 ms |
| client → server | `activity_start` / `activity_end` | push-to-talk |
| client → server | `audio_stream_end` | free rejimda mikrofon o'chirilganda |
| client → server | `text`, `ping`, `end` | matn, heartbeat, to'g'ri yakunlash |
| server → client | binary | PCM16 LE, 24 kHz, mono |
| server → client | `ready` | sessiya ochildi (daraja, timeout, model) |
| server → client | `user_transcript` / `adam_transcript` | oqimli transkript bo'laklari |
| server → client | `turn_complete` / `interrupted` | navbat tugadi / barge-in (ijroni to'xtating) |
| server → client | `error` / `scores` / `vocabulary` / `level_update` | tool natijalari |
| server → client | `warning` | 1 daqiqa qoldi / go_away |
| server → client | `session_end` | yakuniy statistika (DB ga yozilgan) |
| server → client | `server_error` | `unauthorized` (4401), `active_session`/`rate_limited` (4429), `gemini_unavailable` (4503) |

## Deploy

### Backend — Railway (tavsiya)

1. Railway'da yangi project → **Deploy from GitHub** (root: `backend/`) yoki CLI: `cd backend && railway up`.
   `railway.json` Dockerfile va `/health` healthcheck'ni sozlaydi.
2. Project'ga **PostgreSQL** va **Redis** qo'shing (yoki Neon/Supabase + Upstash).
3. Variables:
   ```
   TELEGRAM_BOT_TOKEN=...
   GEMINI_API_KEY=...
   DATABASE_URL=${{Postgres.DATABASE_URL}}        # postgres:// avtomatik asyncpg'ga o'giriladi
   REDIS_URL=${{Redis.REDIS_URL}}
   ENVIRONMENT=production
   FRONTEND_URL=https://<vercel-app>.vercel.app
   WEBAPP_URL=https://<vercel-app>.vercel.app
   BACKEND_URL=https://<railway-app>.up.railway.app
   WEBHOOK_SECRET=<uzun tasodifiy satr>
   GEMINI_MODEL=gemini-3.8-live
   ```
4. Startup'da webhook avtomatik o'rnatiladi: `BACKEND_URL/telegram/webhook` (secret token bilan).

**WebSocket eslatmalari:** uvicorn `--ws-ping-interval 20` bilan ishlaydi, shuning uchun proxy bo'sh ulanishni uzmaydi.
Railway'da WS uchun qo'shimcha sozlama shart emas. Render: Web Service (Docker), bepul tarifda uxlab qoladi — pullik tarif tavsiya etiladi.
Fly.io: `fly launch` → `[http_service] auto_stop_machines = false`. Gemini audio sessiyasi 15 daqiqa bilan cheklangan
(`SESSION_TIMEOUT_SECONDS=900`). Bir nechta instance ishlatsangiz Redis majburiy (lock umumiy bo'lishi uchun).

### Frontend — Vercel

```bash
cd frontend
vercel                      # birinchi marta: project yaratadi
vercel env add VITE_API_URL production   # https://<railway-app>.up.railway.app
vercel --prod
```

`vercel.json` SPA rewrite va `Permissions-Policy: microphone=(self)` header'ini sozlaydi.

### Yakuniy tekshiruv

1. `https://<backend>/health` → `{"status":"ok"}`
2. Botda `/start` → «🎤 Adam bilan gapirish» tugmasi chiqadi
3. Mini App → mikrofon ruxsati → Adam o'zbekcha salomlashadi
4. Noto'g'ri gap ayting → ErrorPanel'da xato chiqadi
5. «Tugatish» → xulosa; Progress sahifasida statistika saqlangan

## Muhim eslatmalar

- `GEMINI_MODEL` faqat `.env` dan o'qiladi; ulanmasa `GEMINI_FALLBACK_MODELS` ketma-ket sinaladi.
- Audio: 16 kHz kirish / 24 kHz chiqish, PCM 16-bit mono. Audio hech qayerda saqlanmaydi.
- Har WebSocket = yangi Gemini sessiyasi; davomiylik DB + dinamik context orqali ta'minlanadi.
- Qisqa (<60 s) yoki baholanmagan sessiyalar darajaga ta'sir qilmaydi; daraja avtomatik pasaymaydi.
- Spetsifikatsiyaga qo'shilgan ustunlar: `users.level_progress`, `sessions.mode/level_at_start/summary`, `errors.explanation`.
  Jadvallar startup'da `create_all` bilan yaratiladi (mavjud jadvallarga ustun qo'shilmaydi — sxema o'zgarsa migratsiya qiling).
