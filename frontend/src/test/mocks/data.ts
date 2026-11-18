/**
 * Deterministic fixtures for the MSW layer. DEV/TEST ONLY: this directory is never imported from production
 * code paths (see scripts/check-bundle.mjs which fails the build if MSW leaks into dist/).
 */
import type { UserListItem, PatientListItem, ExamListItem, AuditLogItem, SettingItem, DrugDetail, NotificationItem, ExamStatus, PcgClass, Severity } from '@/shared/api/types';

export const MOCK_PASSWORD = 'Mock-Pass-2026!';

export const users: UserListItem[] = [
  { id: 'u-admin', username: 'admin.demo', full_name: 'Administrator Demo', role: 'admin', status: 'active', created_at: '2026-10-01T08:00:00Z', last_login_at: '2026-11-18T07:00:00Z', must_change_password: false },
  { id: 'u-doc', username: 'doctor.demo', full_name: 'Karimov Aziz', role: 'doctor', status: 'active', specialty: 'Kardiolog', license_no: 'KD-2231', created_at: '2026-10-02T08:00:00Z', last_login_at: '2026-11-18T06:30:00Z', must_change_password: false },
  { id: 'u-nurse', username: 'nurse.demo', full_name: 'Aliyeva Dilnoza', role: 'nurse', status: 'active', department: 'Kardiologiya', created_at: '2026-10-03T08:00:00Z', last_login_at: null, must_change_password: false },
];

const first = ['Aziz', 'Jasur', 'Malika', 'Dilnoza', 'Sardor', 'Zilola', 'Bobur', 'Nodira'];
const last = ['Rahimov', 'Karimov', 'Aliyeva', 'Yusupov', 'Tursunov', 'Ergasheva'];

export const patients: PatientListItem[] = Array.from({ length: 57 }, (_, i) => ({
  id: `p-${i + 1}`,
  mrn: `P-2026-${String(i + 1).padStart(6, '0')}`,
  full_name: `${last[i % last.length]} ${first[i % first.length]} Anvarovich`,
  birth_date: `${1950 + (i % 45)}-04-12`,
  age: 76 - (i % 45),
  gender: i % 2 ? 'female' : 'male',
  phone: `+99890${String(1000000 + i * 137).slice(0, 7)}`,
  last_exam_at: '2026-11-10T08:15:00Z',
  exam_count: (i % 5) + 1,
  has_allergies: i % 4 === 0,
}));

const statuses: ExamStatus[] = ['completed', 'ai_ready', 'processing', 'failed', 'in_review', 'uploaded'];
const classes: PcgClass[] = ['normal', 'murmur', 'extra_heart_sound', 'normal'];
const sev: Severity[] = ['none', 'moderate', 'mild', 'severe'];

export const exams: ExamListItem[] = Array.from({ length: 43 }, (_, i) => ({
  id: `e-${i + 1}`,
  exam_no: `E-20261118-${String(i + 1).padStart(4, '0')}`,
  patient: { id: `p-${(i % 57) + 1}`, mrn: patients[i % 57]!.mrn, full_name: patients[i % 57]!.full_name, age: patients[i % 57]!.age, gender: patients[i % 57]!.gender },
  status: statuses[i % statuses.length]!,
  priority: i % 7 === 0 ? 'urgent' : 'routine',
  examined_at: `2026-11-${String(1 + (i % 17)).padStart(2, '0')}T09:30:00Z`,
  assigned_doctor: { id: 'u-doc', full_name: 'Karimov Aziz' },
  performed_by: { id: 'u-nurse', full_name: 'Aliyeva Dilnoza' },
  recording_count: (i % 3) + 1,
  ai: i % 6 === 5 ? null : { pcg_class: classes[i % 4]!, severity: sev[i % 4]!, confidence: 0.6 + (i % 4) / 10 },
  conclusion_status: null,
}));

export const auditItems: AuditLogItem[] = Array.from({ length: 120 }, (_, i) => ({
  id: 1000 - i,
  ts: new Date(Date.UTC(2026, 10, 18, 9, 30) - i * 600_000).toISOString(),
  user: i % 9 === 0 ? null : { id: 'u-doc', username: i % 2 ? 'doctor.demo' : 'nurse.demo', role: i % 2 ? 'doctor' : 'nurse' },
  action: (['login', 'read', 'update', 'upload', 'ai_call', 'login_failed', 'sign'] as const)[i % 7]!,
  resource_type: i % 3 ? 'examination' : 'patient',
  resource_id: `0192a1b2-0000-7000-8000-${String(i).padStart(12, '0')}`,
  ip: '10.0.0.8',
  request_id: `01JC8M7Q2V6Y0W3K9N5R4T1X${String(i).padStart(2, '0')}`,
  method: 'POST',
  path: '/api/v1/examinations',
  status_code: i % 7 === 5 ? 401 : 200,
  success: i % 7 !== 5,
  changes: i % 7 === 2 ? { before: { status: 'draft', complaints: null }, after: { status: 'uploaded', complaints: 'Nafas qisilishi' } } : null,
  meta: i % 7 === 4 ? { model: 'deepseek-chat', tokens: 1840, latency_ms: 2100 } : {},
}));

export const settings: SettingItem[] = [
  { key: 'upload.max_audio_mb', value: 25, value_type: 'int' },
  { key: 'upload.max_image_mb', value: 10, value_type: 'int' },
  { key: 'upload.max_files_per_exam', value: 12, value_type: 'int' },
  { key: 'audio.min_duration_sec', value: 5, value_type: 'int' },
  { key: 'audio.max_duration_sec', value: 120, value_type: 'int' },
  { key: 'analysis.auto_start', value: true, value_type: 'bool' },
  { key: 'analysis.model_version', value: 'pcg-cnn-1.0.0', value_type: 'string' },
  { key: 'ai.llm_model', value: 'deepseek-chat', value_type: 'string' },
  { key: 'ai.llm_enabled', value: true, value_type: 'bool' },
  { key: 'ai.drug_suggestions_enabled', value: true, value_type: 'bool' },
  { key: 'ai.critical_probability_threshold', value: 0.85, value_type: 'float' },
  { key: 'security.lockout_attempts', value: 5, value_type: 'int' },
  { key: 'security.lockout_minutes', value: 15, value_type: 'int' },
  { key: 'security.password_min_length', value: 10, value_type: 'int' },
  { key: 'retention.audit_days', value: 1825, value_type: 'int' },
  { key: 'retention.raw_llm_days', value: 90, value_type: 'int' },
  { key: 'clinic.name', value: 'CardioPCG klinikasi', value_type: 'string' },
];

export const drugs: DrugDetail[] = [
  {
    id: 'd-1', inn: 'Metoprolol', trade_names: ['Betalok'], group: 'Beta-bloker', version: 3, status: 'published', updated_at: '2026-10-02T10:00:00Z', atc_code: 'C07AB02', forms: ['tabletka'], indications_icd10: ['I10'],
    dose_rules: [{ population: 'Kattalar', min_dose: 25, max_dose: 200, unit: 'mg', max_daily: 200 }], contraindications: [{ text: 'AV blok II-III', absolute: true }], side_effects: [{ text: 'Bradikardiya', frequency: 'common' }],
    interactions: [{ drug_id: 'd-2', drug_name: 'Verapamil', level: 'major', mechanism: 'Aditiv AV o\'tkazuvchanlik sustlashuvi', recommendation: 'Birga qo\'llamang' }], sources: [{ title: 'ESC Guidelines', url: 'https://example.org/esc' }],
  },
  { id: 'd-2', inn: 'Verapamil', trade_names: ['Isoptin'], group: 'Kalsiy kanal blokeri', version: 1, status: 'draft', updated_at: '2026-10-05T10:00:00Z', atc_code: '', forms: [], indications_icd10: [], dose_rules: [], contraindications: [], side_effects: [], interactions: [], sources: [] },
];

export const notifications: NotificationItem[] = [
  { id: 'n-1', type: 'critical_finding', title: 'Kritik topilma: E-20261118-0003', body: 'Yuqori ehtimolli shovqin', payload: { examination_id: 'e-3' }, is_read: false, created_at: '2026-11-18T09:40:00Z' },
  { id: 'n-2', type: 'analysis_done', title: 'Tahlil tayyor: E-20261118-0001', body: null, payload: { examination_id: 'e-1' }, is_read: true, created_at: '2026-11-18T09:10:00Z' },
];
