/**
 * Hand-written API types derived from docs/01-BACKEND-DB-API.md (the contract wins over doc 03).
 * NOTE: backend/openapi.json did not exist when this was written. When it appears, run
 * `pnpm gen:api` (emits schema.gen.ts) and replace these hand-written types incrementally.
 * Field names are snake_case exactly as the backend sends them (no camelCase mapping layer).
 */

import type { components } from './schema.gen';

/** Generated contract types (pnpm gen:api). Prefer these over hand-written ones. */
export type G = components['schemas'];

export type Role = 'admin' | 'doctor' | 'nurse';
export type UserStatus = 'active' | 'suspended' | 'pending';
export type Gender = 'male' | 'female';
export type BloodGroup = 'O+' | 'O-' | 'A+' | 'A-' | 'B+' | 'B-' | 'AB+' | 'AB-' | 'unknown';
export type ExamStatus =
  | 'draft' | 'uploaded' | 'queued' | 'processing' | 'ai_ready' | 'in_review' | 'completed' | 'failed' | 'cancelled';
export type ExamPriority = 'routine' | 'urgent' | 'emergency';
export type PcgClass = 'normal' | 'murmur' | 'extra_heart_sound' | 'artifact' | 'undetermined';
export type Severity = 'none' | 'mild' | 'moderate' | 'severe' | 'critical';
export type AgreementLevel = 'agree' | 'partial' | 'disagree';
export type AuscultationSite = 'aortic' | 'pulmonic' | 'erb' | 'tricuspid' | 'mitral' | 'apex' | 'carotid' | 'other';
export type JobStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled';
export type NotificationType =
  | 'exam_uploaded' | 'analysis_done' | 'analysis_failed' | 'review_requested'
  | 'conclusion_signed' | 'critical_finding' | 'assignment' | 'system';
export type AuditAction =
  | 'login' | 'login_failed' | 'logout' | 'token_refresh' | 'token_reuse_detected' | 'password_change'
  | 'password_reset' | 'create' | 'read' | 'update' | 'delete' | 'restore' | 'export' | 'download' | 'upload'
  | 'assign' | 'ai_call' | 'status_change' | 'sign' | 'approve' | 'reject' | 'permission_denied' | 'settings_change';

/** Page envelope. Cursor lists use `page.next_cursor`; offset lists may use page/page_size/total. */
export interface PageMeta {
  limit?: number;
  next_cursor?: string | null;
  total?: number | null;
  page?: number;
  page_size?: number;
}
export interface Paged<T> {
  items: T[];
  page?: PageMeta;
  total?: number;
}

// ---- Auth ----
export interface SessionUser {
  id: string;
  username: string;
  full_name: string;
  role: Role;
  locale: 'uz' | 'ru' | 'en';
  must_change_password: boolean;
}
export interface LoginResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  user: SessionUser;
}
export interface RefreshResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
}
export interface Me extends SessionUser {
  email?: string | null;
  phone?: string | null;
  specialty?: string | null;
  permissions: string[];
  last_login_at?: string | null;
}

// ---- Users ----
export interface UserListItem {
  id: string;
  username: string;
  full_name: string;
  role: Role;
  status: UserStatus;
  email?: string | null;
  phone?: string | null;
  specialty?: string | null;
  license_no?: string | null;
  department?: string | null;
  must_change_password?: boolean;
  last_login_at?: string | null;
  locked_until?: string | null;
  created_at: string;
}
export interface UserCreateInput {
  username: string;
  full_name: string;
  role: Role;
  email?: string | null;
  phone?: string | null;
  specialty?: string | null;
  license_no?: string | null;
  department?: string | null;
  password: string;
  must_change_password: boolean;
}
export type UserUpdateInput = Partial<Omit<UserCreateInput, 'password' | 'must_change_password' | 'username'>> & {
  status?: UserStatus;
};
export type ResetPasswordResult = G['AdminResetOut'];

// ---- Patients ----
export interface PatientListItem {
  id: string;
  mrn: string;
  full_name: string;
  birth_date: string;
  age: number;
  gender: Gender;
  phone?: string | null;
  primary_doctor?: { id: string; full_name: string } | null;
  last_exam_at?: string | null;
  exam_count?: number;
  has_allergies?: boolean;
}
export type Allergy = G['AllergyOut'];
export type HistoryItem = G['HistoryOut'];
export type Medication = G['MedicationOut'];
export type PatientDetail = G['PatientDetail'] & Partial<Pick<PatientListItem, 'exam_count' | 'last_exam_at' | 'has_allergies'>>;

// ---- Examinations ----
export interface ExamListItem {
  id: string;
  exam_no: string;
  patient: { id: string; mrn: string; full_name: string; age: number; gender: Gender };
  status: ExamStatus;
  priority: ExamPriority;
  examined_at: string;
  assigned_doctor?: { id: string; full_name: string } | null;
  performed_by: { id: string; full_name: string };
  recording_count: number;
  ai?: { pcg_class: PcgClass; severity: Severity; confidence: number } | null;
  conclusion_status?: 'draft' | 'signed' | 'amended' | null;
}
export type Recording = G['RecordingOut'];
export type AnalysisResult = G['AnalysisOut'];
export interface PcgSegment {
  id: string;
  recording_id: string;
  seq: number;
  type: 'S1' | 'S2' | 'S3' | 'S4' | 'systole' | 'diastole' | 'murmur' | 'click' | 'noise';
  start_ms: number;
  end_ms: number;
  cycle_no?: number | null;
  peak_amplitude?: number | null;
  energy?: number | null;
  dominant_freq_hz?: number | null;
  confidence?: number | null;
}
export type AiReport = G['AiReportOut'];
export type AiReportNurse = Pick<AiReport, 'id' | 'status' | 'summary' | 'findings' | 'red_flags' | 'disclaimer' | 'created_at'> &
  Partial<Pick<AiReport, 'differential_diagnoses' | 'recommended_tests' | 'patient_friendly_text'>>;
export type PrescriptionItem = G['PrescriptionItemOut'];
export type Prescription = G['PrescriptionOut'];
export type Conclusion = G['ConclusionOut'];
export type ConclusionInput = G['ConclusionIn'];
export type ExamStatusInfo = G['StatusOut'];
export interface PatientBrief { id: string; mrn: string; full_name: string; age: number; gender: Gender }
export interface StatusHistoryItem { from: ExamStatus | null; to: ExamStatus; at: string; by?: string | null; by_name?: string | null; reason?: string | null }
export type ExamDetail = Omit<G['ExamDetail'], 'patient' | 'report' | 'prescription' | 'conclusion' | 'status_history' | 'recordings' | 'analysis'> & {
  patient: PatientBrief;
  recordings: Recording[];
  analysis: AnalysisResult | null;
  report: AiReport | AiReportNurse | null;
  prescription: Prescription | null;
  conclusion: Conclusion | null;
  status_history: StatusHistoryItem[];
};
export interface WaveformPeaks { sample_rate: number; samples_per_pixel: number; data: number[] }

// ---- Audit / notifications / settings ----
export interface AuditLogItem {
  id: number;
  ts: string;
  user?: { id: string; username: string; role: Role } | null;
  action: AuditAction;
  resource_type?: string | null;
  resource_id?: string | null;
  patient_id?: string | null;
  ip?: string | null;
  user_agent?: string | null;
  request_id?: string | null;
  method?: string | null;
  path?: string | null;
  status_code?: number | null;
  success: boolean;
  changes?: { before?: unknown; after?: unknown } | null;
  meta?: Record<string, unknown>;
}
export interface NotificationItem {
  id: string;
  type: NotificationType;
  title: string;
  body?: string | null;
  payload: Record<string, unknown>;
  is_read: boolean;
  created_at: string;
}
export type SettingValueType = 'int' | 'float' | 'bool' | 'string' | 'json';
export interface SettingItem {
  key: string;
  value: unknown;
  value_type: SettingValueType;
  description?: string | null;
  is_public?: boolean;
  updated_at?: string;
}
/** GET /system/health/deep (backend/app/api/v1/system.py): per-check strings such as "ok", "configured", "missing", "error: X". */
export interface HealthDeep {
  status: string;
  checks?: Record<string, string>;
  job_runner?: string;
}

// ---- Analytics (admin) ----
export interface KpiValue { value: number | null; delta_pct?: number | null }
export interface AdminKpis { period: { from: string; to: string }; kpis: Record<string, KpiValue> }
export interface TimeseriesPoint { t: string; value: number }
export interface Timeseries {
  metric: string;
  granularity: string;
  series: TimeseriesPoint[];
  series_by?: Record<string, TimeseriesPoint[]> | null;
}
export interface Distribution { dimension: string; total: number; items: { key: string; count: number; pct: number }[] }
export interface WorkloadResponse {
  doctors: { user_id: string; full_name: string; assigned: number; completed: number; pending: number; avg_time_to_conclusion_min?: number; agreement_pct?: number }[];
  nurses: { user_id: string; full_name: string; exams_created: number; recordings_uploaded: number; rejected_recordings: number; avg_recordings_per_exam?: number }[];
  queue: { queued: number; processing: number; ai_ready: number; in_review: number; oldest_pending_min?: number | null };
}
export interface HeatmapResponse { items: { dow: number; hour: number; value: number }[] }
export interface AiPerformance {
  model_versions: {
    version: string; n: number; agreement_pct: number; partial_pct: number; disagree_pct: number; avg_confidence: number;
    confusion_matrix?: { labels: string[]; matrix: number[][] };
  }[];
  llm?: { avg_latency_ms: number; total_tokens: number; cost_usd: number; error_rate_pct: number };
}
export interface SystemAnalytics {
  api_p50_ms?: number; api_p95_ms?: number; queue?: Record<string, number>; errors?: number; disk_used_pct?: number;
  recent_errors?: { ts: string; source: string; message: string }[];
  [k: string]: unknown;
}

// ---- Drug knowledge base (admin): NOT in doc 01; paths follow doc 03 section 3.22 (backend gap, see README) ----
export type InteractionLevel = 'minor' | 'moderate' | 'major' | 'contraindicated';
export type DrugStatus = 'draft' | 'published' | 'archived';
export interface DrugListItem {
  id: string;
  inn: string;
  trade_names: string[];
  group: string;
  version: number;
  status: DrugStatus;
  updated_at: string;
}
export interface DrugDetail extends DrugListItem {
  atc_code?: string | null;
  forms: string[];
  indications_icd10: string[];
  dose_rules: { population: string; min_dose: number; max_dose: number; unit: string; max_daily?: number | null; note?: string }[];
  contraindications: { text: string; absolute: boolean }[];
  side_effects: { text: string; frequency: 'common' | 'uncommon' | 'rare' }[];
  interactions: { drug_id: string; drug_name?: string; level: InteractionLevel; mechanism: string; recommendation: string }[];
  sources: { title: string; url: string }[];
}

// ---- Export ----
export interface ExportJob {
  export_id: string;
  status: JobStatus;
  file_url?: string | null;
  size_bytes?: number | null;
  error?: string | null;
}
