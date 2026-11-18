import { http, HttpResponse, delay } from 'msw';
import { clinicalHandlers } from './clinical-handlers';
import { auditItems, drugs, exams, MOCK_PASSWORD, notifications, patients, settings, users } from './data';
import type { UserListItem } from '@/shared/api/types';

const B = '/api/v1';

/** Fake unsigned JWT with a 15 minute exp (the client only reads `exp` to schedule refresh). */
function fakeJwt(sub: string, role: string): string {
  const enc = (o: unknown) => btoa(JSON.stringify(o)).replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_');
  return `${enc({ alg: 'none' })}.${enc({ sub, role, exp: Math.floor(Date.now() / 1000) + 900 })}.mock`;
}

let session: UserListItem | null = null;
const db = { users: [...users], settings: settings.map((s) => ({ ...s })), notifications: notifications.map((n) => ({ ...n })), drugs: drugs.map((d) => ({ ...d })) };

const sessionUser = (u: UserListItem) => ({ id: u.id, username: u.username, full_name: u.full_name, role: u.role, locale: 'uz', must_change_password: !!u.must_change_password });
const err = (status: number, code: string, message: string, details?: unknown) => HttpResponse.json({ error: { code, message, details, request_id: 'mock-req-1' } }, { status });
const page = <T,>(items: T[], req: Request, extra: Record<string, unknown> = {}) => {
  const url = new URL(req.url);
  const limit = Number(url.searchParams.get('limit') ?? url.searchParams.get('page_size') ?? 20);
  const cursor = Number(url.searchParams.get('cursor') ?? 0);
  const pageNo = Number(url.searchParams.get('page') ?? 0);
  const start = pageNo ? (pageNo - 1) * limit : cursor;
  const slice = items.slice(start, start + limit);
  const next = start + limit < items.length ? String(start + limit) : null;
  return HttpResponse.json({ items: slice, page: { limit, next_cursor: pageNo ? undefined : next, total: items.length }, total: items.length, ...extra });
};

const series = (days: number, base: number) => Array.from({ length: days }, (_, i) => ({ t: new Date(Date.UTC(2026, 10, 18 - (days - 1 - i))).toISOString().slice(0, 10), value: Math.round(base + Math.sin(i / 2) * base * 0.4 + (i % 5)) }));

const baseHandlers = [
  // ---- auth
  http.post(`${B}/auth/login`, async ({ request }) => {
    const { username, password } = (await request.json()) as { username: string; password: string };
    const u = db.users.find((x) => x.username === username);
    if (!u || password !== MOCK_PASSWORD) return err(401, 'INVALID_CREDENTIALS', 'Foydalanuvchi nomi yoki parol noto\'g\'ri');
    if (u.status === 'suspended') return err(403, 'ACCOUNT_SUSPENDED', 'suspended');
    session = u;
    return HttpResponse.json({ access_token: fakeJwt(u.id, u.role), token_type: 'bearer', expires_in: 900, user: sessionUser(u) });
  }),
  http.post(`${B}/auth/refresh`, () => (session ? HttpResponse.json({ access_token: fakeJwt(session.id, session.role), token_type: 'bearer', expires_in: 900 }) : err(401, 'REFRESH_INVALID', 'no session'))),
  http.post(`${B}/auth/logout`, () => { session = null; return new HttpResponse(null, { status: 204 }); }),
  http.post(`${B}/auth/logout-all`, () => new HttpResponse(null, { status: 204 })),
  http.get(`${B}/auth/me`, ({ request }) => { const u = session ?? (request.headers.get('authorization') ? db.users[0]! : null); return u ? HttpResponse.json({ ...sessionUser(u), email: null, phone: u.phone ?? null, permissions: [] }) : err(401, 'UNAUTHENTICATED', 'no token'); }),
  http.patch(`${B}/auth/me`, async ({ request }) => HttpResponse.json({ ...(session ? sessionUser(session) : {}), ...(await request.json() as object) })),
  http.post(`${B}/auth/change-password`, async ({ request }) => {
    const b = (await request.json()) as { current_password: string };
    if (b.current_password !== MOCK_PASSWORD) return err(400, 'WRONG_CURRENT_PASSWORD', 'wrong');
    if (session) session.must_change_password = false;
    return new HttpResponse(null, { status: 204 });
  }),
  http.post(`${B}/auth/reset-password`, () => new HttpResponse(null, { status: 204 })),

  // ---- users
  http.get(`${B}/users`, ({ request }) => {
    const p = new URL(request.url).searchParams;
    let list = db.users;
    if (p.get('role')) list = list.filter((u) => u.role === p.get('role'));
    if (p.get('status')) list = list.filter((u) => u.status === p.get('status'));
    const q = p.get('q')?.toLowerCase();
    if (q) list = list.filter((u) => u.username.includes(q) || u.full_name.toLowerCase().includes(q));
    return page(list, request);
  }),
  http.post(`${B}/users`, async ({ request }) => {
    const b = (await request.json()) as UserListItem & { password: string };
    if (db.users.some((u) => u.username === b.username)) return err(409, 'USERNAME_TAKEN', 'taken', [{ field: 'username', msg: 'Bu foydalanuvchi nomi band' }]);
    const u: UserListItem = { id: `u-${Date.now()}`, username: b.username, full_name: b.full_name, role: b.role, status: 'active', created_at: new Date().toISOString(), must_change_password: true };
    db.users.push(u);
    return HttpResponse.json(u, { status: 201 });
  }),
  http.get(`${B}/users/:id`, ({ params }) => { const u = db.users.find((x) => x.id === params.id); return u ? HttpResponse.json(u) : err(404, 'NOT_FOUND', 'not found'); }),
  http.patch(`${B}/users/:id`, async ({ params, request }) => { const u = db.users.find((x) => x.id === params.id); if (!u) return err(404, 'NOT_FOUND', 'nf'); Object.assign(u, await request.json()); return HttpResponse.json(u); }),
  http.post(`${B}/users/:id/reset-password`, () => HttpResponse.json({ temporary_password: 'Tmp-Mock-Reset-2026!' })),
  http.post(`${B}/users/:id/:action`, ({ params }) => { const u = db.users.find((x) => x.id === params.id); if (u && params.action === 'suspend') u.status = 'suspended'; if (u && params.action === 'activate') u.status = 'active'; return new HttpResponse(null, { status: 204 }); }),
  http.delete(`${B}/users/:id`, () => new HttpResponse(null, { status: 204 })),

  // ---- patients / exams
  http.get(`${B}/patients`, ({ request }) => {
    const p = new URL(request.url).searchParams;
    const q = p.get('q')?.toLowerCase();
    let list = patients;
    if (q) list = list.filter((x) => x.full_name.toLowerCase().includes(q) || x.mrn.toLowerCase().includes(q));
    if (p.get('gender')) list = list.filter((x) => x.gender === p.get('gender'));
    return page(list, request);
  }),
  http.get(`${B}/patients/:id`, ({ params }) => { const p = patients.find((x) => x.id === params.id); return p ? HttpResponse.json({ ...p, last_name: p.full_name.split(' ')[0], first_name: 'X', blood_group: 'A+', allergies: p.has_allergies ? [{ id: 'a1', substance: 'Penitsillin', severity: 'severe', is_active: true }] : [], medical_history: [{ id: 'h1', kind: 'chronic', title: 'Gipertoniya', icd10_code: 'I10', is_active: true }], current_medications: [], stats: { exam_count: p.exam_count, last_exam_at: p.last_exam_at } }) : err(404, 'NOT_FOUND', 'nf'); }),
  http.get(`${B}/examinations`, ({ request }) => {
    const p = new URL(request.url).searchParams;
    const st = p.getAll('status');
    let list = exams;
    if (st.length) list = list.filter((e) => st.includes(e.status));
    if (p.get('patient_id')) list = list.filter((e) => e.patient.id === p.get('patient_id'));
    return page(list, request);
  }),
  http.get(`${B}/examinations/:id`, ({ params }) => { const e = exams.find((x) => x.id === params.id); return e ? HttpResponse.json({ ...e, recordings: [], status_history: [{ from: null, to: 'draft', at: e.examined_at }, { from: 'draft', to: e.status, at: e.examined_at }], version: 1, analysis: e.ai ? { id: 'a', model_version: 'pcg-cnn-1.0.0', pcg_class: e.ai.pcg_class, class_probs: {}, confidence: e.ai.confidence, severity: e.ai.severity, quality_ok: true } : null }) : err(404, 'NOT_FOUND', 'nf'); }),
  http.get(`${B}/examinations/:id/segments`, () => HttpResponse.json({ items: [] })),

  // ---- notifications
  http.get(`${B}/notifications`, ({ request }) => page(db.notifications, request)),
  http.get(`${B}/notifications/unread-count`, () => HttpResponse.json({ count: db.notifications.filter((n) => !n.is_read).length })),
  http.post(`${B}/notifications/read-all`, () => { db.notifications.forEach((n) => (n.is_read = true)); return new HttpResponse(null, { status: 204 }); }),
  http.post(`${B}/notifications/:id/read`, ({ params }) => { const n = db.notifications.find((x) => x.id === params.id); if (n) n.is_read = true; return new HttpResponse(null, { status: 204 }); }),

  // ---- audit / settings / system
  http.get(`${B}/audit-logs`, ({ request }) => page(auditItems, request)),
  http.get(`${B}/audit-logs/export`, () => new HttpResponse('\uFEFFid,ts\n1,2026-11-18', { headers: { 'content-type': 'text/csv', 'content-disposition': 'attachment; filename="audit.csv"' } })),
  http.get(`${B}/settings`, () => HttpResponse.json(db.settings)),
  http.patch(`${B}/settings`, async ({ request }) => { const b = (await request.json()) as Record<string, unknown>; for (const s of db.settings) if (s.key in b) s.value = b[s.key]; return HttpResponse.json(db.settings); }),
  http.get(`${B}/system/health/deep`, () => HttpResponse.json({ status: 'ok', checks: { database: 'ok', redis: 'ok', storage: 'ok', analysis_service: 'configured', deepseek_key: 'configured', clamav: 'not_configured' }, job_runner: 'celery' })),

  // ---- analytics (admin)
  http.get(`${B}/analytics/admin/kpis`, async () => { await delay(150); return HttpResponse.json({ period: { from: '2026-10-19', to: '2026-11-18' }, kpis: { examinations_total: { value: 356, delta_pct: 11.5 }, active_users: { value: 19, delta_pct: 5.5 }, avg_ai_processing_sec: { value: 9.8, delta_pct: -3 }, failed_analyses: { value: 3, delta_pct: -50 }, storage_used_gb: { value: 12.4, delta_pct: null }, llm_cost_usd: { value: 4.31, delta_pct: 10 } } }); }),
  http.get(`${B}/analytics/admin/timeseries`, ({ request }) => { const m = new URL(request.url).searchParams.get('metric'); return HttpResponse.json({ metric: m, granularity: 'day', series: series(30, m === 'completed' ? 9 : 12) }); }),
  http.get(`${B}/analytics/admin/distributions`, ({ request }) => {
    const d = new URL(request.url).searchParams.get('dimension');
    const items = d === 'age_group' ? [['0-17', 12], ['18-39', 64], ['40-59', 120], ['60-74', 110], ['75+', 50]] : d === 'severity' ? [['none', 219], ['mild', 60], ['moderate', 52], ['severe', 20], ['critical', 5]] : [['normal', 219], ['murmur', 105], ['extra_heart_sound', 19], ['artifact', 13]];
    const total = items.reduce((a, [, c]) => a + (c as number), 0);
    return HttpResponse.json({ dimension: d, total, items: items.map(([key, count]) => ({ key, count, pct: Math.round(((count as number) / total) * 1000) / 10 })) });
  }),
  http.get(`${B}/analytics/admin/workload`, () => HttpResponse.json({ doctors: [{ user_id: 'u-doc', full_name: 'Karimov Aziz', assigned: 58, completed: 52, pending: 6 }, { user_id: 'd2', full_name: 'Yusupova Madina', assigned: 40, completed: 38, pending: 2 }], nurses: [], queue: { queued: 2, processing: 1, ai_ready: 9, in_review: 5, oldest_pending_min: 134 } })),
  http.get(`${B}/analytics/admin/heatmap`, () => HttpResponse.json({ items: Array.from({ length: 7 * 24 }, (_, i) => ({ dow: Math.floor(i / 24) + 1, hour: i % 24, value: (i % 24 >= 8 && i % 24 <= 17 ? 10 : 1) + (i % 5) })) })),
  http.get(`${B}/analytics/admin/ai-performance`, () => HttpResponse.json({ model_versions: [{ version: 'pcg-cnn-1.0.0', n: 301, agreement_pct: 86.7, partial_pct: 8, disagree_pct: 5.3, avg_confidence: 0.82 }], llm: { avg_latency_ms: 3100, total_tokens: 842113, cost_usd: 4.31, error_rate_pct: 0.9 } })),
  http.get(`${B}/analytics/admin/system`, () => HttpResponse.json({ api_p50_ms: 42, api_p95_ms: 180, recent_errors: [{ ts: '2026-11-18T08:00:00Z', source: 'asr', message: 'Timeout' }] })),

  // ---- drugs KB (paths per doc 03)
  http.get(`${B}/admin/drugs`, ({ request }) => page(db.drugs.map(({ id, inn, trade_names, group, version, status, updated_at }) => ({ id, inn, trade_names, group, version, status, updated_at })), request)),
  http.get(`${B}/admin/drugs/:id`, ({ params }) => { const d = db.drugs.find((x) => x.id === params.id); return d ? HttpResponse.json(d) : err(404, 'NOT_FOUND', 'nf'); }),
  http.post(`${B}/admin/drugs`, async ({ request }) => { const b = (await request.json()) as object; const d = { id: `d-${Date.now()}`, version: 1, status: 'draft', updated_at: new Date().toISOString(), ...b } as (typeof db.drugs)[number]; db.drugs.push(d); return HttpResponse.json(d, { status: 201 }); }),
  http.put(`${B}/admin/drugs/:id`, async ({ params, request }) => { const d = db.drugs.find((x) => x.id === params.id); if (!d) return err(404, 'NOT_FOUND', 'nf'); Object.assign(d, await request.json(), { version: d.version + 1 }); return HttpResponse.json(d); }),
  http.post(`${B}/admin/drugs/:id/:action`, ({ params }) => { const d = db.drugs.find((x) => x.id === params.id); if (d) d.status = params.action === 'publish' ? 'published' : 'archived'; return HttpResponse.json(d); }),

  // ---- export
  http.post(`${B}/export/csv`, () => HttpResponse.json({ export_id: 'exp-1' }, { status: 202 })),
  http.get(`${B}/export/:id`, () => HttpResponse.json({ export_id: 'exp-1', status: 'succeeded', file_url: '/mock/exp-1.csv', size_bytes: 20480 })),
];

// clinical handlers first: they override the minimal examination handlers above
export const handlers = [...clinicalHandlers, ...baseHandlers];
