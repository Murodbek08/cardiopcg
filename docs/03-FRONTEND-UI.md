# 03 — Frontend UI/UX spetsifikatsiyasi (CardioPCG AI)

Bu hujjat `00-ARCHITECTURE-DECISIONS.md` ga tayanadi. Til: matn o'zbekcha (lotin), kod/identifikatorlar inglizcha. Stack: React 19 + TypeScript + Vite + Tailwind CSS 4 + shadcn/ui, TanStack Query 5, React Router 6 (data router), Zustand, react-hook-form + zod, Recharts (oddiy grafiklar) + ECharts (heatmap, gauge), wavesurfer.js (to'lqin), react-i18next, Tabler Icons (`@tabler/icons-react`). Emoji hech qayerda ishlatilmaydi.

Asosiy tamoyil: AI faqat "qaror qo'llab-quvvatlash". Har bir AI natijasi va dori tavsiyasi yonida doimo `AiDisclaimerBadge` ("AI xulosasi - ma'lumot uchun, shifokor tasdiqlaydi") ko'rinadi. Shifokor tasdiqlamaguncha natija "Qoralama" (draft) holatida bo'ladi. Hamshira AI natijasini o'zgartira olmaydi (UI'da tahrirlash tugmalari umuman render qilinmaydi, faqat backend 403 ga tayanilmaydi).

---

## 1. Rolga asoslangan ilova qobig'i (App shells)

Bitta SPA, uchta shell. Login'dan keyin `user.role` bo'yicha `/` -> `/admin`, `/doctor` yoki `/nurse` ga yo'naltiriladi.

```
+------------------------------------------------------------------+
| TopBar: [logo] CardioPCG AI   [global search Ctrl+K]  [bell 3] [theme] [user v] |
+----------+-------------------------------------------------------+
| Sidebar  |  Breadcrumb                                           |
| (role    |  PageHeader (title, actions)                          |
|  menu)   |  -----------------------------------------------     |
|          |  <Outlet/>  (sahifa kontenti)                         |
|          |                                                       |
+----------+-------------------------------------------------------+
```

- `AdminShell`: sidebar to'liq (chap, 264px, yig'iladi 72px). Menyu: Dashboard, Foydalanuvchilar, Audit log, Dorilar bazasi, Hisobotlar, Sozlamalar, Bildirishnomalar.
- `DoctorShell`: sidebar to'liq. Menyu: Dashboard, Bemorlar, Tekshiruvlar, Tasdiqlash navbati (badge soni), Hisobotlar, Bildirishnomalar.
- `NurseShell`: planshet-first. 1024px dan past: sidebar o'rniga pastki `BottomNav` (4 ta katta tugma: Bosh sahifa, Bemorlar, Yangi tekshiruv (markaziy FAB), Bildirishnomalar). Tugmalar min 56px balandlik.
- Barcha shell'lar umumiy: `TopBar`, `UserMenu` (Profil, Parolni o'zgartirish, Til, Mavzu, Chiqish), `NotificationBell`, `OfflineBanner`, `Toaster`, `CommandPalette`.

### 1.1 Route xaritasi

Guard turlari: `Public` (faqat tizimga kirmaganlar), `Auth` (har qanday rol), `Role[...]`.

| Path | Sahifa (component) | Guard |
|---|---|---|
| `/login` | LoginPage | Public |
| `/forgot-password` | ForgotPasswordPage | Public |
| `/reset-password?token=` | ResetPasswordPage | Public |
| `/change-password` | ChangePasswordPage (majburiy yoki ixtiyoriy) | Auth |
| `/profile` | ProfilePage | Auth |
| `/notifications` | NotificationsPage | Auth |
| `/admin` | AdminDashboardPage | Role[admin] |
| `/admin/users` | UsersListPage | Role[admin] |
| `/admin/users/new` | UserCreatePage | Role[admin] |
| `/admin/users/:id` | UserDetailPage (edit, rol, faolsizlantirish, parolni tiklash) | Role[admin] |
| `/admin/audit` | AuditLogPage | Role[admin] |
| `/admin/settings` | SystemSettingsPage | Role[admin] |
| `/admin/drugs` | DrugKbListPage | Role[admin] |
| `/admin/drugs/:id` | DrugKbEditPage | Role[admin] |
| `/admin/reports` | ReportsExportsPage | Role[admin] |
| `/doctor` | DoctorDashboardPage | Role[doctor] |
| `/doctor/review-queue` | ReviewQueuePage | Role[doctor] |
| `/nurse` | NurseDashboardPage | Role[nurse] |
| `/patients` | PatientsListPage | Role[doctor, nurse, admin(read-only)] |
| `/patients/new` | PatientCreatePage | Role[doctor, nurse] |
| `/patients/:id` | PatientDetailPage (tablar: Umumiy, Anamnez, Tekshiruvlar, Trendlar) | Role[doctor, nurse, admin(read-only)] |
| `/patients/:id/edit` | PatientEditPage | Role[doctor, nurse] |
| `/patients/:id/timeline` | PatientTimelinePage (trendlar) | Role[doctor, nurse] |
| `/exams` | ExamsListPage | Role[doctor, nurse, admin(read-only)] |
| `/exams/new?patientId=` | ExamWizardPage | Role[doctor, nurse] |
| `/exams/:id/progress` | ExamProgressPage (live AI) | Role[doctor, nurse] |
| `/exams/:id` | ExamWorkspacePage | Role[doctor, nurse(read-only)] |
| `/exams/:id/report` | ExamReportPrintPage (A4 chop) | Role[doctor, nurse(faqat tasdiqlangan)] |
| `/reports` | ReportsExportsPage (doctor ko'rinishi: faqat o'z ma'lumoti) | Role[doctor] |
| `/403`, `/404`, `/500` | ErrorPages | Public |

Guard amalga oshirilishi: `RequireAuth` (token yo'q -> `/login?next=`), `RequireRole roles={[...]}` (mos emas -> `/403`), `RedirectIfAuthed`. `mustChangePassword=true` bo'lsa barcha yo'llar `/change-password` ga yo'naltiriladi. Ichki ruxsatlar (masalan hamshira uchun tugmalarni yashirish) `usePermission('exam.approve')` hook'i orqali.

Ruxsatlar matritsasi (UI darajasida):

| Amal | admin | doctor | nurse |
|---|---|---|---|
| Foydalanuvchilarni boshqarish | ha | yo'q | yo'q |
| Bemor yaratish/tahrirlash | yo'q | ha | ha |
| Bemor ma'lumotini ko'rish | ha (maskalangan) | ha | ha |
| Tekshiruv yaratish va audio yuklash | yo'q | ha | ha |
| AI natijasini ko'rish | ha | ha | ha (o'qish) |
| Xulosa yozish, dori tasdiqlash | yo'q | ha | yo'q |
| Audit log, sozlamalar, dorilar bazasi | ha | yo'q | yo'q |
| Bemor ma'lumotini eksport | ha | ha (o'z bemorlari) | yo'q |

Admin bemor klinik tafsilotlarini ko'rsa: ism-familiya qisman maskalanadi (`A*** K***`), diagnozlar yashiriladi, faqat statistik ko'rinish (maxfiylik printsipi).

---

## 2. Dizayn tizimi

### 2.1 Ranglar (tibbiy mahsulot: ishonch, sokinlik, aniq holat ranglari)

Asosiy kayfiyat: sovuq teal/ko'k (ishonch), kam to'yingan neytral kulrang, aniq semantik ranglar. Qizil faqat kritik holatlar uchun (alarm charchoqni oldini olish).

Tailwind 4 `@theme` tokenlari (`src/styles/tokens.css`):

```css
@import "tailwindcss";

@theme {
  /* Brand */
  --color-brand-50:  #eefbfb;
  --color-brand-100: #d3f4f4;
  --color-brand-200: #aee8ea;
  --color-brand-300: #78d5da;
  --color-brand-400: #3dbac3;
  --color-brand-500: #209ea9;   /* primary */
  --color-brand-600: #187f8c;
  --color-brand-700: #17666f;
  --color-brand-800: #18535b;
  --color-brand-900: #17454d;

  /* Semantic (light) */
  --color-success-500: #1f9d62;  --color-success-50: #e8f7ef;
  --color-warning-500: #d98a0b;  --color-warning-50: #fdf3e1;
  --color-danger-500:  #d6354b;  --color-danger-50:  #fdecee;
  --color-info-500:    #2f6fdb;  --color-info-50:    #eaf1fd;

  /* Klinik risk shkalasi */
  --color-risk-low:      #1f9d62;
  --color-risk-moderate: #d9a20b;
  --color-risk-high:     #e0662a;
  --color-risk-critical: #d6354b;

  /* Signal / grafik */
  --color-pcg-wave:  #187f8c;
  --color-pcg-s1:    #d6354b;
  --color-pcg-s2:    #2f6fdb;
  --color-pcg-murmur:#d98a0b;

  /* Typography & radius & shadow */
  --font-sans: "Inter Variable", "Inter", system-ui, sans-serif;
  --font-mono: "JetBrains Mono Variable", ui-monospace, monospace;
  --radius-sm: 6px; --radius-md: 10px; --radius-lg: 14px; --radius-xl: 20px;
  --shadow-card: 0 1px 2px rgb(16 24 40 / .06), 0 1px 3px rgb(16 24 40 / .10);
  --shadow-pop:  0 8px 24px rgb(16 24 40 / .14);

  /* Spacing asosi: 4px */
  --spacing: 4px;
}

:root {
  --bg: #f6f8fa;  --surface: #ffffff;  --surface-2: #f0f3f6;
  --border: #dde3ea;  --text: #101828;  --text-muted: #5b6776;
  --ring: var(--color-brand-500);
}
.dark {
  --bg: #0c1218;  --surface: #131b24;  --surface-2: #1a2430;
  --border: #263241;  --text: #e8edf3;  --text-muted: #93a1b3;
  --ring: var(--color-brand-400);
  --color-pcg-wave: #5fd0d9;
  --color-success-50: #0f2a1e; --color-warning-50: #2e2210;
  --color-danger-50: #321419;  --color-info-50: #12233f;
}
```

Light/dark: `class="dark"` `<html>` da; uchta variant: Light / Dark / System (default System). Zustand `useThemeStore`, `localStorage('theme')`. Grafiklar ranglari CSS o'zgaruvchilardan olinadi (`getComputedStyle`), shuning uchun mavzu almashganda qayta chiziladi. Kontrast: matn/fon >= 4.5:1, katta matn va UI chegaralari >= 3:1 (ikkala mavzuda tekshiriladi).

Risk va holat ranglari faqat rangga tayanmaydi: har doim matn yorlig'i + ikonka (Tabler `IconCircleCheck`, `IconAlertTriangle`, `IconAlertOctagon`) bilan birga (rang ko'rligi uchun).

### 2.2 Tipografiya

| Token | O'lcham/qator | Og'irlik | Ishlatilishi |
|---|---|---|---|
| `text-display` | 30/38 | 700 | Dashboard katta raqamlar (KPI) |
| `text-h1` | 24/32 | 650 | Sahifa sarlavhasi |
| `text-h2` | 20/28 | 600 | Bo'lim sarlavhasi |
| `text-h3` | 16/24 | 600 | Karta sarlavhasi |
| `text-body` | 14/22 | 400 | Asosiy matn |
| `text-sm` | 13/20 | 400 | Jadval, yordamchi |
| `text-xs` | 12/16 | 500 | Yorliq, badge |
| `font-mono` | 13/20 | 500 | ID, vaqt, qiymatlar (Hz, ms), doz |

Raqamlar uchun `font-variant-numeric: tabular-nums`. Planshet (hamshira) uchun body 16px, tugma matni 16px.

### 2.3 Oraliq va tartib

4px asosli shkala: 4, 8, 12, 16, 20, 24, 32, 40, 56. Sahifa padding: 24 (desktop), 16 (planshet/mobil). Karta ichki padding 20. Grid: 12 ustun, gap 16/24. Konteyner max-width 1440px. Touch target >= 44x44px (hamshira: >= 56px).

### 2.4 Asosiy komponentlar kutubxonasi (`shared/ui`)

shadcn/ui asosida: `Button` (variant: primary, secondary, ghost, danger; size: sm, md, lg, touch), `Input`, `PasswordInput`, `Select`, `Combobox`, `DatePicker`, `Textarea`, `Checkbox`, `RadioGroup`, `Switch`, `Dialog`, `Sheet` (yon panel), `Tabs`, `Tooltip`, `Popover`, `DropdownMenu`, `DataTable` (TanStack Table), `Pagination`, `Skeleton`, `EmptyState`, `ErrorState`, `Badge`, `StatusPill`, `Stepper`, `Toast` (sonner), `ConfirmDialog`, `FileDropzone`, `KpiCard`, `ChartCard`, `RiskGauge`, `AiDisclaimerBadge`, `PageHeader`, `Breadcrumbs`.

Klinik komponentlar (`shared/clinical`): `PatientAvatar`, `VitalsTile`, `RiskBadge`, `SeverityBadge`, `AgreementBadge`, `DrugInteractionAlert`, `WaveformPlayer`, `SpectrogramView`, `FeatureTable`, `DifferentialList`.

### 2.5 Ikonkalar

Faqat `@tabler/icons-react` (stroke 1.75, o'lcham 20 default, 24 katta). Emoji va unicode pictogramlar taqiqlangan; ESLint qoidasi (`no-restricted-syntax` Unicode emoji regex) CI'da tekshiradi. Namuna: `IconHeartbeat` (logo/PCG), `IconStethoscope`, `IconUserPlus`, `IconUpload`, `IconWaveSine`, `IconBrain`, `IconPill`, `IconFileTypePdf`, `IconBell`, `IconShieldLock`, `IconChartLine`, `IconSun`, `IconMoon`, `IconAlertTriangle`.

---

## 3. Sahifalar spetsifikatsiyasi

Har sahifada: Maqsad, Layout (ASCII), Komponentlar, Data (API), Holatlar, Amallar, Validatsiyalar, Grafiklar. API prefiksi: `/api/v1`. Umumiy holat qoidalari: yuklanayotganda `Skeleton` (spinner emas), bo'sh holatda `EmptyState` (ikonka + tushuntirish + CTA), xatoda `ErrorState` (xabar + "Qayta urinish" + `requestId`).

### 3.1 Login — `/login`

Maqsad: username+parol bilan kirish. Demo hisoblar ko'rsatilmaydi.

```
+--------------------------------------------------------------+
|  [Chap panel: brend, IconHeartbeat, qisqa tavsif]  | [Forma] |
|                                                    |  Tizimga kirish
|  "CardioPCG AI - fonokardiografiya tahlili"        |  [Foydalanuvchi nomi]
|  (faqat >=1024px)                                  |  [Parol        (ko'z)]
|                                                    |  [ ] Eslab qolish (30 daq sessiya)
|                                                    |  [   Kirish   ]
|                                                    |  Parolni unutdingizmi?
+--------------------------------------------------------------+
```

- Komponentlar: `AuthLayout`, `LoginForm`, `PasswordInput`, `Button`, `Alert`.
- Data: `POST /auth/login {username, password}` -> `{accessToken, user{id, role, fullName, mustChangePassword}}`; refresh token httpOnly cookie'da (JS ko'rmaydi). `GET /auth/me` sahifa yangilanganda.
- Holatlar: idle; submitting (tugma `loading`, maydonlar disabled); xato 401 ("Foydalanuvchi nomi yoki parol noto'g'ri" — qaysi biri ekanini aytmaydi); 423 (hisob bloklangan: "N daqiqadan keyin urinib ko'ring"); 429 (juda ko'p urinish); tarmoq xatosi.
- Amallar: Enter bilan yuborish; muvaffaqiyatda `next` parametr yoki rol dashboardi; `mustChangePassword` -> `/change-password`.
- Validatsiya (zod): username 3-32 belgi `[a-z0-9._-]`, majburiy; parol majburiy (login'da murakkablik tekshirilmaydi). Caps Lock ogohlantirishi.
- Grafiklar: yo'q.
- Xavfsizlik: `autocomplete="username"/"current-password"`, parol maydoni xatodan keyin tozalanadi, URLda hech qanday maxfiy ma'lumot yo'q.

### 3.2 Parolni unutdim / tiklash — `/forgot-password`, `/reset-password`

Maqsad: parolni tiklash. Admin yaratgan akkauntlarda email bo'lishi mumkin; email bo'lmasa — "administratorga murojaat qiling" yo'riqnomasi.

```
+----------------------------------+
| <- Kirishga qaytish              |
| Parolni tiklash                  |
| [Foydalanuvchi nomi yoki email]  |
| [ Havola yuborish ]              |
| (yuborilgach) "Agar akkaunt      |
|  mavjud bo'lsa, havola yuborildi"|
+----------------------------------+
```

- Data: `POST /auth/forgot-password {identifier}` (javob doim 202, akkaunt mavjudligini oshkor qilmaydi); `POST /auth/reset-password {token, newPassword}`.
- Holatlar: yuborildi (60 soniya qayta yuborish taymeri); token yaroqsiz/muddati o'tgan -> `ErrorState` + "Yangi havola so'rash"; muvaffaqiyat -> toast + `/login`.
- Validatsiya: parol siyosati (qarang 3.3). Tasdiq paroli mos bo'lishi shart.
- Admin tomonidan tiklash: `UserDetailPage`dan vaqtinchalik parol generatsiya qilinadi (bir marta ko'rsatiladi, `mustChangePassword=true`).

### 3.3 Parolni o'zgartirish — `/change-password`

```
+------------------------------------------+
| Parolni o'zgartirish                     |
| [Joriy parol]                            |
| [Yangi parol]   [kuch indikatori ====- ] |
| [Yangi parolni tasdiqlang]               |
|  Talablar: [v] 12+ belgi [v] katta/kichik|
|  harf [ ] raqam [ ] maxsus belgi         |
| [Bekor qilish]            [Saqlash]      |
+------------------------------------------+
```

- Data: `POST /auth/change-password {currentPassword, newPassword}`; muvaffaqiyatda barcha boshqa sessiyalar bekor qilinadi, foydalanuvchiga xabar.
- Validatsiya: kamida 12 belgi, katta+kichik harf, raqam, maxsus belgi; username va oldingi paroldan farq qilishi; keng tarqalgan parollar ro'yxatiga qarshi (zxcvbn score >= 3). Tasdiq mos bo'lishi.
- Holatlar: majburiy rejim (birinchi kirish) — "Bekor qilish" yo'q, sidebar yashirin; xato 400 `wrong_current_password`.

### 3.4 Profil — `/profile`

Maqsad: o'z ma'lumotlari (ism, telefon, til, mavzu), faol sessiyalar ro'yxati va "Boshqa sessiyalardan chiqish".
Data: `GET/PATCH /users/me`, `GET /auth/sessions`, `DELETE /auth/sessions/:id`. Validatsiya: ism 2-80, telefon `+998XXXXXXXXX`.

---

### 3.5 Admin dashboard — `/admin`

Maqsad: tizim holati, foydalanish va sifat ko'rsatkichlari. Davr filtri: Bugun / 7 kun / 30 kun / 90 kun / Maxsus (`DateRangePicker`), URLda saqlanadi (`?range=30d`).

```
+---------------------------------------------------------------------+
| Dashboard                         [Davr: 30 kun v] [Yangilash] [Eksport]
+---------------------------------------------------------------------+
| KPI: [Jami tekshiruv] [Faol foydalanuvchi] [AI o'rtacha vaqt] [Xatolik %] |
| KPI: [DeepSeek holati] [Navbatdagi vazifalar] [Disk/MinIO] [Audit hodisa] |
+----------------------------------+----------------------------------+
| Tekshiruvlar vaqt qatori (line,  | Rol bo'yicha foydalanuvchilar    |
| kunlik, AI vs tasdiqlangan)      | (donut)                          |
+----------------------------------+----------------------------------+
| AI-shifokor mosligi (gauge+trend)| Anomaliya ulushi: yosh x jins    |
|                                  | (grouped bar)                    |
+----------------------------------+----------------------------------+
| Faollik heatmap (hafta kuni x soat) | Ish yuklamasi: shifokorlar (bar) |
+----------------------------------+----------------------------------+
| Oxirgi xatolar (AI/ASR/queue)  | Oxirgi audit hodisalari (5 qator)  |
+---------------------------------------------------------------------+
```

- Komponentlar: `KpiCard` (qiymat, o'zgarish %, sparkline), `ChartCard` (sarlavha, tooltip-izoh, eksport PNG/CSV menyusi), `SystemHealthCard`, `RecentErrorsTable`, `RecentAuditList`.
- Data: `GET /analytics/admin/summary?from&to` (KPI), `GET /analytics/exams/timeseries?granularity=day`, `GET /analytics/users/by-role`, `GET /analytics/agreement`, `GET /analytics/abnormal-rate?groupBy=age,gender`, `GET /analytics/activity-heatmap`, `GET /analytics/workload?role=doctor`, `GET /system/health` (DeepSeek, Redis, DB, worker, storage), `GET /audit?limit=5`. Realtime: SSE `GET /events/stream` orqali KPI yangilanishi (60 s fallback polling `refetchInterval`).
- Holatlar: har bir karta mustaqil yuklanadi (`useQuery` per card, `Suspense`+`Skeleton`), bittasi xato bo'lsa faqat u karta `ErrorState` ko'rsatadi; ma'lumot yo'q -> "Tanlangan davrda ma'lumot yo'q".
- Amallar: davrni o'zgartirish, kartani to'liq ekran (`Dialog`), PNG/CSV yuklash, KPI bosilganda tegishli ro'yxatga o'tish (masalan "Xatolik %" -> audit log filtrlangan).
- Validatsiya: maxsus davr 1-365 kun, `from <= to`.
- Grafiklar: yuqorida ko'rsatilgan 8 ta (line, donut, gauge, grouped bar, heatmap, horizontal bar, sparkline). Heatmap rangi bitta rang shkalasi (brand-100 -> brand-700), legend bilan; tooltip'da aniq son.

### 3.6 Shifokor dashboard — `/doctor`

Maqsad: "Bugun nima qilishim kerak" + o'z faoliyati tahlili.

```
+---------------------------------------------------------------------+
| Salom, Dr. {fullName}                    [Davr v]  [+ Yangi tekshiruv]
+---------------------------------------------------------------------+
| KPI: [Tasdiqlash kutilmoqda 7] [Bugun ko'rilgan 12] [Kritik holat 2] [O'rtacha javob vaqti 18 daq] |
+--------------------------------+------------------------------------+
| TASDIQLASH NAVBATI (ro'yxat,   | Mening tekshiruvlarim vaqt qatori  |
| risk bo'yicha saralangan,      | (line: yangi vs tasdiqlangan)      |
| kritik birinchi)               |                                    |
+--------------------------------+------------------------------------+
| AI vs men mosligi (donut:      | Aniqlangan patologiyalar taqsimoti |
| mos/qisman/mos emas) + trend   | (horizontal bar, top 8)            |
+--------------------------------+------------------------------------+
| Anomaliya ulushi: yosh x jins  | Bemorlar risk taqsimoti (donut)    |
| (grouped bar)                  |                                    |
+--------------------------------+------------------------------------+
| Haftalik ish yuklamasi (heatmap: kun x soat)  | Oxirgi bemorlar (5)  |
+---------------------------------------------------------------------+
```

- Komponentlar: `ReviewQueueCard` (har qator: bemor, yosh/jins, risk badge, AI asosiy gipoteza, kutish vaqti, "Ochish"), `AgreementDonut`, `PathologyBar`, `AbnormalByDemographics`, `WorkloadHeatmap`, `RecentPatients`.
- Data: `GET /analytics/doctor/summary`, `GET /exams?status=pending_review&sort=risk_desc&limit=8`, `GET /analytics/exams/timeseries?scope=me`, `GET /analytics/agreement?scope=me`, `GET /analytics/pathologies?scope=me`, `GET /analytics/abnormal-rate?groupBy=age,gender&scope=me`, `GET /analytics/activity-heatmap?scope=me`.
- Holatlar: navbat bo'sh -> "Barcha tekshiruvlar ko'rib chiqilgan" (IconCircleCheck); kritik bor -> yuqorida qizil `Alert` ("2 ta kritik tekshiruv 1 soatdan ortiq kutmoqda").
- Amallar: navbatdan to'g'ridan-to'g'ri workspace'ni ochish; "Keyingisi" (navbat bo'yicha ketma-ket ko'rib chiqish rejimi, klaviatura: `N`).
- Validatsiya: davr filtri.
- Agreement ta'rifi tooltip'da: "Mos = shifokorning yakuniy tashxisi AI top-1 gipotezasi bilan mos".

### 3.7 Hamshira dashboard — `/nurse`

Maqsad: tez ish; katta tugmalar, minimal analitika. Planshet landshaft/portret.

```
+---------------------------------------------------+
| Bosh sahifa                         [Davr: Bugun v]|
| [   + YANGI TEKSHIRUV (katta tugma, 72px)   ]     |
| [ Bemor qidirish (katta input, skaner/ID)    ]    |
+----------------------+----------------------------+
| KPI: [Bugun 9]  [Jarayonda 2] [Qayta yozish kerak 1] [Navbat 3]  |
+----------------------+----------------------------+
| BUGUNGI TEKSHIRUVLAR (kartalar ro'yxati:          |
|  vaqt, bemor, holat: Yuklanmoqda / AI tahlilda /  |
|  Shifokor kutilmoqda / Tasdiqlangan)              |
+---------------------------------------------------+
| Haftalik tekshiruvlar (bar)  | Audio sifati       |
|                              | (donut: yaxshi/past)|
+---------------------------------------------------+
```

- Komponentlar: `PrimaryActionButton`, `PatientQuickSearch`, `TodayExamCard`, `StatusPill`, `QualityDonut`.
- Data: `GET /analytics/nurse/summary`, `GET /exams?createdBy=me&date=today`, `GET /patients?q=`, `GET /analytics/exams/timeseries?scope=me`, `GET /analytics/audio-quality?scope=me`.
- Holatlar: bugun bo'sh -> "Bugun hali tekshiruv yo'q" + CTA; "Qayta yozish kerak" kartasi (sifat past bo'lgan audio) sariq, bosilganda tegishli tekshiruvga.
- Amallar: yangi tekshiruv (wizard), bemor qidirish, kartani ochish (read-only workspace).
- Hamshira dashboardida klinik tashxis/risk raqamlari ko'rsatilmaydi (faqat holat va sifat); risk faqat shifokor tasdiqlagandan keyin workspace'da ko'rinadi (hamshira o'qish rejimida).

---

### 3.8 Bemorlar ro'yxati — `/patients`

Maqsad: bemorlarni qidirish, filtrlash, ochish.

```
+---------------------------------------------------------------------+
| Bemorlar (1 248)                              [+ Yangi bemor] [Eksport v]
| [Qidiruv: ism / ID / telefon] [Jins v] [Yosh dan-gacha] [Risk v] [Yorliq v] [Tozalash]
+---------------------------------------------------------------------+
| [] | ID      | F.I.Sh.        | Yosh/Jins | Oxirgi tekshiruv | Risk  | Holat | ... |
| [] | P-00231 | Karimov A.     | 54 / E    | 2026-11-12       | O'rta | Ochiq  | [..]|
+---------------------------------------------------------------------+
| < 1 2 3 ... >           Sahifada: [25 v]                             |
+---------------------------------------------------------------------+
```

- Komponentlar: `DataTable` (server-side sort/filter/pagination), `FilterBar`, `RiskBadge`, `RowActionsMenu`, `BulkBar` (faqat doctor: eksport).
- Data: `GET /patients?q&gender&ageMin&ageMax&risk&tag&sort&page&pageSize`, `GET /patients/export` (doctor). Filtrlar URL query'da (ulashish/orqaga qaytish uchun). Qidiruv 300 ms debounce, `keepPreviousData`.
- Holatlar: yuklanish — 8 skeleton qator; bo'sh (umuman bemor yo'q) -> "Hali bemor yo'q" + "Yangi bemor"; bo'sh (filtr natijasi) -> "Mos bemor topilmadi" + "Filtrlarni tozalash"; xato -> `ErrorState`.
- Amallar: qator bosilsa detail; "Yangi tekshiruv" tez tugmasi qatorda; eksport CSV (doctor); saralash (ism, yosh, oxirgi tekshiruv, risk).
- Validatsiya: yosh oralig'i 0-120, `ageMin <= ageMax`.
- Planshet: jadval kartalar ro'yxatiga aylanadi (<768px) yoki gorizontal scroll yo'q, ustunlar kamayadi (ID, F.I.Sh., Oxirgi tekshiruv).

### 3.9 Bemor yaratish/tahrirlash — `/patients/new`, `/patients/:id/edit`

Maqsad: bemor kartasi va tibbiy anamnez. Ko'p bo'limli forma, avtosaqlash qoralamasi (`localStorage` draft, 24 soat).

```
+---------------------------------------------------------------------+
| Yangi bemor                                   [Bekor] [Saqlash]     |
+---------------------+-----------------------------------------------+
| Bo'limlar (sticky): | 1. Shaxsiy ma'lumot                           |
|  1 Shaxsiy          |   [Familiya] [Ism] [Otasining ismi]           |
|  2 Aloqa            |   [Tug'ilgan sana] [Jins: E/A] [Qon guruhi v] |
|  3 Antropometriya   | 2. Aloqa                                      |
|  4 Anamnez          |   [Telefon] [Manzil] [Favqulodda aloqa]       |
|  5 Dorilar/Allergiya| 3. Antropometriya                             |
|  6 Rozilik          |   [Bo'y sm] [Vazn kg] [BMI (avto)]            |
|                     | 4. Anamnez (MedicalHistoryEditor)             |
|                     |   Surunkali kasalliklar: [chip tanlash]       |
|                     |   (gipertoniya, QD, yurak nuqsoni, revmatizm, |
|                     |    yurak yetishmovchiligi, aritmiya, DM, ...) |
|                     |   Oldingi operatsiyalar [qator qo'shish]      |
|                     |   Oilaviy anamnez, chekish, alkogol, faollik  |
|                     | 5. Hozirgi dorilar [dori qidirish+doz+chastota]|
|                     |    Allergiyalar [dori/modda + reaksiya + og'irlik]|
|                     | 6. [ ] Ma'lumotni qayta ishlashga rozilik     |
+---------------------+-----------------------------------------------+
```

- Komponentlar: `PatientForm` (react-hook-form + zod), `SectionNav` (scroll-spy), `MedicalHistoryEditor`, `ConditionChips` (ICD-10 qidiruv bilan), `MedicationListEditor` (dori bazasidan autocomplete), `AllergyEditor`, `BmiField` (hisoblanadigan, disabled), `ConsentCheckbox`, `UnsavedChangesGuard`.
- Data: `POST /patients`, `GET/PUT /patients/:id`, `GET /drugs/search?q=` (autocomplete), `GET /icd10/search?q=`, dublikat tekshiruv `GET /patients/duplicates?lastName&birthDate`.
- Holatlar: edit rejimi yuklanishida forma skeleton; saqlash paytida tugma loading; server validatsiya xatosi 422 -> maydon ostida; dublikat topilsa `Dialog` ("Shunga o'xshash bemor bor: ... Baribir yaratish / Mavjudini ochish"); chiqishda saqlanmagan o'zgarishlar ogohlantirishi.
- Amallar: saqlash -> bemor detaliga; "Saqlash va tekshiruv boshlash" (wizard'ga `patientId` bilan); bemorni arxivlash (faqat doctor, `ConfirmDialog`; o'chirish yo'q — soft delete).
- Validatsiya (zod): familiya/ism 2-60 harf; tug'ilgan sana o'tmishda va yosh <= 120; jins majburiy; telefon `+998` + 9 raqam; bo'y 30-250 sm; vazn 1-400 kg; allergiya bo'lsa modda nomi majburiy; doz musbat son + birlik; rozilik majburiy (yaratishda).
- Grafiklar: yo'q (BMI indikator rangli shkala).

### 3.10 Bemor detali — `/patients/:id`

Maqsad: bemor bo'yicha yagona ko'rinish.

```
+---------------------------------------------------------------------+
| <- Bemorlar / Karimov Aziz (54, E)  [Tahrirlash] [+ Yangi tekshiruv]|
| P-00231 | Qon: A(II)+ | BMI 27.4 | Allergiya: [Penitsillin] [..]    |
+---------------------------------------------------------------------+
| [Umumiy] [Anamnez] [Tekshiruvlar (8)] [Trendlar] [Fayllar]          |
+---------------------------------------------------------------------+
| UMUMIY:                                                              |
| +--------------------+ +---------------------+ +------------------+ |
| | Oxirgi tekshiruv   | | Joriy risk (gauge)  | | Faol dorilar     | |
| | sana, xulosa       | | + o'zgarish strelka | | ro'yxati         | |
| +--------------------+ +---------------------+ +------------------+ |
| Mini-timeline (oxirgi 5 hodisa)   | Eslatmalar (shifokor)           |
+---------------------------------------------------------------------+
```

- Komponentlar: `PatientHeader` (sticky, allergiya doim ko'rinadi), `Tabs`, `LastExamSummary`, `RiskGauge`, `ActiveMedicationsList`, `MedicalHistoryView`, `ExamsTable`, `NotesPanel` (faqat doctor yozadi).
- Data: `GET /patients/:id`, `GET /patients/:id/exams`, `GET /patients/:id/summary`, `GET /patients/:id/notes`, `POST /patients/:id/notes`. Tab'lar lazy (`React.lazy` + prefetch on hover).
- Holatlar: 404 -> "Bemor topilmadi"; tekshiruvlar yo'q -> EmptyState + "Birinchi tekshiruvni boshlash"; arxivlangan bemor -> banner, tahrirlash o'chirilgan.
- Amallar: tahrirlash, yangi tekshiruv, tekshiruvni ochish, eslatma qo'shish (doctor), bemor hisobotini PDF qilish (doctor), arxivlash (doctor).
- Admin ko'rinishida shaxsiy ma'lumotlar maskalangan, tab'lar: faqat Umumiy (statistik).

### 3.11 Bemor timeline / trendlar — `/patients/:id/timeline`

Maqsad: tekshiruvlar bo'yicha dinamikani ko'rish (yomonlashish/yaxshilanish).

```
+---------------------------------------------------------------------+
| Karimov A. — Trendlar            [Davr: 12 oy v] [Ko'rsatkichlar v] |
+---------------------------------------------------------------------+
| Risk balli (line, 0-100, zonalar fon rangida: past/o'rta/yuqori)    |
| ---o------o----------o-------o---  (nuqta bosilsa -> tekshiruv)    |
+---------------------------------------------------------------------+
| Shovqin darajasi (grade 0-6) bar | S1/S2 amplituda nisbati (line)   |
+---------------------------------------------------------------------+
| Yurak urish chastotasi (line)    | Qon bosimi sistolik/diastolik    |
+---------------------------------------------------------------------+
| TIMELINE (vertikal):                                                 |
|  12-nov  Tekshiruv #8   [Risk: O'rta]  Dr. Aliyev  [Ochish]         |
|  03-sep  Dori o'zgardi: Metoprolol 50 -> 100 mg                      |
|  ...                                                                  |
+---------------------------------------------------------------------+
| Taqqoslash: [Tekshiruv A v] vs [Tekshiruv B v]  -> yonma-yon waveform|
+---------------------------------------------------------------------+
```

- Komponentlar: `TrendChart` (Recharts `ComposedChart`, `ReferenceArea` zonalar), `MetricPicker`, `ExamTimeline`, `ExamCompare` (ikki `WaveformPlayer` sinxron), `ChangeBadge` (delta).
- Data: `GET /patients/:id/trends?metrics=risk,murmurGrade,hr,bpSys,bpDia,s1s2Ratio&from&to`, `GET /patients/:id/timeline`.
- Holatlar: < 2 tekshiruv bo'lsa "Trend uchun kamida 2 ta tekshiruv kerak" (yagona nuqta ko'rsatiladi); metrika yo'q bo'lsa uzilgan chiziq (gap), nolga tushirilmaydi.
- Amallar: nuqta -> tekshiruv; davr/ko'rsatkich tanlash; ikki tekshiruvni taqqoslash; PNG eksport.
- Grafiklar: line (risk), bar (shovqin darajasi), line (vitals), ReferenceArea zonalar, timeline.

---

### 3.12 Tekshiruvlar ro'yxati — `/exams`

Maqsad: barcha tekshiruvlarni holat bo'yicha ko'rish.

- Layout: `/patients` ga o'xshash; tepada holat tablari: `Hammasi | Yuklanmoqda | AI tahlilda | Shifokor kutilmoqda | Tasdiqlangan | Xato`.
- Ustunlar: ID, bemor, sana, kim yaratgan, holat (`StatusPill`), AI risk (doctor/admin uchun), mosligi, amallar.
- Data: `GET /exams?status&patientId&createdBy&from&to&risk&sort&page`.
- Holatlar/Amallar: bo'sh, xato — umumiy; "Xato" holatidagi qatorda "Qayta tahlil" (`POST /exams/:id/reanalyze`, doctor/nurse yaratgan); ochish; PDF (tasdiqlangan).
- Realtime: ro'yxatdagi `analyzing` holatdagi qatorlar SSE orqali yangilanadi.

### 3.13 Tekshiruv yaratish wizard — `/exams/new`

Maqsad: bemor tanlash, vitals, audio/rasm yuklash, sifat tekshiruvi, yuborish. 4 qadam; planshetda to'liq ekran, katta tugmalar.

```
+---------------------------------------------------------------------+
| Yangi tekshiruv       (1)Bemor --(2)Vitals --(3)Yozuv --(4)Tasdiq   |
+---------------------------------------------------------------------+
| QADAM 1: Bemor                                                       |
|  [Qidirish...]   [+ Yangi bemor (modal)]                             |
|  Tanlangan: Karimov A., 54, E   Allergiya: Penitsillin  [O'zgartirish]|
|  Shikoyatlar (chip + erkin matn): [nafas qisilishi][yurak urishi] ...|
+---------------------------------------------------------------------+
| QADAM 2: Vitals                                                      |
|  [Sistolik] [Diastolik] [Puls] [SpO2 %] [Harorat] [Nafas soni]       |
|  [Vazn] [Bo'y]   Oraliq tashqarida bo'lsa sariq belgi                |
+---------------------------------------------------------------------+
| QADAM 3: Yozuv / yuklash                                             |
|  Auskultatsiya nuqtasi: (o) Aortal (o) Pulmonal (o) Trikuspid (o) Mitral |
|  +-------------- FileDropzone / [Mikrofondan yozish] --------------+ |
|  |  .wav .mp3 .m4a .flac  <= 50 MB, 5-60 s                        | |
|  +-----------------------------------------------------------------+ |
|  Waveform preview [play]  ====/\/\==/\/\==  00:12 / 00:15           |
|  Sifat tekshiruvi: Davomiylik OK | Shovqin: O'rta | Klipping: Yo'q   |
|    | Signal/shovqin 14 dB | Yurak urishi aniqlandi: 72 bpm          |
|  Qo'shimcha rasm (EKG/exo, ixtiyoriy): [yuklash] .png .jpg .pdf     |
+---------------------------------------------------------------------+
| QADAM 4: Tasdiq: xulosa (bemor, vitals, fayllar, sifat)             |
|  [ ] Bemor ma'lumotni yuborishga rozi    [Orqaga]  [Tahlilni boshlash]|
+---------------------------------------------------------------------+
```

- Komponentlar: `Stepper`, `PatientPicker`, `ComplaintsInput`, `VitalsForm`, `AuscultationSitePicker` (yurak sxemasi SVG, 4 nuqta bosiladi), `AudioUploader`, `AudioRecorder` (MediaRecorder, faqat HTTPS), `WaveformPreview` (wavesurfer, `RegionsPlugin` yo'q), `QualityCheckPanel`, `ImageUploader`, `WizardSummary`.
- Data: `POST /exams` (draft yaratadi -> `examId`), `PUT /exams/:id/vitals`, `POST /exams/:id/files` (multipart, `onUploadProgress` bilan progress; yoki presigned URL: `POST /uploads/presign` -> S3 PUT -> `POST /exams/:id/files/confirm`), `POST /exams/:id/quality-check` (server tomonida SNR, clipping, davomiylik, bpm) — frontend lokal tezkor tekshiruv (davomiylik, format, hajm) ham bajaradi (`AudioContext.decodeAudioData`), `POST /exams/:id/submit`. Draft avtomatik saqlanadi (`PUT /exams/:id`), brauzer yopilsa `Davom ettirish` taklifi.
- Holatlar: yuklash progress (foiz, bekor qilish); format/hajm xatosi; sifat past -> sariq/qizil panel va "Qayta yozish" tavsiyasi; "Baribir yuborish" faqat sifat "past" (qizil emas) bo'lsa va sabab belgilansa; sifat "yaroqsiz" (juda qisqa, jim, to'liq shovqin) bo'lsa yuborish bloklanadi; tarmoq uzilsa — qayta urinish (chunklar bilan resumable, 5 MB chunk); mikrofon ruxsati rad etildi -> yo'riqnoma.
- Amallar: qadamlar orasida Orqaga/Keyingi (validatsiya o'tmaguncha Keyingi disabled); bir nechta audio (har nuqta uchun bittadan, maksimum 4); `Tahlilni boshlash` -> `/exams/:id/progress`.
- Validatsiya: bemor majburiy; sistolik 50-260, diastolik 30-160 (sistolik > diastolik), puls 20-250, SpO2 50-100, harorat 30-43, nafas soni 5-60 (chegaradan tashqari = "tasdiqlang" ogohlantirishi, bloklanmaydi, chunki real klinik qiymatlar bo'lishi mumkin); audio: format `wav/mp3/m4a/flac`, <= 50 MB, davomiylik 5-60 s (tavsiya >= 10 s), kamida 1 ta audio; auskultatsiya nuqtasi majburiy; tasdiq checkbox majburiy.
- Grafiklar: waveform preview, sifat indikatorlari (progress barlar).

### 3.14 Live AI tahlil progressi — `/exams/:id/progress`

Maqsad: tahlil bosqichlarini real vaqtda ko'rsatish.

```
+---------------------------------------------------------------------+
| Tahlil: Tekshiruv #1042  Karimov A.                                 |
+---------------------------------------------------------------------+
|  [v] 1. Fayl qabul qilindi                          0.4 s           |
|  [v] 2. Signal tozalash (filtr, normallashtirish)   1.1 s           |
|  [>] 3. S1/S2 segmentatsiya                         ........  62%   |
|  [ ] 4. Xususiyatlar ajratish (spektr, shovqin, HRV)                |
|  [ ] 5. Model bashorati (anomaliya, shovqin turi)                   |
|  [ ] 6. Klinik izoh va differensial tashxis (DeepSeek)              |
|  [ ] 7. Dori tavsiyasi va o'zaro ta'sir tekshiruvi                  |
|  Umumiy: [=========-----------]  48%     Taxminiy: ~25 s qoldi      |
|  Jonli jurnal (qisqa): "Segmentatsiya: 14 sikl topildi"             |
|  [Bekor qilish]            (tugagach avtomatik workspace'ga o'tadi) |
+---------------------------------------------------------------------+
```

- Komponentlar: `PipelineStepper` (vertikal), `ProgressBar`, `LiveLog` (aria-live="polite"), `EtaEstimate`.
- Data: SSE `GET /exams/:id/events` (`event: step`, `data: {step, status, pct, message}`), fallback polling `GET /exams/:id/status` har 2 s (SSE uzilsa avtomatik); `POST /exams/:id/cancel`.
- Holatlar: navbatda ("Navbatda: 3-o'rin"); bosqich xatosi (qizil, sabab, "Qayta urinish" va "Tahlilsiz saqlash"); DeepSeek vaqtincha ishlamayapti -> bosqich 6/7 "o'tkazib yuborildi" ogohlantirishi bilan qisman natija (signal tahlili ko'rinadi, klinik izoh keyin avtomatik qo'shiladi); tugadi -> 1.5 s dan keyin workspace'ga o'tish; sahifa yangilansa holat serverdan tiklanadi.
- Amallar: bekor qilish (`ConfirmDialog`), orqaga (fon rejimida tahlil davom etadi; bildirishnoma keladi).
- Validatsiya: yo'q. Grafiklar: progress.

### 3.15 Tekshiruv workspace — `/exams/:id`

Maqsad: asosiy klinik ish joyi. Shifokor tahlil qiladi, xulosa yozadi, dorilarni tasdiqlaydi; hamshira o'qish rejimida.

```
+---------------------------------------------------------------------------+
| <- Karimov A., 54 E | Tekshiruv #1042 | 12-nov 10:42 | Mitral nuqta       |
| [Holat: Shifokor kutilmoqda]  Risk: [O'RTA 58]  [AI xulosasi - ma'lumot uchun] |
| Vitals: BP 142/90 | HR 84 | SpO2 96 | T 36.8      Allergiya: Penitsillin  |
+------------------------------------------+--------------------------------+
| SIGNAL                                   | AI TAHLIL (o'ng panel, tablar) |
| Waveform (wavesurfer) S1 S2 markerlar    | [Xususiyatlar][Differensial]   |
|  |S1| |S2|  |S1| |S2| ...  (qizil/ko'k) |  [Dori][Tarix]                 |
|  [<<][play][>>] 0.5x 1x 2x  [zoom -- +]  |                                |
|  Qatlamlar: [x] S1/S2 [x] Shovqin zonasi |  Risk gauge (0-100)            |
|             [ ] Sikl chegaralari         |  Asosiy gipoteza + ishonch     |
| Spektrogramma (mel/STFT, vaqt sinxron)   |  ...                           |
|  kursor chizig'i waveform bilan bog'liq  |                                |
| Sikl tanlash: [1][2][3]... -> zoom       |                                |
+------------------------------------------+--------------------------------+
| SHIFOKOR XULOSASI (faqat doctor)                                          |
|  [Xulosa matni (rich text)] [Tashxis ICD-10 qidirish] [Tavsiyalar]        |
|  Dorilar: jadval (tasdiqlash/tahrirlash)                                  |
|  [Qoralama saqlash] [Rad etish va qayta tahlil] [Tasdiqlash va imzolash]  |
+---------------------------------------------------------------------------+
```

Tablar (o'ng panel):

1. **Xususiyatlar (`FeatureTable`)**: jadval — Xususiyat, Qiymat, Birlik, Me'yor oralig'i, Holat (normal/chetlangan ikonka+rang), izoh tooltip. Guruhlar: Vaqt (HR, S1-S2 oralig'i, sistola/diastola davomiyligi, HRV), Amplituda (S1/S2 nisbati), Spektr (dominant chastota, spektral markaz, energiya diapazonlari), Shovqin (grade 0-6, joylashuvi: sistolik/diastolik, shakl: crescendo-decrescendo/pansistolik), Qo'shimcha tovushlar (S3, S4, klik). Qator bosilsa waveform'da tegishli joy highlight bo'ladi.
2. **Differensial tashxis (`DifferentialList`)**: har gipoteza kartasi: nomi (ICD-10), ehtimollik (progress bar, foiz), "qo'llab-quvvatlovchi" va "qarshi" dalillar (xususiyatlarga havola), tavsiya etilgan qo'shimcha tekshiruvlar (exo-KG, EKG). Tartib: ehtimollik kamayishi; DeepSeek tushuntirishi qisqartirilgan, "Batafsil" kengaytiradi. Har kartada `AiDisclaimerBadge`.
3. **Dori tavsiyasi (`DrugRecommendationPanel`)**: pastda batafsil.
4. **Tarix**: oldingi tekshiruvlar bilan solishtirish (mini trend), xulosa o'zgarishlari (versiyalar).

Risk gauge (`RiskGauge`): yarim doira 0-100, to'rt zona (past/o'rta/yuqori/kritik) rangi + matn yorlig'i, markazda raqam; ostida "Ishonch oralig'i" va "Risk omillari" (top 3 ta, vazn bilan).

Dori tavsiyasi paneli:

```
+----------------------------------------------------------------+
| DORI TAVSIYALARI     [AI tavsiyasi - ma'lumot uchun, shifokor tasdiqlaydi] |
| [!] OGOHLANTIRISH: Penitsillin allergiyasi — Amoksitsillin    |
|     tavsiyadan chiqarildi (bemor allergiyasi)                 |
+----------------------------------------------------------------+
| Dori          | Doza/Chastota   | Davomiyligi| Holat   | Amal  |
| Metoprolol    | 50 mg 2 r/kun   | 30 kun     | Taklif  |[Qabul][Tahrir][Rad]|
|   o'zaro ta'sir: [Sariq] Verapamil bilan -> bradikardiya xavfi [batafsil]|
|   qarshi ko'rsatma: AV blok II-III; astma (bemorda: yo'q)      |
|   yon ta'sirlar: ...   Manba: Dorilar bazasi v12 (2026-10)     |
+----------------------------------------------------------------+
| Joriy dorilar bilan o'zaro ta'sir matritsasi (qisqa jadval)    |
| [+ Qo'lda dori qo'shish]                                        |
+----------------------------------------------------------------+
```

- Har dori kartasi: nomi, farmakologik guruh, doza (bemor yoshi/vazni/buyrak funksiyasiga moslangan, "AI taklifi"), qarshi ko'rsatmalar, yon ta'sirlar, o'zaro ta'sir darajasi (`DrugInteractionAlert`: `minor` ko'k, `moderate` sariq, `major` to'q sariq, `contraindicated` qizil — rang + ikonka + matn).
- Xavfsizlik qoidalari UI'da: qizil (`contraindicated`) o'zaro ta'sirda "Qabul qilish" tugmasi bloklanadi, faqat "Baribir qabul qilish (sabab yozing)" — majburiy sabab matni + audit logga yoziladi; allergiya mos kelsa dori ro'yxatga umuman qo'yilmaydi, ogohlantirishda ko'rsatiladi; nurse'da bu panel faqat tasdiqlangan holatdagi ro'yxatni o'qiydi.
- Dori holatlari: `suggested` -> `accepted` / `edited` / `rejected` -> `final` (imzolangach).
- Bemorga "yakuniy" ko'rinish faqat `approved` bo'lgandan keyin: PDF hisobotda draft dori ro'yxati chiqmaydi.

Shifokor xulosasi bloki:

- Maydonlar: `conclusionText` (rich text, minimal toolbar: qalin, ro'yxat), `finalDiagnoses[]` (ICD-10 combobox, ko'p tanlov, "AI gipotezasiga mos" belgisi avtomatik hisoblanadi -> agreement), `recommendations`, `followUpDate`, `urgency` (rejali / 1 hafta / shoshilinch).
- Tugmalar: `Qoralama saqlash` (avtosaqlash 10 s), `Tasdiqlash va imzolash` (`ConfirmDialog`: "Tasdiqlaganingizdan so'ng o'zgartirish faqat yangi versiya sifatida mumkin"), `Qayta tahlil` (parametrlarni o'zgartirib: shovqin filtri, boshqa model), `Chop etish / PDF`.
- Tasdiqlashdan keyin: holat `approved`, tahrir qulflanadi; "Tuzatish kiritish" -> yangi versiya (v2), eski versiya tarixda saqlanadi; hamshira va bemor kartasiga bildirishnoma.

Waveform/spektrogramma tafsilotlari:

- `WaveformPlayer`: `wavesurfer.js` v7 + `RegionsPlugin` (S1/S2 va sikl regionlari), `TimelinePlugin`, `ZoomPlugin`. Markerlar server `segments[]` (`{type: 'S1'|'S2'|'murmur', start, end, cycleIdx}`) dan chiziladi; S1 qizil, S2 ko'k, shovqin sariq yarim shaffof; legend va markerlar uchun ikonka/yorliq (rangga tayanmaydi). Marker ustiga hover: vaqt, davomiylik, amplituda. Doctor markerlarni sudrab tuzatishi mumkin (`resize/drag`) -> `PATCH /exams/:id/segments` (versiyalanadi, "Qo'lda tuzatilgan" belgisi), hamshira uchun regionlar `drag:false`.
- Audio: `GET /exams/:id/files/:fileId/stream` (Range qo'llab-quvvatlaydi, qisqa muddatli signed URL), waveform peaks oldindan serverdan (`GET .../peaks` JSON) -> katta faylni to'liq yuklamasdan chizish.
- Pleyer boshqaruvi: play/pause (Space), +-1 s (strelkalar), tezlik 0.25x-2x, loop (tanlangan sikl yoki region), zoom (slider va `+`/`-`), `M` marker rejimi, balandlik.
- `SpectrogramView`: server PNG (`GET .../spectrogram?type=mel`) yoki `<canvas>` (STFT, `useSpectrogramWorker` Web Worker'da); vaqt o'qi waveform bilan sinxron (bir xil zoom/scroll), chastota o'qi 0-1000 Hz (log/linear almashtirgich), colormap: `viridis` (ko'rlikka mos) + kontrast slider. Kursor chizig'i ikkalasida bir vaqtda.
- Holatlar: audio yuklanmoqda (waveform skeleton); audio xatosi (`ErrorState` + qayta urinish); AI qisman natija (DeepSeek yo'q) -> o'ng panelda "Klinik izoh vaqtincha mavjud emas" + "Qayta urinish"; tahlil bo'lmagan -> `/progress` ga yo'naltirish; versiya to'qnashuvi (boshqa shifokor allaqachon tasdiqlagan) -> 409 ogohlantirishi.
- Data: `GET /exams/:id` (to'liq: bemor snapshot, vitals, files, segments, features, ai{differential, risk, drugs, narrative, modelVersion}, review{status, version}), `GET /exams/:id/features`, `GET /exams/:id/ai/differential`, `GET /exams/:id/ai/drugs`, `POST /exams/:id/drugs/check` (shifokor qo'lda dori qo'shganda o'zaro ta'sir tekshiruvi), `PUT /exams/:id/review` (qoralama), `POST /exams/:id/review/approve`, `PATCH /exams/:id/review/drugs/:drugId {status, dose, reason}`, `POST /exams/:id/reanalyze`, `GET /exams/:id/report.pdf`.
- Validatsiyalar: tasdiqlash uchun `conclusionText` >= 20 belgi, kamida 1 ta `finalDiagnosis`, har bir dori `accepted/edited/rejected` holatida (hal qilinmagan dori qolmasin), `followUpDate` > bugun, majburiy sabab (qizil o'zaro ta'sir yoki AI tavsiyasidan voz kechishda: "Nima uchun AI bilan farq qiladi" ixtiyoriy tavsiya, qizilda majburiy).
- Hamshira rejimi: barcha tahrir elementlari DOM'da yo'q, tepada "Faqat o'qish rejimi" yorlig'i; AI risk/dori bloklari tasdiqlanmagan tekshiruvda yashirin ("Shifokor tasdiqlashini kutmoqda"); signal (waveform, spektrogramma, xususiyatlar) ko'rinadi.
- Klaviatura: `Space` play, `J/K/L` orqaga/to'xtash/oldinga, `[`/`]` oldingi/keyingi sikl, `Ctrl+S` qoralama, `?` yordam.

### 3.16 Chop etiladigan PDF hisobot — `/exams/:id/report`

Maqsad: A4 formatida rasmiy hisobot (faqat `approved`).

```
+----------------------- A4 (210x297) ---------------------+
| [Logo] CardioPCG AI          Hisobot #1042-v1            |
| Muassasa nomi/manzil                    12-nov-2026      |
|----------------------------------------------------------|
| Bemor: Karimov Aziz, 54 y, E   ID: P-00231               |
| Vitals jadvali                                           |
| Waveform rasmi (S1/S2 belgilangan) + Spektrogramma       |
| Asosiy xususiyatlar jadvali (chetlanganlar belgilangan)  |
| AI differensial tashxis (jadval)  [AI - ma'lumot uchun]  |
| Shifokor xulosasi, yakuniy tashxis (ICD-10), tavsiyalar  |
| Tasdiqlangan dorilar (doza, davomiylik, ogohlantirishlar)|
|----------------------------------------------------------|
| Shifokor: Dr. Aliyev  Imzo/Muhr: [QR tekshiruv]  Sahifa 1/2|
| Disklaymer: Bu hisobot shifokor nazoratida tuzilgan...   |
+----------------------------------------------------------+
```

- Komponentlar: `PrintLayout` (`@media print`, `@page { size: A4; margin: 14mm }`), `ReportHeader`, `ReportFooter` (har sahifada), `QrVerify`.
- Data: `GET /exams/:id/report` (JSON, ekranda ko'rish va `window.print()`), `GET /exams/:id/report.pdf` (server-side PDF, Playwright/WeasyPrint — rasmiy nusxa, imzo/hash bilan), `POST /exams/:id/report/share` (muddatli havola, doctor).
- Holatlar: tasdiqlanmagan -> "Hisobot faqat tasdiqlangandan keyin mavjud"; PDF generatsiya (loading, 10 s timeout, qayta urinish).
- Amallar: Chop etish, PDF yuklash, ulashish havolasi nusxalash. Chop etishda interaktiv elementlar (`.no-print`) yashirinadi, grafiklar statik rasm sifatida (server render) chiqadi, sahifa sinishlari: `break-inside: avoid` kartalarga.
- Validatsiya: yo'q.

### 3.17 Tasdiqlash navbati — `/doctor/review-queue`

Maqsad: shifokor kutayotgan tekshiruvlarni ketma-ket ko'rib chiqishi.
- Layout: chapda navbat ro'yxati (risk va kutish vaqti bo'yicha), o'ngda tanlangan tekshiruv qisqa ko'rinishi (waveform mini + risk + top gipoteza) va "Workspace'ni ochish".
- Data: `GET /exams?status=pending_review&sort=priority`, `POST /exams/:id/claim` (boshqa shifokor bir vaqtda ochmasligi uchun 15 daq qulf).
- Holatlar: boshqa shifokor ko'rib chiqayotgan -> "Dr. X ko'rib chiqmoqda" disabled; bo'sh navbat. Amallar: ochish, o'tkazib yuborish, "Keyingisi".

---

### 3.18 Bildirishnomalar markazi — `/notifications`

Maqsad: barcha bildirishnomalar tarixi va sozlamalar. Tepadagi qo'ng'iroq (`NotificationBell`) dropdown'da oxirgi 8 ta.

```
+---------------------------------------------------------------------+
| Bildirishnomalar   [Hammasi | O'qilmagan | Kritik]  [Hammasini o'qilgan qil] [Sozlamalar]
+---------------------------------------------------------------------+
| (o) Kritik: Tekshiruv #1042 yuqori risk       10:44   [Ochish]      |
|     Yangi tekshiruv tasdiqlash kutmoqda       10:12   [Ochish]      |
|     Tekshiruv #1039 tasdiqlandi (Dr. Aliyev)  09:55                 |
+---------------------------------------------------------------------+
```

- Turlari: `exam.analysis_done`, `exam.analysis_failed`, `exam.pending_review`, `exam.critical`, `exam.approved`, `exam.rerecord_needed`, `system.deepseek_down` (admin), `security.login_anomaly` (admin).
- Data: `GET /notifications?status&type&page`, `POST /notifications/:id/read`, `POST /notifications/read-all`, `GET/PUT /notifications/preferences`; realtime: SSE `GET /events/stream` -> `queryClient.setQueryData` + toast; tab sarlavhasida badge soni `(3) CardioPCG`.
- Holatlar: bo'sh ("Yangi bildirishnoma yo'q"); SSE uzilgan -> 30 s polling. Kritik bildirishnoma toast'i avtomatik yopilmaydi (ovozsiz, `role="alert"`).
- Amallar: o'qilgan qilish, tegishli sahifaga o'tish, turlar bo'yicha yoqish/o'chirish (kritikni o'chirib bo'lmaydi). Validatsiya: yo'q.

---

### 3.19 Admin: foydalanuvchilar — `/admin/users`, `/new`, `/:id`

Maqsad: admin, shifokor, hamshira akkauntlarini boshqarish.

```
+---------------------------------------------------------------------+
| Foydalanuvchilar   [Rol: Hammasi|Admin|Shifokor|Hamshira] [Holat v] [+ Yangi]
| [Qidiruv]                                                            |
+---------------------------------------------------------------------+
| Username | F.I.Sh. | Rol | Mutaxassislik | Holat | Oxirgi kirish | ... |
| aliyev   | Aliyev  | Shifokor | Kardiolog| Faol  | bugun 09:12   | [..]|
+---------------------------------------------------------------------+
```

Yaratish/tahrirlash formasi (`UserForm`): username, F.I.Sh., rol (radio), email, telefon, mutaxassislik va litsenziya raqami (doctor), bo'lim (nurse), holat (faol/faolsiz). Yaratilganda vaqtinchalik parol bir marta ko'rsatiladi (`CopyField`, "Yopilgach qayta ko'rib bo'lmaydi") va `mustChangePassword=true`.

- Data: `GET /admin/users?role&status&q&page`, `POST /admin/users`, `GET/PATCH /admin/users/:id`, `POST /admin/users/:id/reset-password`, `POST /admin/users/:id/deactivate`, `POST /admin/users/:id/activate`, `POST /admin/users/:id/revoke-sessions`, `GET /admin/users/:id/activity` (oxirgi 50 hodisa, mini ish yuklamasi grafigi).
- Holatlar: bo'sh/xato umumiy; username band (409) -> maydon xatosi; o'zini faolsizlantirish/rolini pasaytirish bloklangan (tooltip: "O'z akkauntingizni o'zgartira olmaysiz"); oxirgi faol admin faolsizlantirilmaydi.
- Amallar: yaratish, tahrirlash, rol o'zgartirish (`ConfirmDialog`), parolni tiklash, sessiyalarni bekor qilish, faolsizlantirish (o'chirish yo'q, tarix saqlanadi).
- Validatsiya: username unikal `[a-z0-9._-]{3,32}`; email RFC; telefon `+998`; doctor uchun litsenziya raqami majburiy; rol majburiy.
- Grafiklar: foydalanuvchi detalida faollik sparkline va ish yuklamasi bar.

### 3.20 Admin: audit log — `/admin/audit`

Maqsad: kim, nima, qachon qildi (shu jumladan barcha AI chaqiruvlari).

```
+---------------------------------------------------------------------+
| Audit log      [Davr] [Foydalanuvchi v] [Amal turi v] [Natija v] [Resurs] [Qidiruv] [Eksport CSV]
+---------------------------------------------------------------------+
| Vaqt (UTC+5)   | Foydalanuvchi | Amal            | Resurs   | Natija | IP        |
| 12-nov 10:44   | aliyev        | exam.approve    | exam:1042| OK     | 10.0.x.x  |
| 12-nov 10:41   | system        | ai.deepseek.call| exam:1042| OK 2.1s| -         |
|  > qator ochilsa (Sheet): requestId, user-agent, before/after diff (JSON), AI: model, token soni, prompt hash (PHI yo'q), latency
+---------------------------------------------------------------------+
```

- Komponentlar: `AuditTable`, `AuditDetailSheet`, `JsonDiffViewer`, `ActionTypeFilter` (guruhlar: auth, patient, exam, ai, drug, admin, export).
- Data: `GET /admin/audit?from&to&userId&action&result&resource&q&cursor` (cursor pagination), `GET /admin/audit/:id`, `GET /admin/audit/export?...` (CSV, o'zi audit'ga yoziladi).
- Holatlar: bo'sh; katta natija — virtual scroll (`@tanstack/react-virtual`); xato.
- Amallar: filtr, qator tafsiloti, eksport. Audit yozuvlarini o'zgartirish/o'chirish UI'da yo'q (append-only). Validatsiya: davr <= 90 kun bir so'rovda.
- Grafiklar: tepada qisqa bar (soatlik hodisalar) va "Muvaffaqiyatsiz kirishlar" (line), shubhali faollik belgisi.

### 3.21 Admin: tizim sozlamalari — `/admin/settings`

Maqsad: AI model, DeepSeek holati, chegaralar.

```
+---------------------------------------------------------------------+
| Tizim sozlamalari                      [Saqlanmagan o'zgarishlar: 2] [Saqlash]
+---------------------------------------------------------------------+
| [AI va modellar] [Chegaralar] [Xavfsizlik] [Saqlash] [Bildirishnoma]|
+---------------------------------------------------------------------+
| AI va MODELLAR                                                       |
|  DeepSeek holati: [Faol (o'rtacha 2.1 s)]  [Ulanishni tekshirish]   |
|    Kalit: sk-****…a3f9 (serverda; UI'da o'zgartirib bo'lmaydi)      |
|    Model: (o) deepseek-chat  ( ) deepseek-reasoner                  |
|    Timeout [60] s   Retry [2]   Temperatura [0.2]   Maks token [2048]|
|    Oylik token ishlatilishi: [=====----] 4.2M / 10M   (line grafik) |
|  Signal modeli (ONNX): v1.3.0  [Faol]  Versiyalar: [v1.2.1][v1.3.0]  |
|    [Faollashtirish] [Yuklash (.onnx)]  Metrikalar: AUC, sezgirlik    |
|  Fallback: [x] DeepSeek ishlamasa faqat signal tahlili ko'rsatilsin  |
+---------------------------------------------------------------------+
| CHEGARALAR (thresholds)                                              |
|  Risk zonalari: past <[30] o'rta <[60] yuqori <[85] kritik >=85      |
|  Kritik bildirishnoma risk chegarasi [85]                            |
|  Audio: min davomiylik [5] s, maks [60] s, maks hajm [50] MB, min SNR [8] dB |
|  Vitals ogohlantirish oraliqlari (jadval, tahrirlanadi)              |
|  Navbat eskirishi: ogohlantirish [60] daq                            |
+---------------------------------------------------------------------+
| XAVFSIZLIK: parol siyosati (min uzunlik), sessiya muddati, urinishlar chegarasi, bloklash vaqti |
| SAQLASH: audio saqlash muddati (kun), zaxira holati                  |
+---------------------------------------------------------------------+
```

- Data: `GET/PUT /admin/settings`, `GET /admin/ai/status` (DeepSeek ping, latency, oxirgi xato, token hisobi), `POST /admin/ai/test` (sinov chaqiruvi, PHI'siz namunaviy matn), `GET /admin/ai/models`, `POST /admin/ai/models/:id/activate`, `POST /admin/ai/models` (upload). API kalit UI'da faqat maskalangan; o'zgartirish `.env` orqali (UI'da "Serverdagi `.env` fayl orqali o'zgartiriladi" izohi).
- Holatlar: DeepSeek "Ishlamayapti" (qizil, oxirgi xato, "qayta tekshirish"); saqlanmagan o'zgarishlar banneri; xavfli sozlama o'zgarishida (risk zonasi, model almashtirish) `ConfirmDialog` + sabab (audit'ga).
- Amallar: saqlash, sinov chaqiruvi, modelni faollashtirish (oldin shadow test natijasi ko'rsatiladi), tiklash (default).
- Validatsiya: zonalar o'suvchi (`0 < past < o'rta < yuqori < 100`), timeout 5-300, retry 0-5, temperatura 0-1, token 256-8192, audio min < maks, SNR 0-40.
- Grafiklar: token ishlatilishi (line), DeepSeek latency (sparkline), model metrikalari (bar).

### 3.22 Admin: dorilar bilimlar bazasi — `/admin/drugs`, `/:id`

Maqsad: AI dori tavsiyalari tayanadigan tekshirilgan baza (o'zaro ta'sir, qarshi ko'rsatma, doz) ni boshqarish. AI taklifi bazadagi dorilar bilan chegaralanadi.

```
+---------------------------------------------------------------------+
| Dorilar bazasi (412)  [Qidirish] [Guruh v] [Holat: Faol/Qoralama] [+ Dori] [Import CSV] [Eksport]
+---------------------------------------------------------------------+
| Nomi (INN) | Savdo nomlari | Guruh      | Versiya | Holat | Yangilangan |
| Metoprolol | Betalok       | Beta-bloker| v3      | Faol  | 2026-10-02  |
+---------------------------------------------------------------------+
Edit sahifa tablari: [Asosiy] [Dozalar] [Qarshi ko'rsatmalar] [Yon ta'sirlar] [O'zaro ta'sirlar] [Manbalar] [Tarix]
 - Asosiy: INN, savdo nomlari, ATC kod, guruh, shakllar (tab/inj), ko'rsatmalar (ICD-10 ro'yxati)
 - Dozalar: jadval (yosh/vazn/buyrak funksiyasi bo'yicha, min/maks, kunlik chegara)
 - Qarshi ko'rsatmalar: ro'yxat (mutlaq/nisbiy), homiladorlik toifasi
 - Yon ta'sirlar: ro'yxat (chastota: tez/kam uchraydigan)
 - O'zaro ta'sirlar: boshqa dori tanlash + daraja (minor/moderate/major/contraindicated) + mexanizm + tavsiya
 - Manbalar: havola/qo'llanma (majburiy, kamida 1 ta)
```

- Komponentlar: `DrugTable`, `DrugForm` (tablar), `DoseRuleEditor`, `InteractionMatrixEditor` (qidiruv bilan ikkinchi dori tanlash, simmetrik yozuv avtomatik), `SourceList`, `VersionHistory` + `JsonDiffViewer`, `CsvImportDialog` (preview + xatolar jadvali).
- Data: `GET /admin/drugs?q&group&status&page`, `POST /admin/drugs`, `GET/PUT /admin/drugs/:id`, `POST /admin/drugs/:id/publish`, `POST /admin/drugs/:id/archive`, `GET /admin/drugs/:id/versions`, `POST /admin/drugs/import` (CSV dry-run -> tasdiqlash), `GET /admin/drugs/export`, `GET /admin/drugs/interactions/graph` (ko'rinish).
- Holatlar: yangi dori `draft` — AI ko'rmaydi; `published` bo'lgach faol; o'zgartirish yangi versiya yaratadi (eski tekshiruvlar eski versiyaga havola saqlaydi); import xatolari qator bo'yicha ko'rsatiladi.
- Validatsiya: INN majburiy unikal; ATC kod regex `^[A-Z]\d{2}[A-Z]{2}\d{2}$`; doz min <= maks, musbat; kamida 1 manba; o'zaro ta'sir darajasi majburiy; o'ziga o'zi bilan ta'sir taqiqlangan; nashr qilish uchun barcha majburiy bo'limlar to'ldirilgan.
- Grafiklar: tepada guruhlar bo'yicha donut, o'zaro ta'sir tarmoq grafigi (ixtiyoriy, ECharts graph).

### 3.23 Hisobotlar va eksport — `/admin/reports`, `/reports`

Maqsad: agregat hisobotlar va ma'lumot eksporti. Admin — tizim bo'yicha (anonimlashtirilgan), doctor — o'z bemorlari bo'yicha.

```
+---------------------------------------------------------------------+
| Hisobotlar                                                          |
| Shablon: ( ) Oylik faoliyat ( ) AI aniqligi ( ) Ish yuklamasi ( ) Patologiyalar ( ) Maxsus |
| Davr [..] Guruhlash [yosh|jins|shifokor|kun] Filtrlar [..]          |
| Format: (o) PDF ( ) CSV ( ) XLSX      [Oldindan ko'rish] [Yaratish] |
+---------------------------------------------------------------------+
| Oldindan ko'rish: jadval + grafik                                   |
+---------------------------------------------------------------------+
| Yaratilgan hisobotlar: nomi | davr | format | holat | [Yuklab olish] |
+---------------------------------------------------------------------+
```

- Data: `GET /reports/templates`, `POST /reports/preview`, `POST /reports/jobs` (fon vazifa), `GET /reports/jobs` , `GET /reports/jobs/:id/download` (signed URL, 24 soat), SSE job holati. Barcha eksportlar audit logga yoziladi.
- Holatlar: job `queued/running/done/failed`; katta eksportda progress; muddati o'tgan fayl -> "Qayta yaratish".
- Validatsiya: davr <= 1 yil; kamida bitta filtr/shablon; PHI o'z ichiga olgan eksport (faqat doctor) uchun sabab maydoni majburiy va ogohlantirish. Admin eksportida shaxsiy identifikatorlar yo'q (ID hash).
- Grafiklar: preview'da tanlangan shablonga mos (bar/line/donut).

---

## 4. Analitika grafiklari katalogi

| Grafik | Kutubxona | Qaerda | Eslatma |
|---|---|---|---|
| Time series (line/area) | Recharts | admin, doctor, nurse, patient trends | Tooltip, zoom brush, gap bilan |
| Donut | Recharts `PieChart` innerRadius | rol, agreement, risk, audio sifati | Markazda jami; legend jadval ko'rinishida (a11y) |
| Grouped bar | Recharts | anomaliya ulushi yosh x jins | Yosh guruhlari: 0-17, 18-29, 30-44, 45-59, 60-74, 75+; ustida n |
| Horizontal bar | Recharts | patologiyalar, ish yuklamasi | Top-N + "Boshqalar" |
| Heatmap | ECharts `heatmap` | faollik (hafta kuni x soat) | Bitta ketma-ket rang shkalasi, visualMap legend |
| Gauge | ECharts `gauge` / SVG | risk | Zona + matn yorlig'i |
| Sparkline | Recharts (minimal) | KPI | Ramkasiz, aria-label "7 kunlik trend" |
| Agreement trend | Recharts | admin, doctor | Mos foiz vaqt bo'yicha + n tooltip |
| Waveform/spectrogram | wavesurfer / canvas | workspace | Yuqorida |

Qoidalar: kichik namuna (n < 10) bo'lsa foiz o'rniga "Ma'lumot yetarli emas (n=6)"; aniq birliklar o'qlarda; har bir grafikda `<figure>` + `figcaption` + yashirin ma'lumot jadvali (screen reader va "Jadval sifatida ko'rish" almashtirgich); eksport PNG/CSV; qora fonda ranglar tokenlardan.

"AI vs shifokor mosligi" ta'rifi: `agreement = count(final_diagnosis ∋ ai_top1) / count(approved)`; qisman moslik: top-3 ichida. Rad etilgan va tuzatilgan holatlar alohida ko'rsatiladi (model sifati monitoringi).

"Anomaliya ulushi": `abnormal = count(ai.risk >= moderate_threshold) / count(exams)` yosh guruhi va jins bo'yicha; ishonch oralig'i (Wilson) tooltip'da.

---

## 5. Holatlar (loading / empty / error) — yagona qoidalar

| Holat | Ko'rinish | Komponent |
|---|---|---|
| Loading (birinchi) | Skeleton (kontent shakliga mos), 200 ms kechikish bilan (flash oldini olish) | `Skeleton` |
| Refetch | Kontent turadi, yuqorida ingichka progress chiziq | `TopProgress` |
| Empty | Ikonka + sarlavha + 1 jumla + asosiy CTA | `EmptyState` |
| Error (karta) | Ikonka, xabar, "Qayta urinish", `requestId` (nusxalash) | `ErrorState` |
| Error (sahifa) | Route `errorElement`, `/500` | `RouteError` |
| Offline | Sariq banner "Internet yo'q — o'zgarishlar saqlanmaydi" | `OfflineBanner` |
| Forbidden | `/403` "Ruxsat yo'q" + bosh sahifaga | `ForbiddenPage` |
| Stale session | Refresh muvaffaqiyatsiz -> modal "Sessiya tugadi" -> `/login?next=` | `SessionExpiredDialog` |

---

## 6. Papka tuzilmasi

```
frontend/
  index.html
  vite.config.ts            # alias @ -> src, manual chunks (echarts, wavesurfer, recharts)
  tailwind (v4: src/styles/tokens.css), tsconfig.json, eslint.config.js
  public/ (favicon.svg, fonts/)
  src/
    main.tsx
    app/
      App.tsx               # providers: QueryClient, I18n, Theme, Router, Toaster
      router.tsx            # route xaritasi, lazy, guard'lar
      providers/            # QueryProvider, ThemeProvider, SseProvider
      shells/               # AdminShell, DoctorShell, NurseShell, AuthLayout
      guards/               # RequireAuth, RequireRole, RedirectIfAuthed
    features/
      auth/        {api, components, pages, schemas, store}
      dashboard/   {admin, doctor, nurse}/ {components, api, hooks}
      patients/    {api, components, pages, schemas, hooks}
      exams/       {api, wizard/, workspace/, progress/, report/, schemas, hooks}
      notifications/
      users/       # admin
      audit/       # admin
      settings/    # admin
      drugs/       # admin KB + clinical drug panel
      reports/
    shared/
      api/         {client.ts, auth-interceptor.ts, errors.ts, sse.ts, upload.ts}
      ui/          # shadcn komponentlar
      clinical/    # WaveformPlayer, SpectrogramView, RiskGauge, ...
      charts/      # chart wrapperlar, theme adapter
      hooks/       # useDebounce, usePermission, useMediaQuery, useSse
      lib/         # format (sana, raqam), cn, constants, zodUz (uz xato xabarlari)
      store/       # theme, ui (sidebar), auth
      types/       # OpenAPI'dan generatsiya (openapi-typescript)
    i18n/          {index.ts, locales/uz/*.json, ru/, en/}
    styles/        {tokens.css, print.css, globals.css}
    test/          # vitest setup, msw handlers
  e2e/             # Playwright
```

Qoidalar: `features/*` bir-biriga to'g'ridan-to'g'ri import qilmaydi (faqat `shared` orqali yoki public `index.ts`); `eslint-plugin-boundaries` bilan majburlanadi. Backend tiplari `openapi-typescript` bilan avtomatik (`pnpm gen:api`).

---

## 7. State management

| Turi | Vosita | Misol |
|---|---|---|
| Server state | TanStack Query 5 | patients, exams, analytics, notifications |
| Global UI/auth | Zustand | `useAuthStore` (user, accessToken — faqat xotirada), `useThemeStore`, `useUiStore` (sidebar) |
| Forma | react-hook-form + zod | barcha formalar |
| URL state | `useSearchParams` (+ zod parser) | filtr, sahifa, tab, davr |
| Wizard | Zustand slice (`useExamWizardStore`, `persist` -> sessionStorage, fayllar emas faqat `examId` va qadam) | wizard |
| Lokal | `useState`/`useReducer` | dialog, toggle |

Query key fabrikasi: `qk.patients.list(filters)`, `qk.exams.detail(id)`. Standart: `staleTime` 30 s (analitika 2 daq), `gcTime` 10 daq, `retry` 1 (4xx'da 0), `refetchOnWindowFocus` true (klinik ma'lumotda yangilik muhim). Mutatsiyalarda invalidatsiya aniq kalitlar bo'yicha; tasdiqlashda optimistik yangilash qo'llanmaydi (klinik amal — server javobini kutadi). SSE hodisalari `queryClient.invalidateQueries`/`setQueryData` ga bog'lanadi. Access token localStorage'da SAQLANMAYDI (XSS), faqat xotirada; sahifa yangilanganda `POST /auth/refresh` (cookie) bilan tiklanadi.

---

## 8. API klienti va token yangilash

`shared/api/client.ts` — `axios` (yoki `ky`) instansiyasi: `baseURL=/api/v1`, `withCredentials: true`, `timeout: 30_000` (yuklash uchun alohida, cheksiz + progress).

Request interceptor: `Authorization: Bearer <accessToken>`, `X-Request-Id` (uuid), `Accept-Language`.

Response interceptor (single-flight refresh):

```ts
let refreshing: Promise<string> | null = null;

api.interceptors.response.use(undefined, async (error) => {
  const { config, response } = error;
  if (response?.status === 401 && !config._retry && !config.url.includes('/auth/')) {
    config._retry = true;
    refreshing ??= api.post('/auth/refresh')            // httpOnly cookie, rotation
      .then(r => { authStore.setToken(r.data.accessToken); return r.data.accessToken; })
      .finally(() => { refreshing = null; });
    try {
      const token = await refreshing;
      config.headers.Authorization = `Bearer ${token}`;
      return api(config);                                // so'rovni qayta yuborish
    } catch {
      authStore.logout({ reason: 'session_expired' });  // modal + /login?next=
    }
  }
  return Promise.reject(normalizeError(error));
});
```

- Bir vaqtda ko'p 401 -> bitta refresh (single-flight), qolganlari kutadi.
- Refresh'ni vaqtidan oldin: access token `exp` ga 60 s qolganda fon timer (`setTimeout`) yangilaydi; ko'p tabli sinxron: `BroadcastChannel('auth')` orqali logout/token yangilash.
- Refresh token rotation: 401 `refresh_reused` (o'g'irlik belgisi) -> darhol logout + "Xavfsizlik sababli qayta kiring".
- SSE: `fetch`-asosli `EventSource` polyfill (Authorization header uchun, `@microsoft/fetch-event-source`), uzilsa eksponensial backoff (1, 2, 4, 8, max 30 s), `Last-Event-ID` bilan davom.
- Yuklash (`upload.ts`): presigned PUT, 5 MB chunk, parallel 3, qayta urinish, `AbortController` bilan bekor qilish, progress callback.
- Xato normallashtirish: `ApiError {status, code, message, fieldErrors?, requestId}`; backend formati `{error:{code, message, details[], requestId}}`.

---

## 9. Xatolarni qayta ishlash

| Holat | Xatti-harakat |
|---|---|
| 400/422 | `fieldErrors` -> `form.setError`; umumiy xabar `Alert` |
| 401 | Refresh urinishi, bo'lmasa login |
| 403 | `/403` yoki toast "Ruxsat yo'q" (amal uchun) |
| 404 | Resurs topilmadi sahifasi/EmptyState |
| 409 | Versiya to'qnashuvi dialogi ("Boshqa foydalanuvchi o'zgartirdi — yangilash") |
| 413/415 | Fayl hajmi/formati xabari wizard'da |
| 423/429 | Bloklash/limit xabari + qolgan vaqt (`Retry-After`) |
| 5xx | Toast "Server xatosi" + `requestId` + qayta urinish; kritik oqimlarda (tasdiqlash) ma'lumot yo'qolmaydi (forma holati saqlanadi) |
| Tarmoq | `OfflineBanner`; mutatsiyalar navbatga olinmaydi (klinik xavfsizlik), foydalanuvchiga qayta urinish tugmasi |
| AI xizmat xatosi | Qisman natija + aniq banner; hech qachon "AI natijasi" soxta to'ldirilmaydi |

Global: React `ErrorBoundary` har route'da (`errorElement`), Sentry (self-hosted yoki o'chirilgan; PHI skrab qilinadi: maskalanadigan maydonlar), `window.onunhandledrejection` logi. Foydalanuvchiga matnlar o'zbekcha, texnik tafsilot faqat `requestId` bilan.

---

## 10. Responsiv va planshet-first (hamshira)

Breakpointlar: `sm 640`, `md 768`, `lg 1024`, `xl 1280`, `2xl 1536`. Hamshira oqimi uchun dizayn bazasi: 768-1024px (planshet) va portret/landshaft.

- Hamshira shell: `BottomNav` (<1024), katta touch target (>= 56px), tugmalar `size="touch"`, forma maydonlari balandligi 52px, `inputmode` (numeric vitals uchun `inputmode="decimal"`), katta stepper.
- Wizard planshetda to'liq ekran, "Keyingi" tugmasi pastda sticky (`position: sticky; bottom: 0`), klaviatura ochilganda yashirmaydi (`visualViewport`).
- Mikrofondan yozish: katta yozish tugmasi, vaqt hisoblagich, darajali indikator; ekran o'chmasligi (`navigator.wakeLock`).
- Jadvallar <768px da kartalar ro'yxatiga aylanadi.
- Workspace planshetda: waveform tepada to'liq kenglik, o'ng panel tablar ostida (accordion); hamshira ko'rinishi soddalashtirilgan.
- Hover'ga tayanilmaydi (tooltip: bosish bilan ham ochiladi); pinch-zoom waveform'da qo'llab-quvvatlanadi.
- Desktop doctor: sahifa 2 ustunli (waveform | AI panel), >= 1440px da 3 ustun imkoniyati.
- PWA: `manifest.json` (standalone, ikonlar), service worker faqat statik aktiv keshlash (API keshlanmaydi — PHI).
- Test qurilmalar: iPad (810x1080), Galaxy Tab (800x1280), 1366x768 noutbuk, 1920x1080.

---

## 11. Accessibility (WCAG 2.2 AA)

- Semantik HTML, landmark'lar (`header`, `nav`, `main`, `aside`), "Asosiy kontentga o'tish" skip-link.
- Klaviatura: barcha interaktivlar fokuslanadi, ko'rinadigan fokus halqasi (`ring-2 ring-[--ring] ring-offset-2`), tartib mantiqiy, `Esc` dialog yopadi, fokus tuzog'i va qaytarish (shadcn/Radix beradi); jadvallarda strelka navigatsiyasi (ixtiyoriy).
- ARIA: `aria-live="polite"` (progress, toast), `role="alert"` (kritik xatolar), `aria-busy` skeletonlarda, `aria-describedby` forma xatolari, `aria-current="page"` menyuda; Stepper `aria-current="step"`.
- Rang: holat faqat rangda emas (ikonka + matn); kontrast tekshiruvi CI'da (`axe`); dark mode alohida tekshiriladi; colormap spektrogramma (viridis) rang ko'rligiga mos.
- Waveform/spektrogram: matnli muqobil — "Signal xulosasi": sikllar soni, HR, shovqin mavjudligi (screen reader uchun), S1/S2 vaqtlari jadvali ("Jadval sifatida ko'rish"); pleyer klaviatura bilan to'liq boshqariladi, play tugmasida `aria-pressed`.
- Grafiklar: `figure`+`figcaption`, ma'lumot jadvali muqobili, `aria-label` sparkline'da.
- Harakat: `prefers-reduced-motion` — animatsiyalar o'chiriladi (gauge sakrashi, progress shimmer).
- Shrift o'lchami: foydalanuvchi brauzer o'lchamiga mos (rem), 200% kattalashtirishda layout buzilmaydi; matn oralig'i.
- Formalar: ko'rinadigan label (placeholder o'rniga emas), majburiy belgi `aria-required`, xato fokusga olinadi (birinchi xato maydoniga), avtotoldirish atributlari.
- Auto-logout oldidan ogohlantirish (1 daq) va sessiyani uzaytirish imkoniyati (WCAG vaqt chegarasi).

---

## 12. i18n

`react-i18next`, asosiy til `uz` (lotin), keyin `ru`, `en`. Fallback `uz`. Namespace'lar: `common`, `auth`, `nav`, `dashboard`, `patients`, `exams`, `clinical`, `drugs`, `admin`, `notifications`, `errors`, `validation`. Kalitlar: `namespace:section.key` (inglizcha, snake/dot), kodda matn qattiq yozilmaydi (ESLint `i18next/no-literal-string` — JSX matn uchun).

Namuna (`uz/exams.json`):

```json
{
  "status": {
    "draft": "Qoralama", "uploading": "Yuklanmoqda", "analyzing": "AI tahlilda",
    "pending_review": "Shifokor kutilmoqda", "approved": "Tasdiqlangan", "failed": "Xato"
  },
  "wizard": {
    "steps": { "patient": "Bemor", "vitals": "Vitals", "recording": "Yozuv", "confirm": "Tasdiq" },
    "quality": { "duration_ok": "Davomiylik yetarli", "noise_high": "Shovqin yuqori — qayta yozing", "clipping": "Signal kesilgan (klipping)" },
    "actions": { "start_analysis": "Tahlilni boshlash", "back": "Orqaga", "next": "Keyingisi" }
  },
  "workspace": {
    "ai_disclaimer": "AI xulosasi — ma'lumot uchun, shifokor tasdiqlaydi",
    "approve": "Tasdiqlash va imzolash",
    "read_only": "Faqat o'qish rejimi",
    "interaction": { "minor": "Kichik", "moderate": "O'rtacha", "major": "Jiddiy", "contraindicated": "Qarshi ko'rsatma" }
  }
}
```

Boshqa kalitlar: `auth.login.title`, `auth.errors.invalid_credentials`, `validation.required`, `validation.min_length` (`{{count}}`), `errors.network`, `errors.forbidden`, `nav.dashboard`, `nav.patients`, `clinical.risk.low|moderate|high|critical`, `clinical.features.hr`, `clinical.points.aortic|pulmonic|tricuspid|mitral`.

Format: sana `Intl.DateTimeFormat('uz-UZ', {timeZone:'Asia/Tashkent'})` (UI), serverda UTC; raqamlar `Intl.NumberFormat`; o'nlik ajratgich vergul (uz/ru), nuqta (en). Ko'plik shakllari `i18next` plural. Zod xato xabarlari `zodUz` xaritasi orqali o'zbekchada. Til almashtirgich `UserMenu`'da; tanlov `PATCH /users/me {locale}` bilan saqlanadi. Tibbiy atamalar ro'yxati (glossary) `docs`da, tarjimon uchun bir xil ma'noni saqlash.

---

## 13. Performance

- Route-based code splitting (`React.lazy`), shell'lar va rol modullari alohida chunk; admin kodi doktor/nurse'ga yuklanmaydi.
- Og'ir kutubxonalar dinamik import: `echarts` (faqat heatmap/gauge), `wavesurfer.js` (faqat workspace/wizard), PDF/print ko'rinishi; `manualChunks` (`vendor-react`, `vendor-charts`, `vendor-wave`).
- Byudjet: boshlang'ich JS <= 180 KB gzip (login/dashboard), LCP < 2.5 s (4G), INP < 200 ms, CLS < 0.1; `size-limit` CI'da.
- Prefetch: ro'yxatda qator hover/focus -> `queryClient.prefetchQuery(detail)`; navbatdagi keyingi tekshiruv prefetch.
- Katta ro'yxatlar: server pagination, audit log `@tanstack/react-virtual`.
- Waveform: serverdan oldindan hisoblangan peaks (`GET .../peaks`), audio `Range`/stream; spektrogramma server PNG (kichik, keshlanadi), canvas hisoblash Web Worker'da; `OffscreenCanvas` qo'llab-quvvatlansa.
- Grafiklar: `ResponsiveContainer` debounce, ma'lumot nuqtalari <= 500 (backend downsample LTTB), animatsiya katta ma'lumotda o'chiriladi; viewport'ga kirganda render (`IntersectionObserver`).
- Rasmlar: `loading="lazy"`, WebP/AVIF; shriftlar `font-display: swap`, faqat lotin+kiril subset, variable font.
- Keshlash: statik aktivlar `immutable` (hash), `index.html` `no-cache`; API javoblarida PHI bo'lgani uchun brauzer HTTP keshi o'chirilgan (`Cache-Control: no-store`), kesh faqat TanStack Query xotirasida.
- Re-render nazorati: selektor bilan Zustand (`useStore(s => s.x)`), `React.memo` og'ir kartalarda, React Compiler (React 19) yoqilgan.
- Monitoring: `web-vitals` -> `/telemetry` (PHI'siz).

---

## 14. Xavfsizlik (frontend tomoni)

CSP (nginx): `default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'`; token xotirada; `dangerouslySetInnerHTML` taqiqlangan (rich text DOMPurify bilan); tashqi CDN yo'q (shriftlar/self-host); PHI konsolga/analytics'ga yozilmaydi; inaktivlikda 15 daq avto-logout (ekran qulfi), ekran qulfidan keyin parol bilan qayta kirish; admin'da bemor ma'lumotlari maskalangan; clipboard/print'da "maxfiy" suv belgisi (foydalanuvchi + vaqt) hisobotda.

---

## 15. Playwright e2e test ro'yxati

Muhit: `docker compose` test stack, test ma'lumotlar `e2e/fixtures` orqali API'dan yaratiladi (seed parollar productionda yo'q — test stack'da `scripts/create_admin.py` bilan alohida yaratiladi). Brauzerlar: chromium, webkit (iPad emulyatsiyasi), firefox (smoke). Loyihalar: `desktop-chrome`, `tablet-ipad` (nurse), `mobile-smoke`. DeepSeek va signal model `msw`/test double bilan almashtiriladi (deterministik).

| # | Test | Rol | Tekshiriladi |
|---|---|---|---|
| 1 | auth.login.success | hamma | to'g'ri kirish, rol dashboardiga yo'naltirish |
| 2 | auth.login.invalid | - | noto'g'ri parol xabari, parol maydoni tozalanadi |
| 3 | auth.lockout | - | N urinishdan keyin 423 xabari |
| 4 | auth.forgot_reset | - | havola, yangi parol, eski token yaroqsiz |
| 5 | auth.change_password.forced | doctor | mustChangePassword majburiy yo'naltirish |
| 6 | auth.token_refresh | doctor | access muddati tugaganda jimgina yangilanish, bir vaqtda ko'p so'rov = 1 refresh |
| 7 | auth.session_expired | doctor | refresh rad -> modal -> login -> `next` ga qaytish |
| 8 | rbac.route_guards | hamma | nurse `/admin`ga kira olmaydi (403), doctor `/admin/users`ga yo'q |
| 9 | rbac.nurse_readonly | nurse | workspace'da tahrir/tasdiqlash elementlari yo'q |
| 10 | admin.dashboard.render | admin | KPI, 6+ grafik yuklanadi, davr filtri o'zgartirilganda yangilanadi |
| 11 | admin.dashboard.partial_error | admin | bitta endpoint 500 -> faqat shu karta xato |
| 12 | doctor.dashboard.queue | doctor | navbat tartibi (kritik birinchi), "Keyingisi" |
| 13 | nurse.dashboard.tablet | nurse | katta tugmalar, BottomNav, bugungi ro'yxat |
| 14 | patients.list.filters | doctor | qidiruv, filtr URLda, pagination, bo'sh holat |
| 15 | patients.create.validation | nurse | zod xatolari, BMI avto, dublikat dialogi |
| 16 | patients.create.draft | nurse | qoralama tiklanishi, saqlanmagan ogohlantirish |
| 17 | patients.edit.history | doctor | anamnez/allergiya/dori qo'shish va saqlash |
| 18 | patients.detail.tabs | doctor | tab'lar, allergiya sticky header |
| 19 | patients.timeline.trends | doctor | trend grafik, nuqta -> tekshiruv, <2 tekshiruv holati |
| 20 | exam.wizard.happy_path | nurse (tablet) | bemor -> vitals -> audio yuklash -> sifat OK -> yuborish |
| 21 | exam.wizard.validation | nurse | vitals oraliqlari, format/hajm xatosi, davomiylik |
| 22 | exam.wizard.low_quality | nurse | sifat past ogohlantirishi, yaroqsiz bloklanadi |
| 23 | exam.wizard.upload_resume | nurse | tarmoq uzilishi, chunk qayta urinish, bekor qilish |
| 24 | exam.progress.live | nurse | SSE bosqichlari, tugagach avtoyo'naltirish |
| 25 | exam.progress.sse_fallback | nurse | SSE uzilganda polling |
| 26 | exam.progress.ai_partial | doctor | DeepSeek down -> qisman natija banneri |
| 27 | exam.workspace.waveform | doctor | waveform, S1/S2 markerlar soni, play/zoom/klaviatura |
| 28 | exam.workspace.spectrogram_sync | doctor | kursor sinxronligi |
| 29 | exam.workspace.features_table | doctor | qator -> waveform highlight |
| 30 | exam.workspace.differential | doctor | gipotezalar tartibi, disklaymer ko'rinadi |
| 31 | exam.drugs.interaction_warning | doctor | qizil o'zaro ta'sirda qabul bloklanadi, sabab bilan baribir |
| 32 | exam.drugs.allergy_excluded | doctor | allergik dori ro'yxatda yo'q, ogohlantirish bor |
| 33 | exam.review.approve | doctor | validatsiya, tasdiqlash, qulf, bildirishnoma |
| 34 | exam.review.conflict_409 | doctor x2 | ikkinchi shifokor 409 dialogi |
| 35 | exam.review.new_version | doctor | tuzatish -> v2, tarix |
| 36 | exam.report.print_pdf | doctor | A4 hisobot, PDF yuklash, draft dorilar yo'q |
| 37 | exam.report.unapproved_blocked | nurse | tasdiqlanmagan hisobot ochilmaydi |
| 38 | notifications.realtime | doctor+nurse | yangi tekshiruv -> bell badge, toast, o'qilgan qilish |
| 39 | admin.users.crud | admin | yaratish (vaqtinchalik parol), rol o'zgartirish, faolsizlantirish, o'zini bloklash taqiq |
| 40 | admin.audit.filters | admin | filtr, detail sheet, eksport, o'zgartirib bo'lmasligi |
| 41 | admin.settings.thresholds | admin | validatsiya (zona tartibi), saqlash, audit yozuvi |
| 42 | admin.settings.deepseek_status | admin | holat kartasi, sinov chaqiruvi |
| 43 | admin.drugs.crud_publish | admin | yaratish, o'zaro ta'sir, nashr, versiya, CSV import dry-run |
| 44 | reports.export_job | admin/doctor | job holati, yuklab olish, audit |
| 45 | theme.dark_light | hamma | mavzu almashtirish, grafik ranglari yangilanadi, saqlanadi |
| 46 | i18n.locale_switch | hamma | til almashishi, sana/raqam formati |
| 47 | a11y.axe.pages | hamma | asosiy sahifalarda `@axe-core/playwright` jiddiy xatosiz (ikkala mavzu) |
| 48 | a11y.keyboard.wizard | nurse | wizard va workspace faqat klaviatura bilan |
| 49 | responsive.tablet.layouts | nurse | 768/1024px layout, jadval->karta |
| 50 | security.no_token_storage | hamma | localStorage/sessionStorage'da token yo'q, cookie httpOnly |
| 51 | security.idle_logout | doctor | inaktivlikdan keyin ogohlantirish va chiqish |
| 52 | no_emoji.lint | - | build'da emoji topilmasligi (statik tekshiruv) |

CI: `pnpm test:e2e` har PR'da (chromium + tablet), kechasi to'liq matritsa; vizual regressiya (`toHaveScreenshot`) dashboard va hisobot PDF-ko'rinishida; trace/video faqat xatoda.

---

## 16. Qabul mezonlari (Definition of Done) — frontend

1. Barcha yuqoridagi route'lar rol guard bilan ishlaydi; ruxsatsiz amallar DOM'da yo'q.
2. Har sahifada loading/empty/error holatlari amalga oshirilgan.
3. Har AI natijasi yonida disklaymer, dori tavsiyasi shifokor tasdiqlamaguncha "taklif" holatida.
4. Light/dark ikkalasida kontrast va `axe` o'tadi; emoji yo'q, faqat Tabler Icons.
5. Hamshira oqimi 768px planshetda to'liq bajariladi (wizard, yuklash, ro'yxat).
6. Token faqat xotirada, refresh single-flight, 401 oqimi e2e bilan tasdiqlangan.
7. Performance byudjeti va Playwright ro'yxati (52 test) CI'da yashil.
