import { http, HttpResponse } from 'msw';
import { exams, patients } from './data';

const B = '/api/v1';
const roleOf = (req: Request) => (req.headers.get('authorization') ?? '').replace('Bearer ', '').replace('tok-', '');
const err = (status: number, code: string, message: string) => HttpResponse.json({ error: { code, message, request_id: 'mock-req' } }, { status });

const recording = (id = 'r-1', site = 'mitral') => ({
  id, examination_id: 'e-2', kind: 'audio', site, status: 'validated', original_filename: `${site}.wav`, mime_type: 'audio/wav', ext: 'wav', size_bytes: 2_000_000, sha256: 'x'.repeat(64),
  duration_sec: 15, sample_rate_hz: 4000, channels: 1, snr_db: 18.5, quality_score: 0.82, validation_report: { warnings: [] }, scan_status: 'clean', url: `/api/v1/recordings/${id}/file`, created_at: '2026-11-18T09:00:00Z',
});

const analysis = { id: 'a-1', model_version: 'pcg-cnn-1.0.0', pcg_class: 'murmur', class_probs: { normal: 0.09, murmur: 0.84, extra_heart_sound: 0.04, artifact: 0.03 }, confidence: 0.84, severity: 'moderate', murmur_timing: 'systolic', murmur_grade: 3, murmur_shape: 'holosystolic', heart_rate_bpm: 86.4, hr_variability_ms: 18.2, s1_count: 21, s2_count: 21, mean_s1_s2_ms: 312.5, mean_s2_s1_ms: 384.1, systole_ms: 312.5, diastole_ms: 384.1, dominant_freq_hz: 145, quality_ok: true, is_current: true, recordings: [], created_at: '2026-11-18T09:35:00Z' };

const reportFull = {
  id: 'rep-1', status: 'ready', llm_model: 'deepseek-chat', prompt_version: 'v3', summary: 'Mitral nuqtada holosistolik shovqin aniqlandi.', findings: {}, red_flags: [],
  differential_diagnoses: [{ name: 'Mitral yetishmovchilik', icd10: 'I34.0', likelihood: 'high', rationale: 'Holosistolik shovqin' }, { name: 'Mitral prolaps', icd10: 'I34.1', likelihood: 'medium', rationale: 'Klik' }],
  recommended_tests: ['Exo-KG'], patient_friendly_text: null, disclaimer: 'AI faqat qo\'llab-quvvatlash', created_at: '2026-11-18T09:36:00Z',
};

const prescription = {
  id: 'rx-1', status: 'suggested', disclaimer: 'AI taklifi. Faqat ma\'lumot uchun; shifokor tasdiqlaydi.', version: 1,
  safety_check: { allergy_conflicts: [{ item_id: 'i-2', allergen: 'Penitsillin', severity: 'severe' }], interactions: [], contraindications: [] },
  items: [
    { id: 'i-1', source: 'ai', drug_name: 'Furosemid', dose: '20 mg', route: 'oral', frequency: 'kuniga 1 marta', duration_days: 14, rationale: 'Hajm yuklamasi', contraindications: ['Anuriya'], side_effects: ['Gipokaliemiya'], interaction_warnings: [], allergy_warning: false, safety_pending: false, status: 'suggested', sort_order: 0 },
    { id: 'i-2', source: 'ai', drug_name: 'Amoksitsillin', dose: '500 mg', route: 'oral', frequency: 'kuniga 3 marta', duration_days: 7, contraindications: [], side_effects: [], interaction_warnings: [{ items: ['Amoksitsillin', 'Varfarin'], level: 'major', note: 'Qon ketish xavfi' }], allergy_warning: true, safety_pending: false, status: 'suggested', sort_order: 1 },
  ],
};

const wiz: { exam: Record<string, unknown> | null; recs: unknown[] } = { exam: null, recs: [] };

function detail(id: string, role: string) {
  if (id === 'e-new' && wiz.exam) return { ...wiz.exam, recordings: wiz.recs };
  const e = exams.find((x) => x.id === id);
  if (!e) return null;
  const doctor = role === 'doctor';
  const completed = e.status === 'completed';
  const hasAi = ['ai_ready', 'in_review', 'completed'].includes(e.status);
  return {
    ...e, complaints: 'Nafas qisilishi', symptoms: ['dyspnea'], patient_position: 'sitting', heart_rate_bpm: 88, bp_systolic: 135, bp_diastolic: 85, spo2_pct: 97, temperature_c: 36.6, weight_kg_at_exam: 80,
    ai_requested_at: null, ai_completed_at: null, completed_at: null, cancel_reason: null, failure_reason: e.status === 'failed' ? 'AUDIO_CORRUPT' : null, version: 1,
    recordings: hasAi || e.status === 'uploaded' ? [recording('r-1', 'mitral'), recording('r-2', 'aortic')] : [],
    analysis: hasAi ? analysis : null,
    report: hasAi ? (doctor || role === 'admin' ? reportFull : { id: 'rep-1', status: 'ready', summary: reportFull.summary, findings: {}, red_flags: [], disclaimer: reportFull.disclaimer, created_at: reportFull.created_at }) : null,
    prescription: doctor && hasAi ? prescription : null,
    conclusion: completed ? { id: 'c-1', examination_id: id, doctor_id: 'u-doc', status: 'signed', diagnosis_text: 'Mitral yetishmovchilik, o\'rtacha daraja (ehtimoliy).', icd10_codes: ['I34.0'], final_pcg_class: 'murmur', final_severity: 'moderate', agreement_with_ai: 'agree', recommendations: 'Exo-KG, 2 haftadan so\'ng nazorat.', follow_up_date: null, signed_at: '2026-11-18T10:05:00Z', signature_hash: 'a1b2c3d4e5f6a7b8', is_current: true, version: 1, created_at: '2026-11-18T10:00:00Z', updated_at: '2026-11-18T10:05:00Z' } : null,
    status_history: [{ from: null, to: 'draft', at: e.examined_at, by_name: 'Aliyeva Dilnoza' }, { from: 'draft', to: e.status, at: e.examined_at }],
    created_at: e.examined_at, updated_at: e.examined_at,
  };
}

const kpis = (o: Record<string, number | null>) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, { value: v }]));

export const clinicalHandlers = [
  http.get(`${B}/examinations/:id`, ({ params, request }) => { const d = detail(String(params.id), roleOf(request)); return d ? HttpResponse.json(d) : err(404, 'NOT_FOUND', 'nf'); }),
  http.get(`${B}/examinations/:id/status`, ({ params }) => { const e = exams.find((x) => x.id === params.id); return HttpResponse.json({ status: e?.status ?? 'draft', job: e?.status === 'processing' ? { id: 'j1', status: 'running', stage: 'classifying', progress_pct: 62, attempt: 1 } : null, history: [] }); }),
  http.get(`${B}/examinations/:id/events`, () => new HttpResponse(null, { status: 503 })),
  http.post(`${B}/examinations`, async ({ request }) => {
    wiz.recs = [];
    wiz.exam = { ...detail('e-6', 'nurse'), id: 'e-new', exam_no: 'E-NEW', status: 'draft', patient: { id: 'p-1', mrn: patients[0]!.mrn, full_name: patients[0]!.full_name, age: 70, gender: 'male' }, recordings: [], ...(await request.json() as object) };
    return HttpResponse.json(wiz.exam, { status: 201 });
  }),
  http.patch(`${B}/examinations/:id`, async ({ params, request }) => {
    const body = (await request.json()) as object;
    if (params.id === 'e-new' && wiz.exam) wiz.exam = { ...wiz.exam, ...body };
    return HttpResponse.json({ ...(detail(String(params.id), 'nurse') ?? detail('e-6', 'nurse')), ...body });
  }),
  http.post(`${B}/examinations/:id/recordings`, () => { const r = recording('r-new', 'mitral'); wiz.recs.push(r); return HttpResponse.json(r, { status: 201 }); }),
  http.post(`${B}/examinations/:id/analyze`, () => HttpResponse.json({ job_id: 'j1', status: 'pending', exam_status: 'queued', events: '/x' }, { status: 202 })),
  http.post(`${B}/examinations/:id/reanalyze`, () => HttpResponse.json({ job_id: 'j2', status: 'pending', exam_status: 'queued', events: '/x' }, { status: 202 })),
  http.get(`${B}/examinations/:id/conclusion`, () => err(404, 'NOT_FOUND', 'Xulosa')),
  http.put(`${B}/examinations/:id/conclusion`, async ({ request }) => HttpResponse.json({ id: 'c-1', status: 'draft', version: 1, is_current: true, ...(await request.json() as object) })),
  http.post(`${B}/examinations/:id/conclusion/sign`, () => HttpResponse.json({ id: 'c-1', status: 'signed', exam_status: 'completed' })),
  http.get(`${B}/examinations/:id/conclusion/history`, () => HttpResponse.json([])),
  http.post(`${B}/prescription-items/:id/approve`, () => HttpResponse.json(prescription)),
  http.post(`${B}/prescription-items/:id/reject`, () => HttpResponse.json(prescription)),
  http.get(`${B}/users/doctors`, () => HttpResponse.json([{ id: 'u-doc', full_name: 'Karimov Aziz', specialty: 'Kardiolog' }])),
  http.get(`${B}/settings/public`, () => HttpResponse.json({ 'upload.max_audio_mb': 25, 'audio.min_duration_sec': 5, 'audio.max_duration_sec': 120 })),
  http.post(`${B}/patients`, () => HttpResponse.json({ id: 'p-new' }, { status: 201 })),
  http.patch(`${B}/patients/:id`, () => HttpResponse.json({ id: 'p-1' })),

  http.get(`${B}/analytics/doctor/kpis`, () => HttpResponse.json({ period: { from: '2026-10-19', to: '2026-11-18' }, kpis: kpis({ my_pending: 6, my_completed_today: 9, my_completed_period: 52, avg_time_to_conclusion_min: 41.2, urgent_waiting: 2, ai_agreement_pct: 88.5, overrides_count: 6, patients_seen: 47, follow_ups_due_7d: 11 }) })),
  http.get(`${B}/analytics/doctor/queue`, () => HttpResponse.json({ items: [{ exam_id: 'e-2', exam_no: 'E-20261118-0002', priority: 'urgent', patient: { id: 'p-2', mrn: 'P-2026-000002', full_name: 'Karimov Jasur', age: 54, gender: 'male' }, severity: 'moderate', ai_class: 'murmur', waiting_min: 38 }] })),
  http.get(`${B}/analytics/doctor/timeseries`, () => HttpResponse.json({ metric: 'completed', granularity: 'day', series: Array.from({ length: 14 }, (_, i) => ({ t: `2026-11-${String(i + 1).padStart(2, '0')}`, value: 3 + (i % 5) })) })),
  http.get(`${B}/analytics/doctor/distributions`, ({ request }) => { const d = new URL(request.url).searchParams.get('dimension'); return HttpResponse.json({ dimension: d, total: 52, items: d === 'age_group' ? [{ key: '40-59', count: 20, pct: 38 }, { key: '60-74', count: 32, pct: 62 }] : [{ key: 'normal', count: 30, pct: 58 }, { key: 'murmur', count: 22, pct: 42 }] }); }),
  http.get(`${B}/analytics/doctor/ai-vs-doctor`, () => HttpResponse.json({ total: 52, agree: 46, partial: 4, disagree: 2, agreement_pct: 88.5, weighted_agreement_pct: 90.4, disagreements: [], trend: [{ t: '2026-W45', agreement_pct: 85 }] })),
  http.get(`${B}/analytics/doctor/follow-ups`, () => HttpResponse.json({ items: [{ exam_id: 'e-1', exam_no: 'E-20261118-0001', follow_up_date: '2026-12-02', notes: null, patient: { id: 'p-1', mrn: 'P-2026-000001', full_name: 'Rahimov Aziz', age: 70, gender: 'male' } }] })),
  http.get(`${B}/analytics/nurse/kpis`, () => HttpResponse.json({ exams_created_today: 8, exams_created_period: 8, recordings_uploaded: 21, rejected_recordings: 1, avg_recording_quality: 0.79, awaiting_ai: 2 })),
];
