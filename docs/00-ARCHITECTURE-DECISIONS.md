# CardioPCG AI — Arxitektura qarorlari (barcha TZ bo'limlari shunga tayanadi)

Maqsad: fonokardiografiya (PCG) tovushlarini to'liq tahlil qiladigan, haqiqiy (demo emas) ko'p rolli tibbiy platforma.
Domen: https://cardiopcgai.189.uz (Cloudflare proxied, A -> 164.68.111.41). Til: UI o'zbekcha (lotin), kodda inglizcha identifikatorlar.

## Rollar (real, DB'da)
admin, doctor (shifokor), nurse (hamshira). Login: username+parol, JWT access (15 daq) + refresh (7 kun, httpOnly cookie, rotation), RBAC, audit log. Demo/seed parollar PRODUCTION'DA YO'Q: birinchi admin `scripts/create_admin.py` orqali yaratiladi.

## Stack (qat'iy)
- Backend: Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async) + Alembic, PostgreSQL 17, Redis 7, Celery (yoki arq) fon vazifalar, uv (paket menejeri), ruff, pytest, structlog.
- Signal: numpy, scipy, librosa, soundfile, neurokit/own segmentatsiya (S1/S2), matplotlib/plotly (spektrogramma PNG), onnxruntime (agar model bo'lsa).
- AI: DeepSeek API (OpenAI-compatible, `https://api.deepseek.com`, model `deepseek-chat` / `deepseek-reasoner`) — KLINIK IZOH, differensial tashxis, dori tavsiyasi. Kalit faqat serverda `.env` (DEEPSEEK_API_KEY), hech qachon kodga/gitga yozilmaydi.
- Fayl saqlash: MinIO (S3) yoki server diskidagi volume; DB'da faqat URL/key (base64 EMAS).
- Frontend: React 19 + TypeScript + Vite + Tailwind CSS 4 + shadcn/ui, TanStack Query 5, TanStack Router (yoki React Router 6), Zustand, react-hook-form + zod, Recharts/ECharts, wavesurfer.js (audio to'lqin), react-i18next (uz asosiy, ru/en keyin), Tabler Icons (emoji YO'Q).
- Realtime: WebSocket/SSE (AI tahlil progressi, yangi tekshiruv bildirishnomasi).
- Deploy: Docker Compose, konteynerlar faqat 127.0.0.1:<port>'da, host nginx + certbot (yoki Cloudflare origin), boshqa loyihalarga (tiiame, adshare, uzex, migrantlar24 va h.k.) TEGILMAYDI.

## Monorepo tuzilmasi
```
cardiopcg/
  docs/            # TZ
  backend/         # FastAPI (app/api, app/core, app/models, app/schemas, app/services, app/ml, app/workers, alembic)
  frontend/        # React (src/app, features/<role>, shared)
  deploy/          # docker-compose.prod.yml, nginx conf, scripts
  .env.example
```

## Tibbiy xavfsizlik printsipi
AI faqat "qaror qo'llab-quvvatlash". Dori tavsiyalari — "ma'lumot uchun, shifokor tasdiqlaydi" belgisi bilan, dozalar va qarshi ko'rsatmalar, allergiya/o'zaro ta'sir tekshiruvi; shifokor tasdiqlamaguncha bemorga "yakuniy" bo'lib ko'rinmaydi. Hamshira AI natijasini o'zgartira olmaydi. Barcha AI chaqiruvlari audit logga yoziladi.
