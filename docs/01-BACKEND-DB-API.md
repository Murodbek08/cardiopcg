# CardioPCG AI — Backend, ma'lumotlar bazasi va API texnik spetsifikatsiyasi

Hujjat holati: v1.0 (implementatsiyaga tayyor). Asos: `00-ARCHITECTURE-DECISIONS.md`.
Til qoidasi: tushuntirishlar o'zbekcha (lotin), identifikatorlar (jadval, ustun, endpoint, enum, kod) inglizcha.

## 0. Umumiy qoidalar

- Base URL: `https://cardiopcgai.189.uz/api/v1`. WebSocket: `wss://cardiopcgai.189.uz/api/v1/ws`. Hamma javob `application/json; charset=utf-8` (fayl yuklab olish va SSE bundan mustasno).
- Vaqt: DB'da `timestamptz` (UTC), API'da ISO 8601 (`2026-11-18T09:30:00Z`). Sana: `YYYY-MM-DD`.
- ID: barcha jadvallarda `uuid` (UUIDv7, `uuid_utils` kutubxonasi orqali ilovada generatsiya qilinadi — vaqt bo'yicha tartiblanadi, indeks uchun yaxshi). Foydalanuvchiga ko'rinadigan qisqa kodlar: `patients.mrn`, `examinations.exam_no`.
- Soft delete: `patients`, `examinations`, `users` jadvallarida `deleted_at`. Tibbiy yozuvlar fizik o'chirilmaydi (saqlash muddati — 7.4-bo'lim).
- Barcha jadvallarda `created_at`, `updated_at` (trigger yoki SQLAlchemy `onupdate`). Optimistik blokirovka: tahrirlanadigan resurslarda `version int` (PATCH'da `If-Match: <version>` sarlavhasi; mos kelmasa `409 VERSION_CONFLICT`).
- Naming: jadval — snake_case, ko'plik. Enum'lar PostgreSQL `CREATE TYPE ... AS ENUM` (SQLAlchemy `Enum(native_enum=True)`), qiymat qo'shish — Alembic migratsiyasi bilan `ALTER TYPE ... ADD VALUE`.
- Xato formati (RFC 7807 ga yaqin, hamma xato uchun yagona):

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Ma'lumotlar noto'g'ri",
    "details": [{"field": "birth_date", "msg": "Kelajak sanasi bo'lishi mumkin emas", "type": "value_error"}],
    "request_id": "01JC8M7Q2V6Y0W3K9N5R4T1XAB"
  }
}
```

- `request_id` — middleware generatsiya qiladi, `X-Request-ID` sarlavhasida ham qaytadi, structlog va audit_logs'da yoziladi.
- Umumiy HTTP kodlari: `400 BAD_REQUEST`, `401 UNAUTHENTICATED` / `TOKEN_EXPIRED`, `403 FORBIDDEN`, `404 NOT_FOUND`, `409 CONFLICT` / `VERSION_CONFLICT` / `INVALID_STATE`, `413 FILE_TOO_LARGE`, `415 UNSUPPORTED_MEDIA_TYPE`, `422 VALIDATION_ERROR`, `423 ACCOUNT_LOCKED`, `429 RATE_LIMITED` (+`Retry-After`), `500 INTERNAL_ERROR`, `502 AI_UPSTREAM_ERROR`, `503 SERVICE_UNAVAILABLE`.

---

## 1. PostgreSQL 17 sxemasi

Kengaytmalar: `pgcrypto` (gen_random_uuid zaxira), `pg_trgm` (qidiruv), `citext` (username/email), `btree_gin`.

### 1.1 Enum'lar

```sql
CREATE TYPE user_role AS ENUM ('admin','doctor','nurse');
CREATE TYPE user_status AS ENUM ('active','suspended','pending');          -- pending: parol hali o'rnatilmagan
CREATE TYPE gender AS ENUM ('male','female');
CREATE TYPE blood_group AS ENUM ('O+','O-','A+','A-','B+','B-','AB+','AB-','unknown');
CREATE TYPE exam_status AS ENUM (
  'draft','uploaded','queued','processing','ai_ready','in_review',
  'completed','failed','cancelled');
CREATE TYPE exam_priority AS ENUM ('routine','urgent','emergency');
CREATE TYPE auscultation_site AS ENUM ('aortic','pulmonic','erb','tricuspid','mitral','apex','carotid','other');
CREATE TYPE patient_position AS ENUM ('supine','sitting','left_lateral','standing','other');
CREATE TYPE recording_kind AS ENUM ('audio','spectrogram','waveform_image','envelope_json','other_image');
CREATE TYPE recording_status AS ENUM ('uploading','uploaded','validated','rejected','processed');
CREATE TYPE job_status AS ENUM ('pending','running','succeeded','failed','cancelled');
CREATE TYPE pcg_class AS ENUM ('normal','murmur','extra_heart_sound','artifact','undetermined');
CREATE TYPE severity AS ENUM ('none','mild','moderate','severe','critical');
CREATE TYPE segment_type AS ENUM ('S1','S2','S3','S4','systole','diastole','murmur','click','noise');
CREATE TYPE murmur_timing AS ENUM ('systolic','diastolic','continuous','none');
CREATE TYPE report_status AS ENUM ('generating','ready','failed','superseded');
CREATE TYPE prescription_status AS ENUM ('draft','suggested','approved','rejected','cancelled');
CREATE TYPE conclusion_status AS ENUM ('draft','signed','amended');
CREATE TYPE agreement_level AS ENUM ('agree','partial','disagree');
CREATE TYPE notification_type AS ENUM (
  'exam_uploaded','analysis_done','analysis_failed','review_requested',
  'conclusion_signed','critical_finding','assignment','system');
CREATE TYPE audit_action AS ENUM (
  'login','login_failed','logout','token_refresh','token_reuse_detected','password_change','password_reset',
  'create','read','update','delete','restore','export','download','upload','assign',
  'ai_call','status_change','sign','approve','reject','permission_denied','settings_change');
CREATE TYPE allergy_severity AS ENUM ('mild','moderate','severe','anaphylaxis');
CREATE TYPE history_kind AS ENUM ('cardiac','chronic','surgical','family','habit','other');
CREATE TYPE export_format AS ENUM ('pdf','csv','json');
```

### 1.2 `users`

| ustun | tur | izoh |
|---|---|---|
| id | uuid PK | |
| username | citext NOT NULL UNIQUE | 3-32, `[a-z0-9._-]` |
| email | citext NULL UNIQUE | parolni tiklash uchun (ixtiyoriy) |
| password_hash | text NOT NULL | argon2id |
| full_name | varchar(160) NOT NULL | |
| role | user_role NOT NULL | |
| status | user_status NOT NULL DEFAULT 'active' | |
| phone | varchar(32) NULL | E.164 |
| specialty | varchar(120) NULL | doctor uchun (kardiolog va h.k.) |
| license_no | varchar(64) NULL | shifokor litsenziyasi |
| department | varchar(120) NULL | |
| avatar_key | text NULL | storage key |
| locale | varchar(5) NOT NULL DEFAULT 'uz' | uz/ru/en |
| must_change_password | boolean NOT NULL DEFAULT false | birinchi kirishda |
| failed_login_count | smallint NOT NULL DEFAULT 0 | |
| locked_until | timestamptz NULL | |
| last_login_at | timestamptz NULL | |
| password_changed_at | timestamptz NOT NULL | |
| created_by | uuid NULL FK users(id) | |
| created_at, updated_at, deleted_at | timestamptz | |

Indekslar: `UNIQUE(username)`, `UNIQUE(email)`, `idx_users_role_status (role, status) WHERE deleted_at IS NULL`, `idx_users_fullname_trgm GIN (full_name gin_trgm_ops)`.
CHECK: `role='doctor' OR specialty IS NULL OR true` (qat'iy emas); `char_length(username)>=3`.

### 1.3 `refresh_tokens`

Refresh token ma'lumotni DB'da faqat hash ko'rinishida (SHA-256) saqlanadi. `family_id` — rotation zanjiri: bir token ikki marta ishlatilsa (reuse) butun oila bekor qilinadi.

| ustun | tur | izoh |
|---|---|---|
| id | uuid PK | |
| user_id | uuid NOT NULL FK users(id) ON DELETE CASCADE | |
| family_id | uuid NOT NULL | login'da yangi, rotation'da meros |
| token_hash | char(64) NOT NULL UNIQUE | sha256(hex) |
| parent_id | uuid NULL FK refresh_tokens(id) | |
| issued_at | timestamptz NOT NULL | |
| expires_at | timestamptz NOT NULL | issued + 7 kun |
| used_at | timestamptz NULL | rotation vaqti |
| revoked_at | timestamptz NULL | |
| revoked_reason | varchar(32) NULL | `logout`,`rotated`,`reuse_detected`,`password_change`,`admin` |
| ip | inet NULL | |
| user_agent | varchar(300) NULL | |
| device_label | varchar(120) NULL | "Chrome / Windows" |

Indekslar: `idx_rt_user_active (user_id) WHERE revoked_at IS NULL`, `idx_rt_family (family_id)`, `idx_rt_expires (expires_at)` (tozalash job'i uchun).

### 1.4 `patients`

| ustun | tur | izoh |
|---|---|---|
| id | uuid PK | |
| mrn | varchar(16) NOT NULL UNIQUE | Medical record number: `P-2026-000123` (sequence `patient_mrn_seq` + yil) |
| last_name, first_name | varchar(80) NOT NULL | |
| middle_name | varchar(80) NULL | otasining ismi |
| birth_date | date NOT NULL | |
| gender | gender NOT NULL | |
| phone | varchar(32) NULL | |
| email | citext NULL | |
| address | text NULL | |
| national_id_enc | bytea NULL | JShShIR (PINFL) — AES-GCM bilan ilova darajasida shifrlanadi (`PII_ENCRYPTION_KEY`); qidiruv uchun `national_id_hash char(64)` |
| national_id_hash | char(64) NULL UNIQUE | HMAC-SHA256 |
| blood_group | blood_group NOT NULL DEFAULT 'unknown' | |
| height_cm | numeric(5,1) NULL | 30..260 |
| weight_kg | numeric(5,1) NULL | 1..400 |
| emergency_contact_name | varchar(160) NULL | |
| emergency_contact_phone | varchar(32) NULL | |
| primary_doctor_id | uuid NULL FK users(id) | mas'ul shifokor |
| notes | text NULL | |
| is_active | boolean NOT NULL DEFAULT true | |
| version | int NOT NULL DEFAULT 1 | |
| created_by | uuid NOT NULL FK users(id) | |
| created_at, updated_at, deleted_at | timestamptz | |

Hisoblanadigan: `age` (API'da), `bmi` (API'da `weight/(height/100)^2`).
Indekslar: `UNIQUE(mrn)`, `UNIQUE(national_id_hash)`, `idx_patients_name_trgm GIN ((last_name||' '||first_name||' '||coalesce(middle_name,'')) gin_trgm_ops)`, `idx_patients_phone (phone)`, `idx_patients_birth (birth_date)`, `idx_patients_doctor (primary_doctor_id) WHERE deleted_at IS NULL`, `idx_patients_created (created_at DESC)`.

### 1.5 `medical_history`, `allergies`, `current_medications`

`medical_history` (anamnez):

| ustun | tur | izoh |
|---|---|---|
| id | uuid PK | |
| patient_id | uuid NOT NULL FK patients(id) ON DELETE CASCADE | |
| kind | history_kind NOT NULL | |
| title | varchar(200) NOT NULL | masalan "Gipertoniya" |
| icd10_code | varchar(10) NULL | `I10` |
| description | text NULL | |
| onset_date | date NULL | |
| resolved_date | date NULL | |
| is_active | boolean NOT NULL DEFAULT true | |
| recorded_by | uuid NOT NULL FK users(id) | |
| created_at, updated_at | timestamptz | |

Indeks: `(patient_id, kind)`, `(patient_id) WHERE is_active`.

`allergies`:

| ustun | tur | izoh |
|---|---|---|
| id | uuid PK | |
| patient_id | uuid NOT NULL FK ON DELETE CASCADE | |
| substance | varchar(160) NOT NULL | "Penitsillin" |
| substance_code | varchar(64) NULL | ATC/INN, dori tekshiruvi uchun normalizatsiya |
| reaction | varchar(200) NULL | "toshma" |
| severity | allergy_severity NOT NULL DEFAULT 'moderate' | |
| noted_date | date NULL | |
| is_active | boolean NOT NULL DEFAULT true | |
| recorded_by | uuid NOT NULL FK users(id) | |
| created_at, updated_at | timestamptz | |

Indeks: `(patient_id) WHERE is_active`, `(lower(substance_code))`. UNIQUE `(patient_id, lower(substance)) WHERE is_active`.

`current_medications`:

| ustun | tur | izoh |
|---|---|---|
| id | uuid PK | |
| patient_id | uuid NOT NULL FK ON DELETE CASCADE | |
| drug_name | varchar(160) NOT NULL | |
| inn_code | varchar(64) NULL | xalqaro nomi/ATC |
| dose | varchar(60) NULL | "5 mg" |
| frequency | varchar(60) NULL | "kuniga 1 marta" |
| route | varchar(30) NULL | `oral`, `iv` ... |
| start_date | date NULL | |
| end_date | date NULL | |
| prescribed_by | varchar(160) NULL | |
| is_active | boolean NOT NULL DEFAULT true | |
| recorded_by | uuid NOT NULL FK users(id) | |
| created_at, updated_at | timestamptz | |

Indeks: `(patient_id) WHERE is_active`, `(lower(inn_code))`.

### 1.6 `examinations`

Tekshiruv (visit) — bir bemorning bitta seansi; ichida bir nechta yozuv (recordings) — turli auskultatsiya nuqtalari.

| ustun | tur | izoh |
|---|---|---|
| id | uuid PK | |
| exam_no | varchar(20) NOT NULL UNIQUE | `E-20261118-0042` (kunlik sequence) |
| patient_id | uuid NOT NULL FK patients(id) | |
| status | exam_status NOT NULL DEFAULT 'draft' | 5-bo'limdagi state machine |
| priority | exam_priority NOT NULL DEFAULT 'routine' | |
| performed_by | uuid NOT NULL FK users(id) | yozuvni olgan (nurse/doctor) |
| assigned_doctor_id | uuid NULL FK users(id) | ko'rib chiqadigan shifokor |
| examined_at | timestamptz NOT NULL DEFAULT now() | |
| complaints | text NULL | shikoyatlar |
| symptoms | text[] NOT NULL DEFAULT '{}' | `{dyspnea,chest_pain,palpitations,syncope,edema}` |
| patient_position | patient_position NULL | |
| heart_rate_bpm | smallint NULL | 20..300 (qo'lda o'lchangan) |
| bp_systolic | smallint NULL | 40..300 |
| bp_diastolic | smallint NULL | 20..200 |
| spo2_pct | smallint NULL | 50..100 |
| temperature_c | numeric(3,1) NULL | 30..45 |
| weight_kg_at_exam | numeric(5,1) NULL | |
| ai_requested_at | timestamptz NULL | |
| ai_completed_at | timestamptz NULL | |
| completed_at | timestamptz NULL | doctor_conclusion imzolangan |
| cancel_reason | text NULL | |
| failure_reason | text NULL | |
| current_job_id | uuid NULL | `analysis_jobs.id` |
| version | int NOT NULL DEFAULT 1 | |
| created_at, updated_at, deleted_at | timestamptz | |

CHECK: `bp_systolic > bp_diastolic` (ikkalasi NOT NULL bo'lganda); `status='completed' => completed_at IS NOT NULL`.
Indekslar: `UNIQUE(exam_no)`, `(patient_id, examined_at DESC)`, `(status, created_at DESC) WHERE deleted_at IS NULL`, `(assigned_doctor_id, status) WHERE deleted_at IS NULL`, `(performed_by, created_at DESC)`, `(examined_at)` (analitika), `(priority, status) WHERE status IN ('ai_ready','in_review')`, BRIN `(created_at)`.

### 1.7 `recordings` (audio va tasvir fayllari)

| ustun | tur | izoh |
|---|---|---|
| id | uuid PK | |
| examination_id | uuid NOT NULL FK examinations(id) ON DELETE CASCADE | |
| kind | recording_kind NOT NULL | `audio` asosiy; `spectrogram` va `waveform_image` — tizim hosil qiladi |
| status | recording_status NOT NULL DEFAULT 'uploading' | |
| site | auscultation_site NULL | audio uchun majburiy (kind='audio') |
| storage_key | text NOT NULL UNIQUE | `exams/{exam_id}/{recording_id}/original.wav` |
| derived_from_id | uuid NULL FK recordings(id) | spektrogramma qaysi audiodan |
| original_filename | varchar(255) NOT NULL | sanitizatsiyalangan |
| mime_type | varchar(100) NOT NULL | server aniqlagan (libmagic), klientniki emas |
| ext | varchar(8) NOT NULL | wav/mp3/flac/png/jpg |
| size_bytes | bigint NOT NULL | |
| sha256 | char(64) NOT NULL | dublikat va yaxlitlik uchun |
| duration_sec | numeric(7,3) NULL | |
| sample_rate_hz | int NULL | |
| channels | smallint NULL | |
| bit_depth | smallint NULL | |
| codec | varchar(30) NULL | `pcm_s16le`, `mp3`, `flac` |
| width_px, height_px | int NULL | tasvir uchun |
| quality_score | numeric(4,3) NULL | 0..1 (SNR asosida) |
| snr_db | numeric(5,2) NULL | |
| validation_report | jsonb NOT NULL DEFAULT '{}' | tekshiruv natijalari, rad etish sababi |
| scan_status | varchar(16) NOT NULL DEFAULT 'pending' | `pending/clean/infected/skipped/error` |
| uploaded_by | uuid NOT NULL FK users(id) | |
| created_at, updated_at, deleted_at | timestamptz | |

Indekslar: `(examination_id, kind)`, `UNIQUE(storage_key)`, `(sha256)`, `(examination_id, site) WHERE kind='audio' AND deleted_at IS NULL`.
CHECK: `kind <> 'audio' OR (site IS NOT NULL)`; `size_bytes > 0`.

### 1.8 `analysis_jobs` (fon vazifa holati)

| ustun | tur | izoh |
|---|---|---|
| id | uuid PK | |
| examination_id | uuid NOT NULL FK | |
| status | job_status NOT NULL DEFAULT 'pending' | |
| stage | varchar(32) NOT NULL DEFAULT 'queued' | `queued,validating,preprocessing,segmenting,features,classifying,spectrogram,llm_report,finalizing` |
| progress_pct | smallint NOT NULL DEFAULT 0 | 0..100 |
| celery_task_id | varchar(64) NULL | |
| attempt | smallint NOT NULL DEFAULT 1 | |
| max_attempts | smallint NOT NULL DEFAULT 3 | |
| error_code | varchar(40) NULL | |
| error_message | text NULL | |
| model_version | varchar(40) NULL | |
| requested_by | uuid NOT NULL FK users(id) | |
| started_at, finished_at | timestamptz NULL | |
| created_at | timestamptz | |

Indeks: `(examination_id, created_at DESC)`, `(status) WHERE status IN ('pending','running')`.

### 1.9 `analysis_results` (signal tahlili natijasi; tekshiruvga 1:1 joriy, tarix saqlanadi)

| ustun | tur | izoh |
|---|---|---|
| id | uuid PK | |
| examination_id | uuid NOT NULL FK | |
| job_id | uuid NOT NULL FK analysis_jobs(id) | |
| is_current | boolean NOT NULL DEFAULT true | qayta tahlilda eskisi false |
| model_version | varchar(40) NOT NULL | `pcg-cnn-1.0.0` yoki `rules-1.0.0` |
| pcg_class | pcg_class NOT NULL | |
| class_probs | jsonb NOT NULL | `{"normal":0.12,"murmur":0.81,"extra_heart_sound":0.04,"artifact":0.03}` |
| confidence | numeric(4,3) NOT NULL | 0..1 |
| severity | severity NOT NULL DEFAULT 'none' | |
| murmur_timing | murmur_timing NOT NULL DEFAULT 'none' | |
| murmur_grade | smallint NULL | Levine 1..6 (taxminiy) |
| murmur_shape | varchar(30) NULL | `crescendo,decrescendo,plateau,holosystolic` |
| heart_rate_bpm | numeric(5,1) NULL | signaldan hisoblangan |
| hr_variability_ms | numeric(7,2) NULL | RR std |
| s1_count, s2_count | int NULL | |
| mean_s1_s2_ms | numeric(7,2) NULL | |
| mean_s2_s1_ms | numeric(7,2) NULL | |
| systole_ms, diastole_ms | numeric(7,2) NULL | |
| dominant_freq_hz | numeric(7,2) NULL | |
| features | jsonb NOT NULL DEFAULT '{}' | MFCC statistikasi, spectral centroid, energy ratio va h.k. |
| quality_ok | boolean NOT NULL DEFAULT true | |
| quality_notes | text NULL | |
| waveform_key | text NULL | oldindan hisoblangan peaks JSON (wavesurfer) |
| spectrogram_recording_id | uuid NULL FK recordings(id) | |
| processing_ms | int NULL | |
| created_at | timestamptz | |

Indekslar: `UNIQUE(examination_id) WHERE is_current` (qisman unikal), `(pcg_class, created_at)`, `(severity)`, `(model_version)`, GIN `(class_probs jsonb_path_ops)` ixtiyoriy.
Eslatma: ko'p nuqtali tekshiruvda har audio uchun alohida natija emas — `features.per_recording[]` ichida, umumiy natija esa eng yomon (max severity) nuqta bo'yicha yig'iladi (`aggregation = "worst_site"`).

### 1.10 `pcg_segments`

Bir yozuvdagi aniqlangan tovush segmentlari (S1, S2, shovqin, vaqt oralig'i).

| ustun | tur | izoh |
|---|---|---|
| id | uuid PK | |
| analysis_result_id | uuid NOT NULL FK ON DELETE CASCADE | |
| recording_id | uuid NOT NULL FK recordings(id) | |
| seq | int NOT NULL | tartib raqami |
| type | segment_type NOT NULL | |
| start_ms | int NOT NULL | |
| end_ms | int NOT NULL | |
| cycle_no | int NULL | yurak sikli raqami |
| peak_amplitude | real NULL | normallashgan |
| energy | real NULL | |
| dominant_freq_hz | real NULL | |
| confidence | real NULL | |
| meta | jsonb NOT NULL DEFAULT '{}' | |

CHECK `end_ms > start_ms`. Indekslar: `(analysis_result_id, recording_id, start_ms)`, `(recording_id, type)`.

### 1.11 `ai_reports` (DeepSeek klinik izoh)

| ustun | tur | izoh |
|---|---|---|
| id | uuid PK | |
| examination_id | uuid NOT NULL FK | |
| analysis_result_id | uuid NOT NULL FK | |
| status | report_status NOT NULL DEFAULT 'generating' | |
| is_current | boolean NOT NULL DEFAULT true | |
| llm_provider | varchar(30) NOT NULL DEFAULT 'deepseek' | |
| llm_model | varchar(40) NOT NULL | `deepseek-chat` / `deepseek-reasoner` |
| prompt_version | varchar(20) NOT NULL | prompt shablon versiyasi |
| summary | text NOT NULL | qisqa xulosa |
| findings | jsonb NOT NULL | tuzilgan topilmalar (quyida sxema) |
| differential_diagnoses | jsonb NOT NULL | `[{"name":"Mitral regurgitation","icd10":"I34.0","likelihood":"high","rationale":"..."}]` |
| recommended_tests | jsonb NOT NULL DEFAULT '[]' | `["Exo-KG","EKG","Troponin"]` |
| red_flags | jsonb NOT NULL DEFAULT '[]' | shoshilinch belgilar |
| patient_friendly_text | text NULL | bemor uchun sodda izoh (shifokor tasdiqlagach ko'rinadi) |
| disclaimer | text NOT NULL | majburiy "AI faqat qo'llab-quvvatlash" matni |
| input_snapshot | jsonb NOT NULL | LLM'ga yuborilgan anonimlashtirilgan kirish (PII'siz) |
| raw_response | jsonb NULL | xom javob (faqat admin ko'radi, 90 kun) |
| prompt_tokens, completion_tokens | int NULL | |
| latency_ms | int NULL | |
| cost_usd | numeric(8,5) NULL | |
| error_message | text NULL | |
| created_at | timestamptz | |

`findings` sxemasi: `{"heart_sounds":"S1 normal, S2 fiziologik bo'linish","murmur":{"present":true,"timing":"systolic","grade":"3/6","location":"mitral","radiation":"qo'ltiq osti"},"rhythm":"regulyar","quality":"yaxshi"}`.
Indekslar: `UNIQUE(examination_id) WHERE is_current`, `(analysis_result_id)`, `(created_at)`.
PII siyosati: LLM'ga ism, telefon, JShShIR, manzil YUBORILMAYDI; faqat yosh, jins, anamnez kodlari, allergiya/dori nomlari, vitallar, signal xususiyatlari yuboriladi.

### 1.12 `prescriptions` va `drug_recommendations`

`prescriptions` — bitta tekshiruv bo'yicha dori buyurish varaqasi (AI taklifi + shifokor tahriri):

| ustun | tur | izoh |
|---|---|---|
| id | uuid PK | |
| examination_id | uuid NOT NULL FK | |
| patient_id | uuid NOT NULL FK | denormal, tez filtr uchun |
| ai_report_id | uuid NULL FK ai_reports(id) | AI taklifi manbai |
| status | prescription_status NOT NULL DEFAULT 'suggested' | |
| prescribed_by | uuid NULL FK users(id) | tasdiqlagan shifokor |
| approved_at | timestamptz NULL | |
| safety_check | jsonb NOT NULL DEFAULT '{}' | `{"allergy_conflicts":[],"interactions":[],"contraindications":[],"checked_at":"..."}` |
| doctor_notes | text NULL | |
| version | int NOT NULL DEFAULT 1 | |
| created_at, updated_at | timestamptz | |

`drug_recommendations` (satrlar):

| ustun | tur | izoh |
|---|---|---|
| id | uuid PK | |
| prescription_id | uuid NOT NULL FK ON DELETE CASCADE | |
| source | varchar(10) NOT NULL | `ai` yoki `doctor` |
| drug_name | varchar(160) NOT NULL | |
| inn_code | varchar(64) NULL | |
| atc_code | varchar(10) NULL | |
| dose | varchar(60) NOT NULL | |
| route | varchar(30) NOT NULL | |
| frequency | varchar(80) NOT NULL | |
| duration_days | smallint NULL | |
| instructions | text NULL | |
| rationale | text NULL | nega tavsiya |
| contraindications | text[] NOT NULL DEFAULT '{}' | |
| side_effects | text[] NOT NULL DEFAULT '{}' | |
| interaction_warnings | jsonb NOT NULL DEFAULT '[]' | |
| allergy_warning | boolean NOT NULL DEFAULT false | |
| status | prescription_status NOT NULL DEFAULT 'suggested' | satr bo'yicha alohida approve/reject |
| sort_order | smallint NOT NULL DEFAULT 0 | |
| created_at, updated_at | timestamptz | |

Indekslar: `(examination_id)`, `(patient_id, status)`, `(prescription_id, sort_order)`.
Qoida: `allergy_warning=true` satr `approved` bo'lishi uchun shifokor `override_reason` kiritishi shart (API'da `override_reason`, `safety_check.overrides` ichida saqlanadi).

### 1.13 `doctor_conclusions`

| ustun | tur | izoh |
|---|---|---|
| id | uuid PK | |
| examination_id | uuid NOT NULL FK | |
| doctor_id | uuid NOT NULL FK users(id) | |
| status | conclusion_status NOT NULL DEFAULT 'draft' | |
| diagnosis_text | text NOT NULL | |
| icd10_codes | text[] NOT NULL DEFAULT '{}' | |
| final_pcg_class | pcg_class NOT NULL | shifokorning yakuniy bahosi |
| final_severity | severity NOT NULL | |
| agreement_with_ai | agreement_level NOT NULL | AI bilan mos kelishi (shifokor tanlaydi; analitika uchun asos) |
| disagreement_reason | text NULL | `disagree/partial` bo'lsa majburiy |
| recommendations | text NOT NULL | |
| follow_up_date | date NULL | |
| follow_up_notes | text NULL | |
| referred_to | varchar(160) NULL | yo'llanma |
| signed_at | timestamptz NULL | |
| signature_hash | char(64) NULL | imzolangan matnning SHA-256 (yaxlitlik) |
| amends_id | uuid NULL FK doctor_conclusions(id) | tuzatish (amendment) zanjiri |
| is_current | boolean NOT NULL DEFAULT true | |
| version | int NOT NULL DEFAULT 1 | |
| created_at, updated_at | timestamptz | |

Indekslar: `UNIQUE(examination_id) WHERE is_current`, `(doctor_id, signed_at DESC)`, `(agreement_with_ai, signed_at)`, `(final_pcg_class)`.
Imzolangan (`signed`) yozuv o'zgartirilmaydi — faqat `amended` yangi qator (amends_id) sifatida yaratiladi.

### 1.14 `notifications`

| ustun | tur | izoh |
|---|---|---|
| id | uuid PK | |
| user_id | uuid NOT NULL FK ON DELETE CASCADE | qabul qiluvchi |
| type | notification_type NOT NULL | |
| title | varchar(160) NOT NULL | |
| body | text NULL | |
| payload | jsonb NOT NULL DEFAULT '{}' | `{"examination_id":"...","patient_id":"..."}` |
| is_read | boolean NOT NULL DEFAULT false | |
| read_at | timestamptz NULL | |
| created_at | timestamptz | |

Indekslar: `(user_id, is_read, created_at DESC)`, `(user_id, created_at DESC)`. Tozalash: o'qilgan 90 kundan keyin.

### 1.15 `audit_logs` (faqat INSERT; append-only)

| ustun | tur | izoh |
|---|---|---|
| id | bigint GENERATED ALWAYS AS IDENTITY PK | |
| ts | timestamptz NOT NULL DEFAULT now() | |
| user_id | uuid NULL | kim (login_failed'da NULL) |
| username_snapshot | varchar(32) NULL | |
| role_snapshot | user_role NULL | |
| action | audit_action NOT NULL | |
| resource_type | varchar(40) NULL | `patient`,`examination`,`recording`,`ai_report`,`prescription`,... |
| resource_id | uuid NULL | |
| patient_id | uuid NULL | bemor kesimida kirish tarixi uchun |
| ip | inet NULL | |
| user_agent | varchar(300) NULL | |
| request_id | varchar(40) NULL | |
| method | varchar(8) NULL | |
| path | varchar(300) NULL | |
| status_code | smallint NULL | |
| success | boolean NOT NULL DEFAULT true | |
| changes | jsonb NULL | `{"before":{...},"after":{...}}` (PII maydonlar maskalanadi) |
| meta | jsonb NOT NULL DEFAULT '{}' | AI chaqiruvi: model, tokens, latency |

Himoya: DB rolida `UPDATE/DELETE/TRUNCATE` huquqi yo'q (`REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM app_user`), qo'shimcha trigger `RAISE EXCEPTION`. Partitsiya: `PARTITION BY RANGE (ts)` oylik (pg_partman yoki Alembic job).
Indekslar: `(ts DESC)`, `(user_id, ts DESC)`, `(patient_id, ts DESC) WHERE patient_id IS NOT NULL`, `(resource_type, resource_id)`, `(action, ts DESC)`, `(request_id)`.

### 1.16 `system_settings`

Kalit-qiymat (admin boshqaradi). Sirlar (API kalitlar) bu yerda SAQLANMAYDI.

| ustun | tur | izoh |
|---|---|---|
| key | varchar(80) PK | |
| value | jsonb NOT NULL | |
| value_type | varchar(12) NOT NULL | `int,float,bool,string,json` |
| description | text NULL | |
| is_public | boolean NOT NULL DEFAULT false | frontend `/settings/public` orqali o'qiydi |
| updated_by | uuid NULL FK users(id) | |
| updated_at | timestamptz | |

Boshlang'ich kalitlar (migratsiya seed'i, parol/sir emas):

| key | default | ma'no |
|---|---|---|
| `upload.max_audio_mb` | 25 | |
| `upload.max_image_mb` | 10 | |
| `upload.max_files_per_exam` | 12 | |
| `audio.min_duration_sec` | 5 | |
| `audio.max_duration_sec` | 120 | |
| `analysis.auto_start` | true | yuklagach avtomatik navbatga |
| `analysis.model_version` | "pcg-cnn-1.0.0" | |
| `ai.llm_model` | "deepseek-chat" | |
| `ai.llm_enabled` | true | o'chirilsa faqat signal natijasi |
| `ai.drug_suggestions_enabled` | true | |
| `ai.critical_probability_threshold` | 0.85 | critical_finding bildirishnomasi |
| `security.lockout_attempts` | 5 | |
| `security.lockout_minutes` | 15 | |
| `security.password_min_length` | 10 | |
| `retention.audit_days` | 1825 | |
| `retention.raw_llm_days` | 90 | |
| `clinic.name`, `clinic.logo_key`, `clinic.report_footer` | | PDF uchun |

### 1.17 Yordamchi jadvallar

- `export_jobs(id uuid PK, user_id, kind varchar(30), params jsonb, format export_format, status job_status, file_key text, size_bytes bigint, error text, created_at, finished_at, expires_at)` — katta eksportlar uchun (CSV >10 000 qator).
- `password_reset_tokens(id, user_id, token_hash char(64) UNIQUE, expires_at, used_at, created_at)` — admin yaratgan bir martalik havola (30 daqiqa).
- `idempotency_keys(key varchar(64), user_id uuid, endpoint varchar(100), response_hash char(64), status_code smallint, created_at; PK(key,user_id))` — `Idempotency-Key` sarlavhasi (upload, analyze, sign).
- `exam_status_history(id bigint identity, examination_id uuid, from_status exam_status NULL, to_status exam_status, changed_by uuid NULL, reason text NULL, created_at)` — state machine tarixi. Indeks `(examination_id, created_at)`.
- Sequences: `patient_mrn_seq`, `exam_daily_seq` (kunlik reset — `exam_counters(day date PK, last int)` bilan `UPDATE ... RETURNING`).

### 1.18 ER aloqalari (qisqacha)

```
users 1—* refresh_tokens
patients 1—* medical_history | allergies | current_medications | examinations
examinations 1—* recordings | analysis_jobs | analysis_results | ai_reports | prescriptions | doctor_conclusions | exam_status_history
analysis_results 1—* pcg_segments
recordings 1—* pcg_segments;  recordings(audio) 1—* recordings(spectrogram) via derived_from_id
prescriptions 1—* drug_recommendations
users 1—* notifications | audit_logs
```

---

## 2. RBAC ruxsatlar matritsasi

Rollar: `admin` (tizim va foydalanuvchilar, analitika; klinik ma'lumotni o'qiy oladi, lekin klinik xulosa imzolamaydi), `doctor` (to'liq klinik ish), `nurse` (qabul, yozuv yuklash, anamnez; AI natijasini faqat o'qiydi).

Belgilar: R=o'qish, C=yaratish, U=tahrirlash, D=o'chirish(soft), A=maxsus amal, `own`=faqat o'ziniki, `-`=taqiqlangan.

| Resurs / amal | admin | doctor | nurse |
|---|---|---|---|
| users: list/create/update/suspend/reset-password | R C U D A | `-` (o'z profilini R/U) | `-` (o'z profilini R/U) |
| users: shifokorlar ro'yxati (assign uchun, minimal maydon) | R | R | R |
| patients | R C U D | R C U D(soft) | R C U (D `-`) |
| patients: JShShIR (national_id) ochiq ko'rish | R | R | `-` (maska `****`) |
| medical_history / allergies / current_medications | R C U D | R C U D | R C U (D `-`) |
| examinations: create | C | C | C |
| examinations: list/read | R (hammasi) | R (hammasi; `?mine=true` filtri) | R (own + o'zi yaratgan bemorlariniki) |
| examinations: update (vitallar, shikoyat) | U | U | U (faqat `draft/uploaded` va o'zi yaratgan) |
| examinations: assign doctor | A | A (o'ziga) | A (shifokorga yo'naltirish) |
| examinations: cancel | A | A | A (faqat `draft/uploaded`, own) |
| recordings: upload | C | C | C |
| recordings: download/stream | R | R | R |
| recordings: delete | D | D (faqat `completed` bo'lmagan) | D (own, `draft/uploaded` holatida) |
| analysis: start / re-run | A | A | A (start; re-run `-`) |
| analysis_results / pcg_segments | R | R | R |
| ai_reports: read | R | R | R (`patient_friendly_text` va dori bo'limisiz, `red_flags` ko'rinadi) |
| ai_reports: regenerate | A | A | `-` |
| prescriptions / drug_recommendations: read | R | R C U | `-` (faqat `approved` va yakuniy shifokor imzolagach, o'qish) |
| prescriptions: approve/reject | `-` | A | `-` |
| doctor_conclusions: read | R | R | R (faqat `signed`) |
| doctor_conclusions: create/update/sign | `-` | C U A (faqat tayinlangan yoki admin tayinlamagan bo'lsa istalgan) | `-` |
| notifications (o'zining) | R U | R U | R U |
| analytics: admin dashboard | R | `-` | `-` |
| analytics: doctor dashboard | R (`?doctor_id=`) | R (own) | `-` |
| analytics: nurse (o'z ish hajmi) | R | `-` | R (own) |
| audit_logs | R (hammasi) | R (o'z amallari) | `-` |
| system_settings | R U | R (public) | R (public) |
| export: PDF hisobot | A | A | A (faqat `completed` va signed) |
| export: CSV (tekshiruvlar, bemorlar) | A | A (own scope) | `-` |
| export: audit CSV | A | `-` | `-` |
| WebSocket/SSE | barcha o'z kanallari | o'z kanallari + `role:doctor` | o'z kanallari |

Amalga oshirish:
- Dependency: `require_roles(*roles)` (FastAPI `Depends`), obyekt darajasida `policy.can(user, action, obj)` (`app/core/permissions.py`, `PERMISSIONS: dict[Role, set[Permission]]` + obyekt qoidalari). Ruxsat nomlari: `patient:read`, `patient:write`, `exam:create`, `exam:assign`, `exam:cancel`, `recording:upload`, `analysis:start`, `analysis:rerun`, `report:read`, `report:regenerate`, `prescription:read`, `prescription:write`, `prescription:approve`, `conclusion:write`, `conclusion:sign`, `conclusion:read_signed`, `analytics:admin`, `analytics:doctor`, `analytics:nurse`, `audit:read`, `audit:read_own`, `user:manage`, `settings:write`, `export:pdf`, `export:csv`, `export:audit`.
- Har rad etilgan so'rov `audit_logs(action='permission_denied')` ga yoziladi.
- Nurse javoblarida maydon-darajasida filtr: Pydantic `response_model` variantlari (`ExaminationOutNurse`, `AiReportOutNurse`), `national_id` maskalanadi.

---

## 3. REST API

Hamma yo'llar `/api/v1` prefiksi ostida. Auth: `Authorization: Bearer <access_jwt>` (aks holda belgilangan). Mutatsion so'rovlarda ixtiyoriy `Idempotency-Key`. Pagination/filter/sort konventsiyasi — 3.14.

### 3.1 Auth

#### `POST /auth/login` — auth: yo'q

Rate limit: IP bo'yicha 10/daq, username bo'yicha 5/daq.

```json
// request
{"username": "dr.karimov", "password": "S3cure-Pass-2026"}
// 200 response (refresh token httpOnly cookie sifatida: Set-Cookie: cp_refresh=...; HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth; Max-Age=604800)
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {"id":"0192...","username":"dr.karimov","full_name":"Karimov Aziz","role":"doctor","locale":"uz","must_change_password":false}
}
```
Xatolar: `401 INVALID_CREDENTIALS` (username yoki parol — bir xil xabar), `423 ACCOUNT_LOCKED` (`{"locked_until":"..."}`), `403 ACCOUNT_SUSPENDED`, `429 RATE_LIMITED`.
Tartib: username bo'yicha topish -> hisob holati -> argon2 verify (foydalanuvchi topilmasa ham soxta hash bilan verify — timing hujumi oldini olish) -> `failed_login_count` yangilash -> token berish -> audit.

#### `POST /auth/refresh` — auth: refresh cookie
Cookie'dagi tokenni tekshiradi, rotation: eski `used_at` belgilanadi, yangi refresh (shu `family_id`) cookie'ga yoziladi, yangi access qaytadi.
```json
// 200
{"access_token":"eyJ...","token_type":"bearer","expires_in":900}
```
Xatolar: `401 REFRESH_INVALID`, `401 REFRESH_EXPIRED`, `401 TOKEN_REUSE_DETECTED` (ishlatilgan token qayta keldi -> butun `family_id` bekor, audit `token_reuse_detected`, cookie tozalanadi). Grace: 10 soniya ichida bir xil tokenning ikkinchi marta kelishi (parallel tab) reuse hisoblanmaydi, xuddi shu yangi tokenni qaytaradi (Redis `refresh:grace:{hash}`).

#### `POST /auth/logout` — Bearer
Joriy refresh oilasini bekor qiladi, cookie o'chiriladi. `204`.

#### `POST /auth/logout-all` — Bearer
Foydalanuvchining barcha faol refresh tokenlari bekor. `204`.

#### `GET /auth/me` — Bearer
```json
{"id":"0192...","username":"dr.karimov","full_name":"Karimov Aziz","role":"doctor","email":"a@clinic.uz","phone":"+998901234567","specialty":"Kardiolog","locale":"uz","permissions":["patient:read","patient:write","analysis:start","conclusion:sign"],"last_login_at":"2026-11-18T08:00:00Z","must_change_password":false}
```

#### `PATCH /auth/me` — Bearer
Faqat `full_name, phone, email, locale, avatar` (avatar alohida `POST /auth/me/avatar`, multipart, png/jpg ≤2 MB).

#### `POST /auth/change-password` — Bearer
```json
{"current_password":"old","new_password":"N3w-Long-Pass-2026"}
```
`204`. Yangi parol: min 10 belgi, zxcvbn score ≥3, oxirgi 5 parol bilan bir xil emas (`password_history` kerak bo'lsa `users.password_history jsonb` — hash ro'yxati). Barcha refresh'lar bekor qilinadi (joriysidan tashqari). Xato: `400 WEAK_PASSWORD`, `400 WRONG_CURRENT_PASSWORD`.

#### `POST /auth/reset-password` — auth: yo'q (admin bergan token bilan)
```json
{"token":"<one-time>","new_password":"..."}
```
`204`; `400 TOKEN_INVALID_OR_EXPIRED`.

### 3.2 Users (admin)

| Metod | Yo'l | Ruxsat | Tavsif |
|---|---|---|---|
| GET | `/users` | admin | list; filtr: `role`, `status`, `q`; sort: `full_name,created_at,last_login_at` |
| POST | `/users` | admin | yaratish |
| GET | `/users/{id}` | admin | |
| PATCH | `/users/{id}` | admin | `full_name, role, status, phone, email, specialty, license_no, department` |
| POST | `/users/{id}/reset-password` | admin | bir martalik havola/vaqtinchalik parol (`must_change_password=true`) |
| POST | `/users/{id}/suspend` / `/activate` | admin | `suspend`'da barcha refresh bekor |
| POST | `/users/{id}/unlock` | admin | `locked_until` ni tozalaydi |
| DELETE | `/users/{id}` | admin | soft delete (o'zini o'chira olmaydi, oxirgi adminni ham) |
| GET | `/users/doctors` | hamma rol | minimal ro'yxat `[{id, full_name, specialty}]` (faqat faol) |

`POST /users`:
```json
{"username":"nurse.aliyeva","full_name":"Aliyeva Dilnoza","role":"nurse","email":null,"phone":"+998935550011","password":"Tmp-Pass-2026!","must_change_password":true}
// 201
{"id":"0192...","username":"nurse.aliyeva","full_name":"Aliyeva Dilnoza","role":"nurse","status":"active","must_change_password":true,"created_at":"2026-11-18T09:00:00Z"}
```
Xatolar: `409 USERNAME_TAKEN`, `409 EMAIL_TAKEN`, `400 WEAK_PASSWORD`, `409 LAST_ADMIN` (oxirgi adminni o'chirish/rol o'zgartirish).

### 3.3 Patients

#### `GET /patients`
Filtr: `q` (ism/familiya/MRN/telefon trgm), `gender`, `age_min`, `age_max`, `primary_doctor_id`, `has_allergies`, `created_from`, `created_to`, `is_active`. Sort: `last_name,birth_date,created_at,last_exam_at` (default `-created_at`).
```json
{
  "items":[{"id":"0192...","mrn":"P-2026-000123","full_name":"Rahimov Jasur Anvarovich","birth_date":"1975-04-12","age":51,"gender":"male","phone":"+998901112233","primary_doctor":{"id":"...","full_name":"Karimov Aziz"},"last_exam_at":"2026-11-10T08:15:00Z","exam_count":4,"has_allergies":true}],
  "page":{"limit":20,"next_cursor":"eyJ...","total":412}
}
```

#### `POST /patients`
```json
{
  "last_name":"Rahimov","first_name":"Jasur","middle_name":"Anvarovich",
  "birth_date":"1975-04-12","gender":"male","phone":"+998901112233",
  "national_id":"31204755550012","blood_group":"A+","height_cm":176,"weight_kg":84.5,
  "address":"Toshkent sh., Chilonzor","primary_doctor_id":"0192...",
  "emergency_contact_name":"Rahimova Malika","emergency_contact_phone":"+998901119999"
}
// 201 -> to'liq patient obyekti (id, mrn, age, bmi, ...)
```
Xatolar: `422` (sana kelajakda, height/weight oralig'i), `409 PATIENT_DUPLICATE` (`national_id_hash` bor; javobda mavjud `patient_id`), `409 POSSIBLE_DUPLICATE` (ism+tug'ilgan sana bir xil — `?force=true` bilan o'tkazish).

#### `GET /patients/{id}`
To'liq obyekt + `allergies[]`, `medical_history[]`, `current_medications[]`, `stats:{exam_count,last_exam_at,last_pcg_class}`.

#### `PATCH /patients/{id}` (`If-Match`) — qisman yangilash. `DELETE /patients/{id}` — soft delete (faqat admin/doctor; faol tekshiruvi bor bo'lsa `409 PATIENT_HAS_ACTIVE_EXAMS`). `POST /patients/{id}/restore` — admin.

#### `GET /patients/{id}/timeline`
Tekshiruvlar, xulosalar, dori tayinlari kronologiyasi (kursor pagination).
```json
{"items":[{"ts":"2026-11-10T08:15:00Z","type":"examination","exam_id":"...","exam_no":"E-20261110-0007","pcg_class":"murmur","severity":"moderate","status":"completed"}],"page":{"limit":20,"next_cursor":null}}
```

#### `GET /patients/{id}/audit` — admin: bemor yozuviga kim kirgani.

Anamnez, allergiya, dorilar (CRUD):

| Metod | Yo'l |
|---|---|
| GET/POST | `/patients/{id}/history` |
| PATCH/DELETE | `/patients/{id}/history/{hid}` |
| GET/POST | `/patients/{id}/allergies` |
| PATCH/DELETE | `/patients/{id}/allergies/{aid}` |
| GET/POST | `/patients/{id}/medications` |
| PATCH/DELETE | `/patients/{id}/medications/{mid}` |

```json
// POST /patients/{id}/allergies
{"substance":"Penitsillin","substance_code":"J01C","reaction":"Toshma, qichishish","severity":"severe","noted_date":"2019-05-01"}
// 201
{"id":"...","patient_id":"...","substance":"Penitsillin","severity":"severe","is_active":true}
```
`DELETE` — `is_active=false` (arxivlash), nurse o'chira olmaydi (`403`). Allergiya/dori o'zgarganda, shu bemorning `suggested` retseptlari uchun `safety_check` qayta hisoblanadi.

### 3.4 Examinations

#### `POST /examinations`
```json
{
  "patient_id":"0192...",
  "priority":"routine",
  "complaints":"Nafas qisilishi, zinapoyada ko'tarilganda",
  "symptoms":["dyspnea","palpitations"],
  "patient_position":"sitting",
  "heart_rate_bpm":88,"bp_systolic":135,"bp_diastolic":85,"spo2_pct":97,"temperature_c":36.6,
  "assigned_doctor_id":"0192..."
}
// 201
{"id":"0192...","exam_no":"E-20261118-0042","status":"draft","patient_id":"...","priority":"routine","performed_by":{"id":"...","full_name":"Aliyeva Dilnoza"},"examined_at":"2026-11-18T09:30:00Z","recordings":[],"version":1}
```

#### `GET /examinations`
Filtr: `status` (ko'p: `status=ai_ready&status=in_review`), `priority`, `patient_id`, `assigned_doctor_id`, `performed_by`, `mine=true`, `pcg_class`, `severity`, `agreement`, `examined_from`, `examined_to`, `q` (exam_no, bemor ismi/MRN), `needs_review=true` (`ai_ready|in_review`). Sort: `examined_at,priority,status,created_at,severity` (priority sort — maxsus: emergency>urgent>routine).
```json
{"items":[{"id":"...","exam_no":"E-20261118-0042","patient":{"id":"...","mrn":"P-2026-000123","full_name":"Rahimov Jasur","age":51,"gender":"male"},"status":"ai_ready","priority":"urgent","examined_at":"...","assigned_doctor":{"id":"...","full_name":"Karimov Aziz"},"performed_by":{"id":"...","full_name":"Aliyeva Dilnoza"},"recording_count":3,"ai":{"pcg_class":"murmur","severity":"moderate","confidence":0.87},"conclusion_status":null}],"page":{"limit":20,"next_cursor":"...","total":97}}
```

#### `GET /examinations/{id}`
Tekshiruv + bemor qisqacha + recordings[] (har biri `url`: imzolangan vaqtinchalik havola) + `analysis` (joriy natija xulosasi) + `report` (nurse uchun cheklangan) + `prescription` (doctor/admin) + `conclusion` + `status_history[]`.

#### `PATCH /examinations/{id}` (`If-Match`)
Vitallar, shikoyat, `priority`, `assigned_doctor_id`. Status o'zgarmaydi (faqat amallar orqali). `409 INVALID_STATE` agar `status in (processing, completed, cancelled)` va maydon klinik bo'lsa.

#### `POST /examinations/{id}/assign` — `{"doctor_id":"0192..."}` -> `200`, notification `assignment`.
#### `POST /examinations/{id}/cancel` — `{"reason":"Bemor ketdi"}` -> `200`; `409 INVALID_STATE`.
#### `DELETE /examinations/{id}` — soft delete: faqat admin, faqat `draft/cancelled/failed`.

#### `POST /examinations/{id}/analyze`
Tahlilni navbatga qo'yadi (3.6 ga qarang). Idempotent: `Idempotency-Key`.
```json
// request (ixtiyoriy)
{"force_rerun": false, "llm": true, "drug_suggestions": true}
// 202 Accepted
{"job_id":"0192...","status":"pending","exam_status":"queued","events":"/api/v1/examinations/0192.../events"}
```
Xatolar: `409 INVALID_STATE` (`draft`, yoki allaqachon `processing`), `422 NO_AUDIO_RECORDINGS`, `422 RECORDINGS_NOT_VALIDATED`, `403` (nurse `force_rerun`).

#### `POST /examinations/{id}/reanalyze` — doctor/admin: `completed` bo'lmagan `ai_ready/in_review/failed` holatdan qayta ishga tushiradi; eski natija `is_current=false`.

#### `GET /examinations/{id}/status`
```json
{"status":"processing","job":{"id":"...","stage":"classifying","progress_pct":62,"attempt":1,"started_at":"..."},"history":[{"from":"uploaded","to":"queued","at":"...","by":"..."}]}
```

#### `GET /examinations/{id}/events` — SSE (7-bo'lim).

### 3.5 Recordings (fayl yuklash)

| Metod | Yo'l | Tavsif |
|---|---|---|
| POST | `/examinations/{id}/recordings` | multipart yuklash |
| GET | `/examinations/{id}/recordings` | ro'yxat |
| GET | `/recordings/{rid}` | metadata |
| GET | `/recordings/{rid}/file` | oqim/yuklab olish (Range qo'llab-quvvatlanadi, `206`) |
| GET | `/recordings/{rid}/waveform` | wavesurfer uchun peaks JSON (`{"sample_rate":..., "samples_per_pixel":..., "data":[...]}`) |
| GET | `/recordings/{rid}/spectrogram` | PNG (tahlildan keyin) |
| PATCH | `/recordings/{rid}` | `site` o'zgartirish |
| DELETE | `/recordings/{rid}` | soft delete (statusga bog'liq) |

`POST /examinations/{id}/recordings` — `multipart/form-data`:
- `file` (majburiy), `site` (audio uchun majburiy: `aortic|pulmonic|erb|tricuspid|mitral|apex|carotid|other`), `kind` (`audio` default yoki `other_image`), `notes` (ixtiyoriy).
- Bir so'rovda 1 fayl (ko'p fayl — ketma-ket/parallel so'rovlar; klient progressni `XMLHttpRequest`/axios orqali oladi).
```json
// 201
{"id":"0192...","examination_id":"...","kind":"audio","site":"mitral","status":"validated","original_filename":"mitral_01.wav","mime_type":"audio/wav","size_bytes":2646044,"sha256":"9f2c...","duration_sec":15.0,"sample_rate_hz":44100,"channels":1,"bit_depth":16,"snr_db":24.3,"quality_score":0.82,"validation_report":{"warnings":[]},"url":"/api/v1/recordings/0192.../file","created_at":"..."}
```
Xatolar: `413 FILE_TOO_LARGE`, `415 UNSUPPORTED_MEDIA_TYPE`, `422 AUDIO_TOO_SHORT|AUDIO_TOO_LONG|AUDIO_CORRUPT|AUDIO_SILENT|AUDIO_CLIPPED`, `409 DUPLICATE_RECORDING` (shu tekshiruvda bir xil sha256), `409 SITE_ALREADY_RECORDED` (`?replace=true` bilan almashtirish), `409 INVALID_STATE` (tekshiruv `processing/completed`), `422 TOO_MANY_FILES`, `422 INFECTED_FILE`.
Yuklashdan keyin exam `draft -> uploaded` (birinchi validated audio'dan so'ng).

### 3.6 Tahlil natijalari, segmentlar, AI hisobot

| Metod | Yo'l | Ruxsat | Tavsif |
|---|---|---|---|
| GET | `/examinations/{id}/analysis` | hamma | joriy `analysis_results` |
| GET | `/examinations/{id}/analysis/history` | doctor/admin | barcha versiyalar |
| GET | `/examinations/{id}/segments?recording_id=&type=` | hamma | `pcg_segments` |
| GET | `/examinations/{id}/report` | hamma (nurse cheklangan) | joriy `ai_reports` |
| POST | `/examinations/{id}/report/regenerate` | doctor/admin | faqat LLM qismini qayta yaratish |
| GET | `/examinations/{id}/report/history` | doctor/admin | |

`GET /examinations/{id}/analysis`:
```json
{
  "id":"0192...","model_version":"pcg-cnn-1.0.0","pcg_class":"murmur",
  "class_probs":{"normal":0.09,"murmur":0.84,"extra_heart_sound":0.04,"artifact":0.03},
  "confidence":0.84,"severity":"moderate","murmur_timing":"systolic","murmur_grade":3,"murmur_shape":"holosystolic",
  "heart_rate_bpm":86.4,"hr_variability_ms":18.2,"s1_count":21,"s2_count":21,
  "mean_s1_s2_ms":312.5,"mean_s2_s1_ms":384.1,"systole_ms":312.5,"diastole_ms":384.1,"dominant_freq_hz":145.0,
  "quality_ok":true,"quality_notes":null,"processing_ms":4210,
  "recordings":[{"recording_id":"...","site":"mitral","pcg_class":"murmur","confidence":0.84,"spectrogram_url":"/api/v1/recordings/.../spectrogram"}],
  "created_at":"2026-11-18T09:35:00Z"
}
```
`GET /examinations/{id}/segments`:
```json
{"items":[{"id":"...","recording_id":"...","seq":1,"type":"S1","start_ms":120,"end_ms":180,"cycle_no":1,"peak_amplitude":0.71,"confidence":0.94},{"seq":2,"type":"systole","start_ms":180,"end_ms":490,"cycle_no":1},{"seq":3,"type":"murmur","start_ms":210,"end_ms":470,"cycle_no":1,"dominant_freq_hz":160}]}
```
`GET /examinations/{id}/report` (doctor/admin to'liq):
```json
{
  "id":"...","status":"ready","llm_model":"deepseek-chat","prompt_version":"v3",
  "summary":"Mitral nuqtada holosistolik shovqin aniqlandi (3/6 ga mos), S1 susaygan.",
  "findings":{"heart_sounds":"S1 susaygan, S2 fiziologik ajralgan","murmur":{"present":true,"timing":"systolic","grade":"3/6","location":"mitral","radiation":"qo'ltiq osti"},"rhythm":"regulyar","quality":"yaxshi"},
  "differential_diagnoses":[{"name":"Mitral yetishmovchilik","icd10":"I34.0","likelihood":"high","rationale":"Holosistolik shovqin, apeksda maksimum, qo'ltiq ostiga tarqalish"},{"name":"Mitral klapan prolapsi","icd10":"I34.1","likelihood":"medium","rationale":"Klik mavjudligi tasdiqlanmagan"}],
  "recommended_tests":["Exo-KG","EKG","Ko'krak qafasi rentgeni"],
  "red_flags":[],
  "patient_friendly_text":"Yurak tovushingizda qo'shimcha shovqin aniqlandi. Aniq tashxis uchun shifokor ko'rigi va Exo-KG tavsiya etiladi.",
  "disclaimer":"Bu natija sun'iy intellekt tomonidan hosil qilingan qaror qo'llab-quvvatlash vositasi; yakuniy tashxisni shifokor qo'yadi.",
  "created_at":"..."
}
```
Nurse uchun `differential_diagnoses`, `patient_friendly_text`, retsept ko'rinmaydi (faqat `summary`, `findings`, `red_flags`, `disclaimer`). Bemorga ko'rinadigan matn faqat shifokor imzolagandan keyin (`conclusion.status='signed'`) ochiladi.

### 3.7 Prescriptions / dori tavsiyalari

| Metod | Yo'l | Ruxsat | Tavsif |
|---|---|---|---|
| GET | `/examinations/{id}/prescription` | doctor/admin (nurse: faqat approved+signed) | |
| POST | `/examinations/{id}/prescription/items` | doctor | qo'lda dori qo'shish (`source='doctor'`) |
| PATCH | `/prescription-items/{iid}` | doctor | doza/chastota/davomiylik tahriri |
| DELETE | `/prescription-items/{iid}` | doctor | |
| POST | `/prescription-items/{iid}/approve` | doctor | `{"override_reason":"..."}` allergiya ogohlantirishi bo'lsa majburiy |
| POST | `/prescription-items/{iid}/reject` | doctor | `{"reason":"..."}` |
| POST | `/examinations/{id}/prescription/approve` | doctor | hamma `suggested` satrlarni (ogohlantirishsizlarni) birdan tasdiqlash |
| POST | `/examinations/{id}/prescription/safety-check` | doctor | allergiya/interaction/qarshi ko'rsatma tekshiruvini qayta ishga tushiradi |
| POST | `/examinations/{id}/prescription/regenerate` | doctor | AI dori taklifini qayta so'rash |

```json
// GET /examinations/{id}/prescription
{
  "id":"...","status":"suggested","disclaimer":"AI taklifi. Faqat ma'lumot uchun; shifokor tasdiqlaydi.",
  "safety_check":{"checked_at":"...","allergy_conflicts":[{"item_id":"...","allergen":"Penitsillin","severity":"severe"}],"interactions":[{"items":["Varfarin","Aspirin"],"level":"major","note":"Qon ketish xavfi"}],"contraindications":[]},
  "items":[{"id":"...","source":"ai","drug_name":"Furosemid","inn_code":"furosemide","atc_code":"C03CA01","dose":"20 mg","route":"oral","frequency":"kuniga 1 marta ertalab","duration_days":14,"rationale":"Hajm yuklamasi belgilari","contraindications":["Anuriya","Gipokaliemiya"],"side_effects":["Gipokaliemiya","Dehidratatsiya"],"interaction_warnings":[],"allergy_warning":false,"status":"suggested"}]
}
```
Xatolar: `409 ALLERGY_OVERRIDE_REQUIRED`, `409 INVALID_STATE` (xulosa imzolangan, tahrir `amend` orqali), `403`.
Xavfsizlik tekshiruvi (`services/drug_safety.py`): (1) allergiya — `inn_code/ATC sinfi` va `allergies.substance_code` mosligi (kross-sinf: penitsillin–sefalosporin ogohlantirish), (2) `current_medications` bilan o'zaro ta'sir (lokal jadval `drug_interactions.json`, v1: eng muhim kardio juftliklar; LLM xulosasi ikkinchi qatlam), (3) qarshi ko'rsatmalar (homiladorlik, buyrak/jigar yetishmovchiligi — anamnezdan), (4) doza chegaralari (`max_daily_dose` jadvali). LLM chiqargan har bir dori shu tekshiruvdan o'tmaguncha `suggested` + `safety_pending`.

### 3.8 Doctor conclusion (shifokor xulosasi)

| Metod | Yo'l | Tavsif |
|---|---|---|
| GET | `/examinations/{id}/conclusion` | joriy xulosa |
| PUT | `/examinations/{id}/conclusion` | qoralama yaratish/yangilash (`If-Match`) |
| POST | `/examinations/{id}/conclusion/sign` | imzolash -> exam `completed` |
| POST | `/examinations/{id}/conclusion/amend` | imzolanganni tuzatish (yangi versiya; sabab majburiy) |
| GET | `/examinations/{id}/conclusion/history` | |

```json
// PUT
{
  "diagnosis_text":"Mitral klapan yetishmovchiligi, o'rtacha daraja (ehtimoliy). Exo-KG bilan tasdiqlash zarur.",
  "icd10_codes":["I34.0"],
  "final_pcg_class":"murmur","final_severity":"moderate",
  "agreement_with_ai":"agree","disagreement_reason":null,
  "recommendations":"Exo-KG, EKG; 2 haftadan so'ng nazorat ko'rigi.",
  "follow_up_date":"2026-12-02","follow_up_notes":"Furosemid ta'siri nazorati","referred_to":null
}
// POST /sign  -> 200
{"id":"...","status":"signed","signed_at":"2026-11-18T10:05:00Z","signature_hash":"a1b2...","exam_status":"completed"}
```
Sign shartlari: `diagnosis_text`, `recommendations` bo'sh emas; barcha retsept satrlari `approved/rejected` (hech biri `suggested` emas); `agreement_with_ai != agree` bo'lsa `disagreement_reason` majburiy; AI natijasi mavjud (`ai_ready/in_review`). Xatolar: `409 PRESCRIPTION_PENDING`, `409 INVALID_STATE`, `422 DISAGREEMENT_REASON_REQUIRED`, `403`.
`GET .../conclusion` birinchi marta ochilganda exam `ai_ready -> in_review` (`reviewed_by` = shu shifokor, assigned bo'lmasa avto-assign).

### 3.9 Notifications

| Metod | Yo'l | Tavsif |
|---|---|---|
| GET | `/notifications?is_read=false&type=` | kursor pagination |
| GET | `/notifications/unread-count` | `{"count":3}` |
| POST | `/notifications/{id}/read` | `204` |
| POST | `/notifications/read-all` | `204` |
| DELETE | `/notifications/{id}` | `204` |

```json
{"items":[{"id":"...","type":"analysis_done","title":"Tahlil tayyor: E-20261118-0042","body":"Rahimov J. — shovqin aniqlandi (o'rtacha)","payload":{"examination_id":"...","severity":"moderate"},"is_read":false,"created_at":"..."}],"page":{"limit":20,"next_cursor":null}}
```

### 3.10 Audit logs

`GET /audit-logs` — admin (hammasi), doctor (`user_id=me` majburiy qo'yiladi). Filtr: `user_id`, `action`, `resource_type`, `resource_id`, `patient_id`, `success`, `from`, `to`, `ip`, `q` (path). Sort: `-ts` (default). Kursor (`id` bo'yicha).
```json
{"items":[{"id":918273,"ts":"2026-11-18T09:30:11Z","user":{"id":"...","username":"nurse.aliyeva","role":"nurse"},"action":"upload","resource_type":"recording","resource_id":"...","patient_id":"...","ip":"10.0.0.8","method":"POST","path":"/api/v1/examinations/.../recordings","status_code":201,"success":true,"meta":{"size_bytes":2646044}}],"page":{"limit":50,"next_cursor":"918223"}}
```
`GET /audit-logs/export?format=csv` — admin (`export:audit`), 8.2.

Qoplanadigan hodisalar: barcha auth hodisalari; bemor/tekshiruv/yozuvga `read` (list emas, faqat detail ochish); har `create/update/delete`; `upload/download`; `ai_call` (LLM — model, tokenlar, latency, `examination_id`, PII yo'q); `status_change`; `sign/approve/reject`; `export`; `settings_change`; `permission_denied`. O'zgarishlarda `changes.before/after` (parol, token, JShShIR maskalanadi).

### 3.11 System settings

| Metod | Yo'l | Ruxsat |
|---|---|---|
| GET | `/settings` | admin (hammasi) |
| PATCH | `/settings` | admin — `{"upload.max_audio_mb": 30, "ai.llm_enabled": false}`; tur va oraliq validatsiya, o'zgarish auditga |
| GET | `/settings/public` | har qanday auth foydalanuvchi: `is_public=true` kalitlar (upload limitlari, klinika nomi) |
| GET | `/system/health` | auth yo'q (faqat `{"status":"ok"}`); `/system/health/deep` admin: DB, Redis, storage, worker, DeepSeek ping |
| GET | `/system/version` | `{"version":"1.0.0","model_version":"pcg-cnn-1.0.0","commit":"abc1234"}` |

### 3.12 Analitika (dashboardlar)

Umumiy parametrlar: `from`, `to` (default oxirgi 30 kun), `granularity=day|week|month` (time series), `tz=Asia/Tashkent` (guruhlash uchun `AT TIME ZONE`). Hamma analitika endpoint'lari Redis'da 60 soniya kesh (`analytics:{endpoint}:{hash(params,user)}`), yangi `completed` bo'lganda tegishli kalitlar bekor qilinadi. Faqat `deleted_at IS NULL` qatorlar. Katta hisoblar uchun v2'da materialized view (`mv_daily_exam_stats`), v1'da indekslangan to'g'ridan-to'g'ri SQL.

#### Admin dashboard (admin)

**`GET /analytics/admin/kpis`**
```json
{
  "period":{"from":"2026-10-19","to":"2026-11-18"},
  "kpis":{
    "total_patients":{"value":412,"delta_pct":6.2},
    "new_patients":{"value":38,"delta_pct":-4.0},
    "examinations_total":{"value":356,"delta_pct":11.5},
    "examinations_completed":{"value":301,"delta_pct":9.1},
    "pending_review":{"value":14,"delta_pct":null},
    "failed_analyses":{"value":3,"delta_pct":-50.0},
    "abnormal_rate_pct":{"value":38.4,"delta_pct":1.9},
    "critical_findings":{"value":9,"delta_pct":28.6},
    "avg_ai_processing_sec":{"value":9.8,"delta_pct":-3.0},
    "avg_time_to_conclusion_min":{"value":47.5,"delta_pct":-8.2},
    "ai_doctor_agreement_pct":{"value":86.7,"delta_pct":0.8},
    "active_users":{"value":19,"delta_pct":5.5},
    "storage_used_gb":{"value":12.4,"delta_pct":null},
    "llm_cost_usd":{"value":4.31,"delta_pct":10.0}
  }
}
```
`delta_pct` — oldingi teng davr bilan solishtirish.

**`GET /analytics/admin/timeseries?metric=examinations|completed|abnormal|new_patients|failed|llm_tokens&granularity=day`**
```json
{"metric":"examinations","granularity":"day","series":[{"t":"2026-11-17","value":14},{"t":"2026-11-18","value":11}],"series_by":null}
```
`group_by=pcg_class|status|priority|doctor` berilsa: `"series_by":{"murmur":[{"t":"2026-11-17","value":5}],"normal":[...]}`.

**`GET /analytics/admin/distributions?dimension=pcg_class|severity|status|age_group|gender|site|priority|icd10`**
```json
{"dimension":"pcg_class","total":356,"items":[{"key":"normal","count":219,"pct":61.5},{"key":"murmur","count":105,"pct":29.5},{"key":"extra_heart_sound","count":19,"pct":5.3},{"key":"artifact","count":13,"pct":3.7}]}
```
Yosh guruhlari: `0-17, 18-39, 40-59, 60-74, 75+`.

**`GET /analytics/admin/workload`** — foydalanuvchi kesimida:
```json
{"doctors":[{"user_id":"...","full_name":"Karimov Aziz","assigned":58,"completed":52,"pending":6,"avg_time_to_conclusion_min":41.2,"agreement_pct":88.5}],
 "nurses":[{"user_id":"...","full_name":"Aliyeva Dilnoza","exams_created":93,"recordings_uploaded":271,"rejected_recordings":7,"avg_recordings_per_exam":2.9}],
 "queue":{"queued":2,"processing":1,"ai_ready":9,"in_review":5,"oldest_pending_min":134}}
```
**`GET /analytics/admin/heatmap?metric=examinations`** — hafta kuni x soat (`[{"dow":1,"hour":9,"value":12}]`).
**`GET /analytics/admin/ai-performance`** — model versiyasi kesimida: `{"model_versions":[{"version":"pcg-cnn-1.0.0","n":301,"agreement_pct":86.7,"partial_pct":8.0,"disagree_pct":5.3,"avg_confidence":0.82,"confusion_matrix":{"labels":["normal","murmur","extra_heart_sound","artifact"],"matrix":[[200,10,2,3],[8,90,4,1],[1,3,12,0],[2,1,0,8]]},"calibration":[{"bin":"0.8-0.9","mean_conf":0.85,"accuracy":0.83,"n":88}]}],"llm":{"avg_latency_ms":3100,"total_tokens":842113,"cost_usd":4.31,"error_rate_pct":0.9}}`. Confusion matrix: qator — shifokor yakuniy sinf (`final_pcg_class`), ustun — AI sinfi.
**`GET /analytics/admin/system`** — API p50/p95 kechikish (Prometheus/Redis hisoblagichlardan), job navbati, xatolar soni, disk.

#### Doctor dashboard (doctor; admin `?doctor_id=`)

**`GET /analytics/doctor/kpis`**: `{"kpis":{"my_pending":{"value":6},"my_completed_today":{"value":9},"my_completed_period":{"value":52},"avg_time_to_conclusion_min":{"value":41.2},"urgent_waiting":{"value":2},"ai_agreement_pct":{"value":88.5},"overrides_count":{"value":6},"patients_seen":{"value":47},"follow_ups_due_7d":{"value":11}}}`.
**`GET /analytics/doctor/queue`** — kutayotganlar ro'yxati (priority tartibida): `{"items":[{"exam_id":"...","exam_no":"...","patient":{...},"priority":"urgent","severity":"severe","ai_class":"murmur","waiting_min":38}]}`.
**`GET /analytics/doctor/timeseries?metric=completed|agreement|avg_time`**.
**`GET /analytics/doctor/distributions?dimension=final_pcg_class|final_severity|icd10|age_group`**.
**`GET /analytics/doctor/ai-vs-doctor`**: `{"total":52,"agree":46,"partial":4,"disagree":2,"agreement_pct":88.5,"confusion_matrix":{...},"disagreements":[{"exam_id":"...","ai_class":"normal","final_class":"murmur","reason":"...","signed_at":"..."}],"trend":[{"t":"2026-W45","agreement_pct":85.0}]}`.
**`GET /analytics/doctor/follow-ups`** — `follow_up_date` yaqinlashgan bemorlar.

#### Nurse (o'z ish hajmi)
**`GET /analytics/nurse/kpis`**: `{"exams_created_today":8,"exams_created_period":93,"recordings_uploaded":271,"rejected_recordings":7,"avg_recording_quality":0.79,"awaiting_ai":2}`.

AI-vs-doctor hisoblash: `agreement_pct = agree / total_signed * 100` (`partial` 0.5 vazn bilan `weighted_agreement_pct` sifatida qo'shimcha beriladi). Faqat `doctor_conclusions.is_current AND status IN ('signed','amended')`.

### 3.13 Export

| Metod | Yo'l | Ruxsat | Natija |
|---|---|---|---|
| GET | `/examinations/{id}/export/pdf` | export:pdf | `application/pdf`, `Content-Disposition: attachment; filename="CardioPCG_E-20261118-0042.pdf"` |
| POST | `/export/csv` | export:csv | `202 {"export_id":"..."}` (> 10 000 qator) yoki kichik so'rovlarda to'g'ridan `200 text/csv` |
| GET | `/export/{export_id}` | egasi | holat; tayyor bo'lsa `file_url` (15 daqiqalik imzolangan) |
| GET | `/audit-logs/export` | admin | CSV |

`POST /export/csv`:
```json
{"kind":"examinations","filters":{"examined_from":"2026-10-01","examined_to":"2026-10-31","status":["completed"],"assigned_doctor_id":null},"columns":["exam_no","mrn","age","gender","examined_at","ai_class","ai_confidence","final_class","agreement","severity","doctor"],"anonymize":true}
```
`kind`: `examinations | patients | analytics_timeseries | conclusions`. `anonymize=true` (default nurse uchun yo'q; doctor/admin uchun true): ism, telefon, manzil, JShShIR chiqmaydi, MRN hash'lanadi. CSV: UTF-8 BOM, `;` bilan emas — `,` ajratgich, Excel uchun formula injection himoyasi (`=,+,-,@` bilan boshlangan katakka `'` prefiks).
PDF hisobot tarkibi (WeasyPrint yoki ReportLab; `services/report_pdf.py`): klinika sarlavhasi/logo, bemor ma'lumoti (MRN, yosh, jins), tekshiruv (vitallar, shikoyat), har audio uchun to'lqin shakli va spektrogramma rasmi, tahlil jadvali (sinf, ehtimollik, HR, S1/S2 vaqtlari, shovqin), AI xulosa va differensial (disclaimer bilan), tasdiqlangan dorilar (faqat `approved`), shifokor xulosasi, imzo bloki (F.I.Sh., litsenziya, `signed_at`, `signature_hash`), QR (verify URL `/verify/{exam_no}/{hash8}`), sahifa pastida "Hujjat tizimda yaratilgan". Faqat `completed` tekshiruv uchun (qoralama — "QORALAMA" suv belgisi bilan, faqat doctor/admin).

### 3.14 Pagination / filter / sort konventsiyasi

- Default: kursor pagination (katta jadvallar: `patients`, `examinations`, `audit_logs`, `notifications`, timeline). Parametrlar: `limit` (default 20, max 100; audit — 200), `cursor` (opak base64 JSON `{"k":[<sort_value>,<id>]}`). Javob: `"page":{"limit":20,"next_cursor":"...|null","total":412}`. `total` faqat `?with_total=true` bilan hisoblanadi (COUNT qimmat) — ro'yxat jadvallarida frontend default `true` yuboradi.
- Offset ham qo'llab-quvvatlanadi kichik ro'yxatlarda (`users`, `settings`): `?page=1&page_size=20`.
- Sort: `sort=-examined_at,priority` (vergul bilan, `-` kamayish). Ruxsat etilgan maydonlar whitelist (har endpoint uchun), boshqasi -> `422`. Tie-breaker har doim `id`.
- Filtr: oddiy `field=value`, ko'p qiymat takroriy parametr (`status=a&status=b`), diapazon `*_from/*_to` yoki `*_min/*_max`, qidiruv `q` (pg_trgm `ILIKE` + `similarity > 0.3`, minimum 2 belgi).
- Ro'yxat elementlari yengil (`ListItem` sxemalari), detail — to'liq.

---

## 4. Fayl yuklash qoidalari

Ruxsat etilgan audio: `.wav` (`audio/wav`, `audio/x-wav`), `.mp3` (`audio/mpeg`), `.flac` (`audio/flac`, `audio/x-flac`). Tasvir (qo'shimcha: EKG/spektrogramma skrinshoti): `.png`, `.jpg/.jpeg`.

| Parametr | Qiymat (system_settings orqali o'zgaradi) |
|---|---|
| Audio maks. hajm | 25 MB (`upload.max_audio_mb`) |
| Tasvir maks. hajm | 10 MB |
| Avatar | 2 MB |
| Tekshiruvga maks. fayl | 12 (`upload.max_files_per_exam`) |
| Audio davomiyligi | 5–120 s |
| Namuna chastotasi | 2 000–96 000 Hz (pastroq bo'lsa `warning`); ichkarida 4 000 Hz ga resample |
| Kanallar | 1–2 (stereo -> mono average) |

Validatsiya zanjiri (`services/upload_validator.py`), tartib bilan; birinchi xatoda to'xtaydi:
1. Content-Length oldindan tekshiruv (nginx `client_max_body_size 30m`; FastAPI'da streaming o'qish va hajm hisoblagich — chegaradan oshsa o'qishni to'xtatib `413`).
2. Fayl nomi sanitizatsiya: faqat `basename`, `[A-Za-z0-9._-]` ga normalizatsiya, uzunlik ≤255, qo'sh kengaytma (`a.wav.exe`) rad; diskdagi nom hech qachon klient nomi emas (`storage_key` UUID asosida).
3. Kengaytma whitelist; MIME ni libmagic (`python-magic`) bilan **kontent bo'yicha** aniqlash; klient `Content-Type` e'tiborga olinmaydi, mos kelmasa `415`.
4. Magic bytes: WAV `RIFF....WAVE`, FLAC `fLaC`, MP3 `ID3` yoki `0xFFEx` frame sync, PNG `\x89PNG`, JPEG `\xFF\xD8\xFF`.
5. Streaming SHA-256 hisoblash (vaqtinchalik faylga yozish bilan bir vaqtda); shu tekshiruvda bir xil sha256 -> `409 DUPLICATE_RECORDING`.
6. Dekodlash: `soundfile`/`librosa` bilan to'liq o'qishga urinish (kodek bomba himoyasi: dekodlangan uzunlik ≤ 120 s * sr, xotira limiti; `ffprobe` timeout 10 s). Buzuq -> `422 AUDIO_CORRUPT`.
7. Signal sifati: davomiylik chegarasi; jimlik (RMS < −60 dBFS -> `AUDIO_SILENT`); klipping (>1% namuna |x|≥0.999 -> `warning` yoki >5% rad `AUDIO_CLIPPED`); SNR bahosi; DC offset olib tashlanadi. Warning'lar `validation_report.warnings[]` da, yuklash qabul qilinadi (`quality_score` past bo'lsa UI tavsiya beradi qayta yozishni).
8. Tasvir: Pillow bilan ochish (`Image.verify()` + qayta kodlash — EXIF/metama'lumot olib tashlanadi, "image bomb" himoyasi `MAX_IMAGE_PIXELS = 25e6`).
9. Antivirus: ClamAV konteyneri (`clamd`, INSTREAM). Asinxron emas — kichik fayllar uchun sinxron (timeout 5 s). `infected` -> fayl o'chiriladi, `422 INFECTED_FILE`, audit `permission_denied` emas `upload` + `success=false`. ClamAV mavjud bo'lmasa: `scan_status='skipped'`, `warning`, admin dashboardda ogohlantirish (prod'da `CLAMAV_REQUIRED=true` bo'lsa `503`).
10. Saqlash: `storage_key = exams/{exam_id}/{recording_id}/original.{ext}`; MinIO'ga `put_object` (SSE-S3 shifrlash yoki disk volume, 0640). Originalga to'g'ridan-to'g'ri ommaviy havola YO'Q; yuklab olish API orqali (auth + audit) yoki 5 daqiqalik presigned URL.
11. Tranzaksiya: `recordings` qatori yaratiladi (`uploading`), fayl saqlanadi, `validated` ga o'tadi; xato bo'lsa fayl o'chiriladi (compensating cleanup); osilib qolgan `uploading` qatorlar 1 soatdan keyin cron bilan tozalanadi.
12. Rate limit: foydalanuvchi bo'yicha 30 upload/daq.

Zararli fayl turlari (`.exe, .js, .html, .svg, .zip`) rad etiladi (SVG — XSS xavfi tufayli ruxsat yo'q).

---

## 5. Exam status state machine va fon vazifalar

### 5.1 Holatlar

| status | ma'no |
|---|---|
| `draft` | yaratilgan, audio yo'q yoki hali validatsiyalanmagan |
| `uploaded` | kamida 1 ta `validated` audio, tahlilga tayyor |
| `queued` | tahlil navbatda (`analysis_jobs.status=pending`) |
| `processing` | worker ishlayapti |
| `ai_ready` | signal tahlili + AI hisobot (+ dori taklifi) tayyor, shifokor kutilmoqda |
| `in_review` | shifokor ochgan/xulosa qoralamasi bor |
| `completed` | xulosa imzolangan (yakuniy) |
| `failed` | tahlil xatosi (qayta urinish mumkin) |
| `cancelled` | bekor qilingan (terminal) |

### 5.2 O'tishlar

```
draft ──upload validated──▶ uploaded ──analyze──▶ queued ──worker start──▶ processing
processing ──success──▶ ai_ready ──doctor opens/draft──▶ in_review ──sign──▶ completed
processing ──error (attempts exhausted)──▶ failed ──reanalyze──▶ queued
ai_ready/in_review ──reanalyze (doctor/admin)──▶ queued
uploaded/draft/failed/ai_ready/in_review ──cancel──▶ cancelled        (completed dan cancel YO'Q)
uploaded ──delete last audio──▶ draft
completed ──amend──▶ completed (conclusion yangi versiya; status o'zgarmaydi)
```

| From | To | Kim | Shart |
|---|---|---|---|
| draft | uploaded | system | birinchi audio `validated` |
| uploaded | queued | nurse/doctor/admin (yoki auto) | `analysis.auto_start=true` bo'lsa yuklash tugagach `POST .../analyze` avto chaqiriladi frontend tomonidan "Yuklashni yakunlash" tugmasida; server-auto faqat sozlama yoqilganda |
| queued | processing | worker | |
| processing | ai_ready | worker | `analysis_results` yozilgan; LLM o'chiq/xato bo'lsa ham `ai_ready` (hisobot `failed`, signal natijasi bor) |
| processing | failed | worker | signal tahlili xatosi, `max_attempts` tugagan |
| failed | queued | doctor/admin | `reanalyze` |
| ai_ready | in_review | doctor | conclusion/report ochilganda yoki qoralama saqlanganda |
| in_review | completed | doctor | `sign` |
| ai_ready/in_review | queued | doctor/admin | `reanalyze` (conclusion qoralamasi saqlanadi) |
| * (non-terminal) | cancelled | roli bo'yicha | `cancel_reason` |

Noto'g'ri o'tish — `409 INVALID_STATE` `{"details":{"current":"processing","allowed":["cancelled"]}}`. O'tishlar yagona funksiya `exam_state.transition(exam, to, actor, reason)` orqali (SELECT ... FOR UPDATE, tarixga `exam_status_history` yozuvi, WebSocket hodisasi, audit `status_change`, bildirishnoma).

### 5.3 Fon vazifa oqimi (Celery, Redis broker; navbatlar: `analysis`, `llm`, `default`, `exports`)

`analyze_examination(exam_id, job_id)`:
1. `queued -> processing`, `job.started_at`, hodisa `analysis.progress {stage:'validating', pct:5}`.
2. **validating**: barcha audio fayllarni MinIO'dan o'qish, qayta tekshiruv (10%).
3. **preprocessing**: mono, resample 4 kHz, band-pass 20–400 Hz (Butterworth 4-tartib), normalizatsiya, shovqin kamaytirish (spectral gating) (25%).
4. **segmenting**: Shannon envelope + Hilbert, S1/S2 aniqlash (o'z algoritmi yoki neurokit2), siklga bo'lish, `pcg_segments` (40%).
5. **features**: MFCC (13), spectral centroid/bandwidth/rolloff, energy ratio sistola/diastola, HR, intervallar (55%).
6. **classifying**: `onnxruntime` modeli (`pcg-cnn`) yoki model yo'q bo'lsa qoidaga asoslangan klassifikator (`rules-1.0.0`: murmur energiyasi sistolada/diastolada chegaralar). Har nuqta uchun sinf, so'ng `worst_site` agregatsiya; `severity` (energiya/davomiylik/frequency bo'yicha) (70%).
7. **spectrogram**: mel-spektrogramma PNG + waveform peaks JSON, MinIO'ga, `recordings(kind='spectrogram', derived_from_id)` (80%).
8. `analysis_results` yoziladi (eski `is_current=false`), exam `ai_requested_at/ai_completed_at`. Hodisa `analysis.signal_done`. Commit (85%).
9. **llm_report** (`llm` navbatida alohida task `generate_ai_report`, agar `ai.llm_enabled`): anonim kirish yig'iladi -> DeepSeek chaqiruvi (`response_format: json_object`, temperature 0.2, timeout 60 s, 2 retry exponential backoff, JSON schema validatsiya Pydantic bilan; noto'g'ri JSON -> 1 marta tuzatish so'rovi) -> `ai_reports` (90%). Audit `ai_call`.
10. **drug suggestions** (agar `ai.drug_suggestions_enabled`): ikkinchi so'rov yoki bitta ichida; natija `drug_safety` tekshiruvidan o'tib `prescriptions/drug_recommendations` (`suggested`) (96%).
11. **finalizing**: `processing -> ai_ready`, `job.status=succeeded`, notification `analysis_done` (assigned_doctor yoki barcha doctor'lar — `assigned_doctor_id` NULL bo'lsa `role:doctor` kanaliga), `critical_finding` (agar `severity>=severe` yoki `confidence>=threshold` va sinf `murmur` + `red_flags` bo'sh emas) (100%).

Xato siyosati: signal bosqichlari — `autoretry_for=(TransientError,)`, 3 urinish, backoff 10/30/90 s; deterministik xato (`AUDIO_CORRUPT`) retry'siz `failed`. LLM xatosi signal natijasini bekor qilmaydi: `ai_reports.status='failed'`, exam baribir `ai_ready` (UI "AI izohini qayta yaratish" tugmasi). Worker o'lib qolsa: `acks_late=True`, `visibility_timeout=900`; cron `reap_stuck_jobs` (har 5 daqiqa) — `running` va `updated_at` > 15 daq bo'lsa `failed` ga o'tkazadi va qayta navbatga qo'yadi (attempt < max).
Vazifa idempotent: `job_id` bo'yicha `SELECT ... FOR UPDATE SKIP LOCKED`; takroriy ishga tushsa (`status != pending`) chiqib ketadi. Bekor qilish: `cancel` -> `job.status=cancelled`, worker har bosqich oldida bayroqni tekshiradi (Redis `job:cancel:{id}`).

Davriy vazifalar (Celery beat): `reap_stuck_jobs` (5 daq), `cleanup_uploading_recordings` (1 soat), `purge_expired_refresh_tokens` (kuniga), `purge_old_notifications` (kuniga), `purge_raw_llm_responses` (kuniga, 90 kun), `purge_expired_exports` (soatiga), `audit_partition_maintenance` (oyiga), `db_backup_verify` (kuniga).

---

## 6. Realtime: WebSocket va SSE

Asosiy kanal — **WebSocket** `GET /api/v1/ws?token=<access_jwt>` (brauzer WS sarlavha qo'sha olmaydi; token query'da, 15 daq amal qiladi, server ulanish paytida tekshiradi va access tugashidan oldin klient `{"type":"auth","token":"..."}` xabari bilan yangilaydi; nginx logida `token` maskalanadi). Zaxira: **SSE** `GET /examinations/{id}/events` (Bearer sarlavha bilan, `text/event-stream`, 15 s heartbeat `: ping`) — bitta tekshiruv progressi uchun (WS bloklangan tarmoqlarda). Backend ichida Redis Pub/Sub (`ws:user:{id}`, `ws:role:{role}`, `ws:exam:{id}`), bir nechta ilova worker'lari orasida tarqatish.

Xabar konverti:
```json
{"v":1,"id":"0192...","type":"analysis.progress","ts":"2026-11-18T09:33:10Z","data":{"examination_id":"...","job_id":"...","stage":"classifying","progress_pct":62}}
```

Klient -> server: `{"type":"subscribe","channels":["exam:0192..."]}`, `{"type":"unsubscribe",...}`, `{"type":"ping"}` (server `pong`). Avtomatik obuna: `user:{me}`, `role:{myrole}` (doctor/admin uchun). `exam:{id}` obunasi `policy.can(read)` bilan tekshiriladi.

Hodisalar:

| type | kimga | data |
|---|---|---|
| `exam.created` | admin, assigned doctor | `{examination_id, exam_no, patient_id}` |
| `exam.status_changed` | exam kanali + `role:doctor` | `{examination_id, from, to, by}` |
| `recording.uploaded` | exam kanali | `{recording_id, site, status}` |
| `recording.rejected` | uploader | `{recording_id, code, message}` |
| `analysis.progress` | exam kanali | `{job_id, stage, progress_pct}` |
| `analysis.signal_done` | exam kanali | `{analysis_result_id, pcg_class, confidence, severity}` |
| `analysis.report_ready` | exam kanali | `{ai_report_id}` |
| `analysis.completed` | exam, performed_by, assigned doctor | `{examination_id, status:'ai_ready'}` |
| `analysis.failed` | exam, performed_by, admin | `{job_id, error_code, message, can_retry}` |
| `exam.assigned` | assigned doctor | `{examination_id, by}` |
| `conclusion.signed` | exam, performed_by (nurse) | `{examination_id, doctor_id, signed_at}` |
| `finding.critical` | `role:doctor`, assigned doctor, admin | `{examination_id, severity, red_flags[]}` |
| `notification.new` | user | to'liq notification obyekti |
| `system.maintenance` | hammaga | `{starts_at, message}` |

SSE: shu konvert, `event: <type>`, `id: <event id>`, `Last-Event-ID` qo'llab-quvvatlanadi (Redis Stream `exam_events:{id}` oxirgi 100 hodisa, TTL 1 soat). Yopilish kodlari WS: `4401` (auth), `4403` (ruxsat), `4429` (limit: foydalanuvchiga ≤5 ulanish). Reconnect: klient exponential backoff, qayta ulangach `GET /examinations/{id}/status` bilan holatni sinxronlaydi.

---

## 7. Xavfsizlik

### 7.1 Autentifikatsiya
- **Parol:** argon2id (`argon2-cffi`): `time_cost=3, memory_cost=65536 (64 MiB), parallelism=4`; `PasswordHasher.check_needs_rehash` — kirishda parametrlar eskirgan bo'lsa qayta hash. Pepper: ixtiyoriy `PASSWORD_PEPPER` (HMAC oldindan). Min uzunlik 10, zxcvbn ≥3, ommaviy buzilgan parollar ro'yxati (top-10k) tekshiruvi.
- **Access JWT:** HS256 yoki EdDSA (`JWT_ALG=EdDSA`, kalit `.env`), 15 daqiqa; claim'lar: `sub`, `role`, `jti`, `iat`, `exp`, `iss=cardiopcg`, `aud=cardiopcg-web`, `sv` (security version — `users.security_version int`; parol o'zgarsa/suspend bo'lsa oshiriladi, eski access'lar rad etiladi — DB/Redis keshdan tekshiriladi, 30 s kesh). Frontend access'ni xotirada (Zustand, localStorage'ga EMAS) saqlaydi.
- **Refresh:** 256-bit tasodifiy (`secrets.token_urlsafe(48)`), DB'da sha256, cookie `cp_refresh` (`HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`), 7 kun, **rotation + reuse detection** (1.3, 3.1). Mutlaq maks. sessiya 30 kun (`family` boshlanishidan hisoblanadi, undan keyin qayta login).
- **CSRF:** refresh cookie faqat `/auth/*` yo'lida va `SameSite=Strict`; qo'shimcha `/auth/refresh` va `/auth/logout` uchun `Origin` sarlavhasi allowlist'ga mosligi tekshiriladi; boshqa endpoint'lar Bearer — CSRF xavfi yo'q.
- **Lockout:** 5 ta noto'g'ri urinish -> 15 daqiqa blok (`locked_until`), eksponensial uzaytirish (takroriy blokda 30/60 daq), admin `unlock`.
- 2FA (TOTP) — v1.1 ga rejalashtirilgan (`users.totp_secret_enc`); admin uchun tavsiya.

### 7.2 Rate limiting
`slowapi` + Redis (sliding window) yoki Redis Lua token bucket; kalit: autentifikatsiyalanganda `user_id`, aks holda IP (`CF-Connecting-IP`, faqat Cloudflare diapazonlaridan kelgan so'rovda ishoniladi).

| Endpoint | Limit |
|---|---|
| `POST /auth/login` | 10/daq/IP, 5/daq/username |
| `POST /auth/refresh` | 30/daq/IP |
| `POST /auth/reset-password`, `change-password` | 5/daq |
| Upload | 30/daq/user |
| `POST .../analyze`, `reanalyze`, `report/regenerate` | 20/daq/user, global LLM 60/daq |
| Umumiy API | 300/daq/user |
| Export | 10/soat/user |
| WS ulanish | 5 parallel/user |

Javob: `429` + `Retry-After`, `X-RateLimit-Limit/Remaining/Reset`.

### 7.3 CORS, sarlavhalar, transport
- CORS: `allow_origins=[settings.FRONTEND_ORIGIN]` (`https://cardiopcgai.189.uz`; dev'da `http://localhost:5173`), `allow_credentials=True`, metodlar `GET,POST,PATCH,PUT,DELETE,OPTIONS`, sarlavhalar `Authorization,Content-Type,If-Match,Idempotency-Key,X-Request-ID`, `expose_headers=[X-Request-ID, Content-Disposition, Retry-After, ETag]`. `*` HECH QACHON.
- Frontend va API bitta domen (`/api` nginx proxy) — CORS prod'da deyarli kerak emas, ammo sozlama aniq saqlanadi.
- Sarlavhalar (nginx + middleware): `Strict-Transport-Security: max-age=31536000; includeSubDomains`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, `Permissions-Policy: microphone=(self), camera=()`, CSP (frontend nginx'da): `default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self' wss://cardiopcgai.189.uz; script-src 'self'; style-src 'self' 'unsafe-inline'`. API javoblarida `Cache-Control: no-store` (PHI).
- TLS: Cloudflare Full (strict) + origin sertifikat; konteyner faqat `127.0.0.1:8080` da eshitadi. `TrustedHostMiddleware`.
- Swagger (`/docs`, `/openapi.json`) prod'da o'chirilgan (`docs_url=None`) yoki admin Basic-auth orqasida.

### 7.4 Ma'lumot himoyasi
- Sirlar faqat `.env` (`DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `DEEPSEEK_API_KEY`, `PII_ENCRYPTION_KEY`, `S3_*`, `PASSWORD_PEPPER`); `.env` gitignore'da; `pydantic-settings` bilan yuklash; loglarda sirlar maskalanadi.
- PII: JShShIR ilova darajasida AES-256-GCM; DB-darajasida disk shifrlash (LUKS) tavsiya; zaxira nusxalar shifrlangan (`pg_dump | age`).
- LLM'ga PII yuborilmaydi (1.11); DeepSeek chaqiruvi serverdan, kalit klientga hech qachon chiqmaydi.
- Input validatsiya: Pydantic v2 `extra='forbid'`; SQLAlchemy parametrli so'rovlar (SQL injection yo'q); `ORDER BY` whitelist; HTML chiqarilmaydi (JSON API), PDF'da foydalanuvchi matni escape.
- Saqlash muddati: klinik yozuvlar — o'chirilmaydi (soft delete, 25 yilgacha qonun bo'yicha tavsiya); audit 5 yil (`retention.audit_days`); xom LLM javobi 90 kun; vaqtinchalik fayllar 1 soat; eksportlar 24 soat.
- Principle of least privilege: DB'da ikkita rol — `cardiopcg_app` (DML, audit_logs'ga faqat INSERT/SELECT) va `cardiopcg_migrator` (DDL, faqat Alembic ishga tushganda).

### 7.5 Audit
`AuditMiddleware` (har so'rov: method, path, status, request_id, ip, ua) + servis darajasidagi aniq hodisalar (`audit.log(action, resource, changes)`). Yozish asinxron (Redis stream -> worker batch insert) EMAS, balki xavfsizlik-kritik hodisalarda (login, sign, permission_denied, ai_call) sinxron, boshqalarda `BackgroundTasks`. Audit yozilmasa operatsiya bajarilmaydi (kritik amallar uchun, bitta tranzaksiyada). GET `/audit-logs` o'zi auditga yozilmaydi (rekursiya).

### 7.6 Boshqa
- Idempotency-Key (upload/analyze/sign).
- Request hajmi limiti: JSON 1 MB.
- Dependency skan: `pip-audit`, `ruff`, `bandit` CI'da. Konteyner non-root, read-only FS (`/tmp` tmpfs), resource limitlar.
- Soat sinxronizatsiyasi (NTP); JWT leeway 10 s.
- Logging: structlog JSON, `request_id`, `user_id`, `role`; PHI (ism, telefon) loglanmaydi.

---

## 8. Loyiha tuzilmasi (`backend/`)

```
backend/
  pyproject.toml            # uv, ruff, pytest, mypy sozlamalari
  uv.lock
  Dockerfile                # python:3.13-slim, uv sync --frozen, non-root, gunicorn+uvicorn workers
  alembic.ini
  alembic/
    env.py                  # async engine
    versions/               # 0001_initial.py ... (enum'lar, partitsiya, triggerlar, seed settings)
  scripts/
    create_admin.py         # interaktiv: username + parol so'raydi (parol argv/logda YO'Q), birinchi admin
    seed_reference.py       # drug_interactions.json, ICD-10 qisqa ro'yxat (parol/demo foydalanuvchi YO'Q)
    train_model.py          # (ml/ bilan bog'liq, ixtiyoriy)
  app/
    main.py                 # create_app(): middleware, routers, lifespan (db/redis/minio init)
    config.py               # pydantic-settings Settings
    core/
      security.py           # argon2, JWT encode/decode, token hash
      permissions.py        # Role, Permission, PERMISSIONS, policy.can()
      deps.py               # get_db, get_current_user, require_roles, get_redis, pagination params
      errors.py             # AppError + exception handlers (yagona xato formati)
      logging.py            # structlog
      rate_limit.py
      middleware.py         # RequestID, Audit, SecurityHeaders, BodySizeLimit
      pagination.py         # cursor encode/decode, apply_sort
      idempotency.py
      crypto.py             # AES-GCM PII, HMAC hash
    db/
      base.py               # DeclarativeBase, mixinlar (UUIDv7 PK, timestamps, soft delete)
      session.py            # async_sessionmaker
    models/                 # user.py refresh_token.py patient.py history.py examination.py recording.py
                            # analysis.py (job, result, segment) ai_report.py prescription.py conclusion.py
                            # notification.py audit.py setting.py export.py enums.py
    schemas/                # Pydantic v2: auth, user, patient, examination, recording, analysis,
                            # report, prescription, conclusion, notification, audit, analytics, common (Page, Error)
    api/
      v1/
        router.py
        auth.py users.py patients.py examinations.py recordings.py analysis.py
        reports.py prescriptions.py conclusions.py notifications.py audit.py
        settings.py analytics.py exports.py system.py ws.py
    services/
      auth_service.py patient_service.py exam_service.py exam_state.py
      recording_service.py upload_validator.py storage.py (MinIO/disk adapter) antivirus.py
      analysis_service.py report_service.py prescription_service.py drug_safety.py
      conclusion_service.py notification_service.py audit_service.py
      analytics_service.py export_service.py report_pdf.py realtime.py (Redis pubsub)
    ml/
      preprocess.py segmentation.py features.py classifier.py (onnx/rules) spectrogram.py quality.py
      models/               # *.onnx (git-lfs yoki serverga alohida joylanadi)
    llm/
      deepseek_client.py    # httpx async, retry, timeout, token/cost hisobi
      prompts/              # report_v3.md.j2, drugs_v1.md.j2 (versiyalangan)
      schemas.py            # LLM javob Pydantic sxemalari
      anonymizer.py         # PII'siz kirish yig'ish
    workers/
      celery_app.py         # navbatlar, beat jadvali
      tasks_analysis.py tasks_llm.py tasks_maintenance.py tasks_export.py
  tests/
    conftest.py             # testcontainers Postgres+Redis+MinIO, async client, factory'lar
    factories.py            # polyfactory/faker
    fixtures/audio/         # sintetik wav/mp3/flac (normal, murmur, silent, corrupt, long)
    unit/ integration/ e2e/ security/ perf/
```

Deploy (`deploy/docker-compose.prod.yml`) servislar: `api` (127.0.0.1:8080), `worker` (analysis, concurrency 2, CPU-bound), `worker-llm` (concurrency 4), `beat`, `postgres:17` (volume, 127.0.0.1), `redis:7`, `minio`, `clamav`. Alembic migratsiya `api` ishga tushishidan oldin alohida bir martalik konteynerda (`alembic upgrade head`).

Muhim kutubxonalar: `fastapi`, `uvicorn[standard]`, `gunicorn`, `pydantic>=2`, `pydantic-settings`, `sqlalchemy[asyncio]>=2`, `asyncpg`, `alembic`, `redis`, `celery`, `argon2-cffi`, `pyjwt`, `python-multipart`, `python-magic`, `boto3`/`aioboto3`, `numpy`, `scipy`, `librosa`, `soundfile`, `neurokit2`, `onnxruntime`, `matplotlib`, `httpx`, `jinja2`, `weasyprint`, `slowapi`, `structlog`, `zxcvbn`, `uuid-utils`, `pillow`, `pyclamd`/`clamd`, `orjson`.

---

## 9. Test rejasi

Vositalar: `pytest`, `pytest-asyncio`, `httpx.AsyncClient` (ASGITransport), `testcontainers` (PostgreSQL 17, Redis, MinIO), `polyfactory`, `freezegun`, `respx` (DeepSeek mock), `schemathesis` (OpenAPI fuzz), `locust` (yuklama), `coverage` (maqsad: umumiy ≥85%, `services/` va `core/security|permissions` ≥95%).

| Daraja | Qamrov |
|---|---|
| **Unit** | argon2 hash/rehash; JWT yaratish/muddati/`sv`; refresh rotation mantig'i va reuse; `policy.can()` — har rol x har ruxsat (parametrlangan matritsa 2-bo'limga to'liq mos); `exam_state.transition` — barcha ruxsat etilgan/etilmagan o'tishlar; upload_validator — magic bytes, soxta kengaytma, jimlik, klipping; `drug_safety` — allergiya kross-sinf, interaction juftliklari; cursor pagination encode/decode; PII shifrlash; CSV formula injection; signal: segmentatsiya sintetik signalda (ma'lum S1/S2 pozitsiyalari ±20 ms), HR aniqligi ±2 bpm |
| **Integration (DB)** | har endpoint: muvaffaqiyat, `401/403/404/409/422`; unikal cheklovlar; `UNIQUE ... WHERE is_current`; soft delete filtrlari; audit yozuvlari paydo bo'lishi (har mutatsiya -> 1 audit qator); audit_logs'ga UPDATE/DELETE urinishi xato; optimistik blokirovka (`If-Match`); filtr/sort/pagination kombinatsiyalari (kursor barqarorligi, tie-breaker); nurse javobida maydon maskalari; analitika SQL'lari ma'lum fixture'da qo'lda hisoblangan qiymatlarga teng; confusion matrix |
| **Worker** | `analyze_examination` to'liq oqim (DeepSeek `respx` bilan mock, haqiqiy kalitsiz); LLM 500/timeout/noto'g'ri JSON -> `ai_reports.failed` lekin exam `ai_ready`; signal xatosi retry va `failed`; `reap_stuck_jobs`; idempotentlik (task ikki marta); bekor qilish |
| **Realtime** | WS auth (yaroqsiz/muddati o'tgan token -> 4401), obuna ruxsati (nurse boshqa exam kanaliga -> 4403), hodisa ketma-ketligi progress 0->100, SSE `Last-Event-ID` |
| **Security** | brute-force lockout; timing (mavjud/yo'q username javob vaqti farqi < 20%); refresh reuse -> oila bekor; CSRF/Origin; CORS preflight faqat ruxsat etilgan origin; rate limit 429; IDOR (nurse/doctor boshqaning resursiga ID bo'yicha urinish); path traversal fayl nomida; zip/SVG/exe yuklash rad; decompression/audio-bomb; SQLi/XSS payload'lar (`sqlmap` smoke); JWT `alg=none` va imzo almashtirish; PII LLM'ga yuborilmasligi (mock so'rov tanasida ism/telefon yo'qligi tekshiruvi); sirlar loglarda yo'qligi |
| **Contract** | `schemathesis run /openapi.json` (stateful), frontend uchun OpenAPI -> TypeScript tiplar (`openapi-typescript`) CI'da diff tekshiruvi |
| **E2E (API oqimi)** | nurse login -> bemor yaratish -> tekshiruv -> wav yuklash -> analyze -> WS progress -> doctor login -> report ko'rish -> dori tasdiqlash -> xulosa imzolash -> PDF yuklab olish -> admin analytics'da hisob ko'rinishi |
| **Performance** | `locust`: 50 parallel foydalanuvchi; maqsad: list endpoint p95 < 300 ms (100k bemor, 500k tekshiruv fixture'da), upload 10 MB p95 < 3 s, analytics p95 < 800 ms (kesh bilan <100 ms); analiz job: 30 s audio uchun < 15 s (CPU, LLM'siz); `EXPLAIN` tekshiruvi: asosiy ro'yxat so'rovlari indeks ishlatishi (seq scan yo'q) |
| **Migratsiya** | `alembic upgrade head` bo'sh DB'da; `downgrade base`; `alembic check` (modellar bilan drift yo'q); migratsiyani prod nusxasi (anonim dump)da sinash — DDL'ni prod tranzaksiyasida sinamaslik |
| **CI** | GitHub Actions: `ruff check/format`, `mypy`, `pytest -n auto --cov`, `pip-audit`, `bandit`, Docker build; main'ga merge faqat yashil CI bilan |

Qabul mezonlari (Definition of Done, backend v1): barcha 3 rol uchun 2-bo'lim matritsasi avtomatik testlarda tasdiqlangan; barcha endpointlar OpenAPI'da hujjatlashtirilgan va namunaviy javoblarga ega; birinchi admin faqat `scripts/create_admin.py` bilan yaratiladi (kodda demo/seed parol yo'q); haqiqiy DeepSeek chaqiruvi staging'da bir marta qo'lda sinalgan (kalit `.env`da); audit_logs har mutatsiyada yoziladi; PDF va CSV eksport ishlaydi; WS/SSE hodisalari analiz oqimida to'liq kuzatiladi.
