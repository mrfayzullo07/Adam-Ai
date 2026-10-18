# Adam — ingliz tili ovozli AI repetitori (Telegram Mini App + Gemini Live)

Adam o'zbekistonlik boshlovchilar uchun real-time ovozli repetitor: foydalanuvchi mikrofon orqali
gapiradi, Gemini Live API darhol ovozli javob beradi. Adam o'zbekcha tushuntiradi (ovoz + subtitr,
italik), inglizcha mashq qildiradi, xatolarni real vaqtda ko'rsatadi va CEFR darajasini (A1–C2) kuzatadi.

```
Telegram ── /start ──► aiogram bot ──► "🎤 Adam bilan gapirish" (WebApp)
                                              │
Mini App (React, Netlify) ── mic ─► AudioWorklet ─► PCM16 16 kHz ─► WSS /ws/audio ─► FastAPI ─► Gemini Live
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
- **Tariflar** — Free (har 12 soatda 2 daqiqa), Pro (29 000 so'm/30 kun, har 6 soatda 1 soat), Max (69 000 so'm/30 kun, cheksiz + guruh/kanal).
- **To'lov** — karta orqali o'tkazma, chek skrinshoti Gemini bilan avtomatik tekshiriladi (summa, karta, sana, tranzaksiya, dublikat);
  shubhali cheklar admin'ga Tasdiqlash/Rad etish tugmalari bilan yuboriladi.
- **Guruh va kanallar (Max)** — guruhda @mention/reply orqali tarjima va tushuntirish, kanalga har kuni avtomatik dars.
- **Admin panel** — botning o'zida: statistika, foydalanuvchilar, obunachilar, qo'lda tarif berish/olish.
- **Xavfsizlik** — initData HMAC-SHA256 (har API/WS), Redis "1 user = 1 sessiya" lock, rate-limit, CORS faqat FRONTEND_URL, audio saqlanmaydi.

## Loyiha tuzilmasi

```
backend/
  app/
    main.py            FastAPI, CORS, lifespan (DB + Redis + bot)
    config.py          pydantic-settings (.env)
    database.py        async SQLAlchemy (Postgres/asyncpg yoki lokal SQLite)
    models.py          users, payments, bot_chats, sessions, errors, progress, vocabulary
    schemas.py         API sxemalari
    redis_client.py    Redis yoki in-memory fallback, SessionLock, rate-limit
    bot/
      bot.py           hayot sikli: polling (dev) / webhook (prod), buyruqlar menyusi
      handlers.py      /start, /help, umumiy javoblar
      payments.py      /tarif, /mening, chek qabul qilish va admin tasdig'i
      admin.py         admin panel: /admin, /stats, /users, /subs, /pending, /user, /grant
      groups.py        guruh/kanal (Max): mention/reply repetitor
    gemini/
      client.py        Live config (VAD, ovoz, transkripsiya, tools) + model fallback
      session.py       AdamBridge: client WS <-> Gemini (upstream/downstream/watchdog)
      text.py          matn modeli (guruh, kanal darslari, chek tahlili)
      tools.py         log_error, update_scores, record_vocabulary, suggest_level
      prompt.py        ADAM_SYSTEM_PROMPT + dinamik context
    lessons/catalog.py darslar katalogi
    services/
      level.py         gibrid CEFR algoritmi
      session_service.py  sessiya holati, kontekst, yakunlash (DB)
      billing.py       tariflar, vaqt limiti, tarifni yoqish
      receipts.py      chekni Gemini bilan tahlil qilish va qaror
      admin_stats.py   statistika, foydalanuvchi qidirish, qo'lda tarif
      group_tutor.py   guruh repetitori
      scheduler.py     limit yangilandi xabari, tarif muddati eslatmasi, kanallarga kunlik dars
    api/
      auth.py          initData validatsiya + POST /api/auth
      ws.py            /ws/audio
      progress.py      /api/me, /api/progress, /api/sessions, /api/errors, /api/vocabulary
    utils/audio.py     float32 <-> PCM16
  tests/               59 ta test (auth, ws+lock, audio, tools, session end, lessons, billing, admin)
  Dockerfile, docker-compose.yml, railway.json
frontend/
  netlify.toml                      build, SPA redirect, mikrofon header
  public/worklets/pcm-recorder.js   AudioWorklet (48k -> 16 kHz Int16, 100 ms)
  src/hooks/useAudio.ts             mikrofon + 24 kHz ijro navbati
  src/hooks/useGeminiWS.ts          WS + reconnect (exponential backoff)
  src/hooks/useTelegram.ts          SDK init, tema, haptic, BackButton
  src/store/{sessionStore,userStore}.ts   Zustand
  src/pages/{Onboarding,Home,Session,Lessons,Progress,Plans,Settings}.tsx
  src/components/{MicButton,Transcript,ErrorPanel,LevelBadge,LimitCard,SessionStats,AdamAvatar,...}.tsx
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
| 6 | `test_lessons.py` | darslar katalogi va dars rejimi |
| 7 | `test_billing.py` | tarif limitlari, oyna yangilanishi, tarifni yoqish, chek qarori (summa, karta, sana, dublikat) |
| 8 | `test_admin.py` | foydalanuvchini topish, qo'lda tarif berish/olish, statistika |

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

## Admin panel (bot ichida)

Faqat `ADMIN_IDS` dagi foydalanuvchilarga ishlaydi (shaxsiy chatda). Buyruqlar adminlarning menyusida avtomatik ko'rinadi.

| Buyruq | Vazifasi |
|--------|----------|
| `/admin` | panel tugmalari: Statistika, Foydalanuvchilar, Obunachilar, Tekshiruvda |
| `/stats` | foydalanuvchilar, faollik, sessiyalar/daqiqalar, obunachilar, daromad, darajalar |
| `/users` | oxirgi faol 15 foydalanuvchi → bosilsa karta |
| `/subs` | faol Pro/Max obunachilar va tugash sanasi |
| `/pending` | admin tekshiruvidagi cheklar (Tasdiqlash / Rad etish) |
| `/user <id \| @username \| ism>` | foydalanuvchi kartasi + Pro/Max +7/+30/+90 kun, Free tugmalari |
| `/grant <id \| @username> <pro\|max\|free> [kun]` | tarifni qo'lda berish (standart: `PLAN_DAYS`) |

Tarif berilganda foydalanuvchiga bot xabar yuboradi. Shu tarif amalda bo'lsa, kunlar ustiga qo'shiladi.

## Deploy (amaldagi: Netlify + Railway)

Bitta GitHub repo (monorepo): Railway `backend/`, Netlify `frontend/` papkasini quradi.
`main` ga `git push` qilinganda ikkalasi avtomatik qayta deploy bo'ladi.

| Qism | Platforma | Manzil |
|------|-----------|--------|
| Mini App | Netlify | `https://adamtutor.netlify.app` |
| Backend + bot (webhook) | Railway | `https://adam-ai-production-4edc.up.railway.app` |
| Ma'lumotlar bazasi | Railway PostgreSQL | `${{Postgres.DATABASE_URL}}` |

### 1. Backend — Railway

1. **New Project → Deploy from GitHub repo** → repo'ni tanlang. Repo ko'rinmasa: **Configure GitHub App** → repo'ga ruxsat bering.
2. Servis **Settings → Source → Root Directory** = `backend`. `railway.json` Dockerfile va `/health` healthcheck'ni sozlaydi.
3. **+ Create → Database → PostgreSQL** qo'shing.
4. **Settings → Networking → Generate Domain** (port `8000`).
5. **Variables → Raw Editor**:
   ```env
   TELEGRAM_BOT_TOKEN=...
   GEMINI_API_KEY=...
   RECEIPT_GEMINI_API_KEY=...
   GEMINI_MODEL=gemini-3.8-live
   GEMINI_FALLBACK_MODELS=gemini-2.5-flash-native-audio-preview-12-2025
   GEMINI_VOICE=Puck
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   ENVIRONMENT=production
   ALLOW_DEV_AUTH=false
   FRONTEND_URL=https://<netlify-sayt>.netlify.app
   WEBAPP_URL=https://<netlify-sayt>.netlify.app
   BACKEND_URL=https://<railway-domen>.up.railway.app
   WEBHOOK_SECRET=<uzun tasodifiy satr>
   PAYMENT_CARD_NUMBER=...
   PAYMENT_CARD_HOLDER=...
   ADMIN_IDS=<telegram id, vergul bilan>
   SESSION_TIMEOUT_SECONDS=900
   ```
   `postgres://` manzil avtomatik `postgresql+asyncpg://` ga o'giriladi. Bir nechta instance ishlatsangiz `REDIS_URL` majburiy
   (lock umumiy bo'lishi uchun); bitta instance'da in-memory fallback yetarli.
6. Startup'da webhook avtomatik o'rnatiladi: `BACKEND_URL/telegram/webhook` (secret token bilan), menyu tugmasi `WEBAPP_URL` ga ulanadi.

**WebSocket:** uvicorn `--ws-ping-interval 20` bilan ishlaydi, Railway'da qo'shimcha sozlama shart emas.
Gemini audio sessiyasi 15 daqiqa bilan cheklangan (`SESSION_TIMEOUT_SECONDS=900`).

### 2. Frontend — Netlify

1. **Add new site → Import an existing project → GitHub** → repo'ni tanlang.
2. **Base directory** = `frontend` (build sozlamalari `frontend/netlify.toml` dan olinadi: `npm run build`, `dist`, Node 22).
3. **Site configuration → Environment variables**: `VITE_API_URL=https://<railway-domen>.up.railway.app` (oxirida `/` yo'q).
4. **Deploys → Trigger deploy → Deploy site** — `VITE_API_URL` build vaqtida kodga yoziladi, o'zgartirilsa qayta deploy shart.
5. **Access & security → Visitor access**: sayt himoyasi o'chiq bo'lishi kerak (aks holda Telegram'da 401).

`netlify.toml` SPA redirect, `Permissions-Policy: microphone=(self)` va assets kesh header'larini sozlaydi.

### 3. BotFather

`/mybots` → bot → **Bot Settings → Configure Mini App → Enable Mini App** → Netlify manzili.

### Muhim

- Production ishlayotganda **lokal backend'ni shu bot tokeni bilan ishga tushirmang**: development polling rejimi startup'da
  webhook'ni o'chiradi va Railway'dagi bot xabar olmay qoladi. Lokal sinov uchun alohida test bot tokenidan foydalaning.
- Railway sinov muddati tugashidan oldin **Hobby** tarifiga o'ting, aks holda servis to'xtaydi.

### Yakuniy tekshiruv

1. `https://<backend>/health` → `{"status":"ok"}`
2. Botda `/start` → «🎤 Adam bilan gapirish» tugmasi chiqadi
3. Mini App → mikrofon ruxsati → Adam o'zbekcha salomlashadi
4. Noto'g'ri gap ayting → ErrorPanel'da xato chiqadi
5. «Tugatish» → xulosa; Progress sahifasida statistika saqlangan
6. `/tarif` → Pro → karta raqami chiqadi; admin: `/admin`, `/stats`

## Muhim eslatmalar

- `GEMINI_MODEL` faqat `.env` dan o'qiladi; ulanmasa `GEMINI_FALLBACK_MODELS` ketma-ket sinaladi.
- Audio: 16 kHz kirish / 24 kHz chiqish, PCM 16-bit mono. Audio hech qayerda saqlanmaydi.
- Har WebSocket = yangi Gemini sessiyasi; davomiylik DB + dinamik context orqali ta'minlanadi.
- Qisqa (<60 s) yoki baholanmagan sessiyalar darajaga ta'sir qilmaydi; daraja avtomatik pasaymaydi.
- Spetsifikatsiyaga qo'shilgan ustunlar: `users.level_progress`, `sessions.mode/level_at_start/summary`, `errors.explanation`.
  Jadvallar startup'da `create_all` bilan yaratiladi (mavjud jadvallarga ustun qo'shilmaydi — sxema o'zgarsa migratsiya qiling).
