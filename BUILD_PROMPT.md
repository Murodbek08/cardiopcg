# CardioPCG AI — YAGONA BUILD PROMPT (0 dan 100 gacha)

Sen senior full-stack muhandis va subagentlar rahbarisan. Vazifa: `docs/` dagi TZ bo'yicha CardioPCG AI platformasini TO'LIQ, real (demo emas) qurish, testlash va https://cardiopcgai.189.uz ga joylash. To'xtab savol berma — qarorlarni TZ va shu prompt bo'yicha o'zing qabul qil; faqat TZ'da yo'q va qaytarib bo'lmaydigan narsada so'ra.

## O'qish tartibi (avval hammasini o'qi)
1. docs/00-ARCHITECTURE-DECISIONS.md — qat'iy stack va printsiplar
2. docs/01-BACKEND-DB-API.md — DB, RBAC, endpointlar, job'lar (API HAQIQAT MANBAI)
3. docs/02-AI-PCG-ANALYSIS.md — signal pipeline, DeepSeek, dori moduli
4. docs/03-FRONTEND-UI.md — barcha sahifalar va dizayn tizimi (API yo'llari 01-hujjatga moslansin, nomuvofiqlikda 01 yutadi)
5. docs/04-DEVOPS-SECURITY-QA.md — deploy, xavfsizlik, testlar

## Ish usuli (subagentlar)
Avval repo skeleti + umumiy shartnoma (OpenAPI sxemasi) ni o'zing yarat. Keyin parallel subagentlar (har biri o'z papkasida, fayllar to'qnashmasin):
- A: backend core (auth, RBAC, DB modellar, Alembic, CRUD, audit, upload, WS/SSE)
- B: signal-processing + ML + DeepSeek + dori bilim bazasi (app/ml, app/services/ai)
- C: frontend shell, auth, dizayn tizimi, admin sahifalari
- D: frontend doctor + nurse sahifalari, exam workspace (wavesurfer, spektrogramma, dori paneli)
- E: deploy (Docker, nginx, CI), testlar (pytest, Playwright), seed-dori ma'lumotlari
Har faza oxirida integratsiya: OpenAPI -> TypeScript klient generatsiya, lint, typecheck, testlar yashil bo'lsin.

## Qat'iy qoidalar
- Sirlar (DEEPSEEK_API_KEY, DB/JWT/MinIO parollari) FAQAT serverdagi `.env` da; repoga, loglarga, docs'ga YOZILMAYDI. `.env.example` da faqat placeholder. Foydalanuvchi bergan kalitni user serverga o'zi qo'yadi yoki aniq so'ragandan keyin.
- Production'da demo/seed foydalanuvchi YO'Q; birinchi admin `scripts/create_admin.py` bilan.
- DeepSeek'ga bemor identifikatorlari (ism, telefon, manzil, ID) yuborilmaydi — faqat de-identifikatsiyalangan klinik kontekst.
- Dori tavsiyalari shifokor tasdig'isiz bemorga yakuniy ko'rinmaydi; hamshira AI natijasini o'zgartira olmaydi.
- Frontendda emoji yo'q (Tabler Icons). UI o'zbekcha.
- Fayllar base64 bilan DB'ga yozilmaydi — MinIO/S3.
- Har task oxirida: lint + typecheck + testlar. Yashil bo'lmagan narsani "tayyor" dema.

## Deploy (umumiy server — ehtiyotkorlik)
Server 164.68.111.41 da boshqa jonli loyihalar bor (tiiame, adshare, uzex-agent, migrantlar24...). 04-hujjatdagi 0-qadam RECON (faqat o'qish) ni bajar: band portlar, nginx saytlari, RAM/disk. Compose project nomi `cardiopcg`, o'z tarmoq/volume, CPU/RAM limit, faqat 127.0.0.1:<bo'sh port>. Nginx: avval config zaxirasi, `nginx -t`, keyin reload; boshqa saytlarga tegma; global `docker prune`/restart yo'q. SSH kalit bilan kir (parol kodga/hujjatga yozilmaydi). Deploydan oldin va keyin boshqa saytlar javob berishini tekshir.

## Tugatish mezoni
- 3 rol real login bilan ishlaydi, RBAC testlari o'tgan
- Hamshira: bemor -> audio/rasm yuklash -> yuborish; shifokor: real PCG tahlil (S1/S2, HR, shovqin), DeepSeek izoh + differensial + dori tavsiyasi (o'zaro ta'sir/allergiya tekshiruvi), xulosa + PDF; admin: foydalanuvchilar, audit, sozlamalar, analitika
- Analitika dashboardlari haqiqiy DB ma'lumotidan
- https://cardiopcgai.189.uz HTTPS da ishlaydi, backup cron, healthcheck, boshqa saytlar buzilmagan
- Oxirida hisobot: nima qilindi, nima tekshirildi, ochiq qolgan narsalar (honest), va foydalanuvchiga: chatga yuborilgan server paroli va DeepSeek kalitini ALMASHTIRISH eslatmasi.

## Eslatma (tibbiy)
Tizim qaror qo'llab-quvvatlash vositasi; sertifikatsiyalangan tibbiy qurilma emas. Interfeysda va PDF'da buni ko'rsat.
