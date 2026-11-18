import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { Api } from '../helpers/api';
import { WAV_FIXTURE, users } from '../helpers/env';
import { loginViaUi } from '../helpers/ui';

/**
 * Clinical flow (docs/03): nurse registers a patient and uploads a SYNTHETIC wav, the analysis runs on the Celery
 * worker, the doctor reviews / approves the prescription and signs the conclusion, the admin sees the audit trail.
 *
 * The nurse/doctor clinical SCREENS (wizard, review workspace) are still placeholders in the frontend, so those
 * steps are driven through the same REST API the UI uses; every page that exists is verified in the browser.
 * Replace the API steps with UI steps as the screens land (see the E2E section of the root README).
 */
test.describe.serial('nurse -> analysis -> doctor review', () => {
  const U = users();
  let examId = '';
  let examNo = '';
  let patientId = '';

  test('nurse creates a patient and an examination, uploads a synthetic PCG recording', async ({ request }) => {
    const nurse = await Api.login(request, U.nurse.username, U.nurse.password);

    const p = await nurse.post('/patients?force=true', {
      last_name: 'Sinov',
      first_name: 'Bemor',
      birth_date: '1970-05-17',
      gender: 'male',
      ai_consent: true,
    });
    expect(p.status(), await p.text()).toBe(201);
    patientId = (await p.json()).id;

    const e = await nurse.post('/examinations', { patient_id: patientId, complaints: 'Nafas qisilishi (sinov)' });
    expect(e.status(), await e.text()).toBe(201);
    const exam = await e.json();
    examId = exam.id;
    examNo = exam.exam_no;

    const up = await nurse.upload(
      `/examinations/${examId}/recordings`,
      { name: 'mitral.wav', mimeType: 'audio/wav', buffer: readFileSync(WAV_FIXTURE) },
      { site: 'mitral' },
    );
    expect(up.status(), await up.text()).toBe(201);

    const list = await (await nurse.get(`/examinations/${examId}/recordings`)).json();
    expect(list).toHaveLength(1);
  });

  test('upload validation: a non-audio file is rejected', async ({ request }) => {
    const nurse = await Api.login(request, U.nurse.username, U.nurse.password);
    const bad = await nurse.upload(
      `/examinations/${examId}/recordings`,
      { name: 'notes.wav', mimeType: 'audio/wav', buffer: Buffer.from('this is not audio at all') },
      { site: 'aortic' },
    );
    expect(bad.status(), await bad.text()).toBeGreaterThanOrEqual(400);
    expect(bad.status()).toBeLessThan(500);
  });

  test('nurse starts the analysis; worker finishes it', async ({ request }) => {
    test.setTimeout(300_000);
    const nurse = await Api.login(request, U.nurse.username, U.nurse.password);
    const r = await nurse.post(`/examinations/${examId}/analyze`);
    // the backend may already have queued the analysis right after the upload (then analyze answers 409 INVALID_STATE)
    if (r.status() !== 202) {
      expect(r.status(), await r.text()).toBe(409);
      expect(['queued', 'processing', 'ai_ready']).toContain((await r.json()).error.details.current);
    }

    await expect
      .poll(
        async () => {
          const st = (await (await nurse.get(`/examinations/${examId}/status`)).json()) as { status: string };
          if (st.status === 'failed') throw new Error('analysis failed');
          return st.status;
        },
        { timeout: 240_000, intervals: [2_000, 3_000, 5_000] },
      )
      .toMatch(/^(ai_ready|in_review)$/);
  });

  test('nurse cannot change the AI result, prescription or conclusion; cannot export before approval', async ({ request }) => {
    const nurse = await Api.login(request, U.nurse.username, U.nurse.password);
    expect((await nurse.post(`/examinations/${examId}/prescription/approve`)).status()).toBe(403);
    expect((await nurse.post(`/examinations/${examId}/report/regenerate`)).status()).toBe(403);
    expect((await nurse.put(`/examinations/${examId}/conclusion`, { diagnosis_text: 'x' })).status()).toBeGreaterThanOrEqual(400);
    expect([403, 404, 405]).toContain((await nurse.patch(`/examinations/${examId}/analysis`, { pcg_class: 'normal' })).status());
    expect((await nurse.get(`/examinations/${examId}/export/pdf`)).status()).toBe(403);
  });

  test('doctor reviews the analysis, approves the prescription and signs the conclusion', async ({ request }) => {
    const doctor = await Api.login(request, U.doctor.username, U.doctor.password);

    const analysis = await (await doctor.get(`/examinations/${examId}/analysis`)).json();
    expect(analysis.pcg_class).toBeTruthy();
    const segs = await (await doctor.get(`/examinations/${examId}/segments`)).json();
    expect(Array.isArray(segs.items)).toBe(true);

    // AI report may be "ready" (with DeepSeek) or "failed" (no key in dev): both are valid, the analysis itself must exist
    const report = await doctor.get(`/examinations/${examId}/report`);
    expect([200, 404]).toContain(report.status());

    // prescription: approve what is safe, explicitly reject what is left (warnings), then sign
    const rx = await doctor.get(`/examinations/${examId}/prescription`);
    if (rx.status() === 200) {
      await doctor.post(`/examinations/${examId}/prescription/approve`);
      const after = (await (await doctor.get(`/examinations/${examId}/prescription`)).json()) as {
        items: { id: string; status: string }[];
      };
      for (const it of after.items.filter((i) => !['approved', 'rejected'].includes(i.status))) {
        const rj = await doctor.post(`/prescription-items/${it.id}/reject`, { reason: 'E2E: tekshiruv uchun rad etildi' });
        expect(rj.status(), await rj.text()).toBe(200);
      }
    }

    const put = await doctor.put(`/examinations/${examId}/conclusion`, {
      diagnosis_text: 'Sinov xulosasi: patologik shovqin aniqlanmadi (sintetik signal)',
      icd10_codes: [],
      final_pcg_class: analysis.pcg_class,
      final_severity: analysis.severity,
      agreement_with_ai: 'agree',
      recommendations: 'Sinov: nazorat tavsiya etilmaydi',
    });
    expect(put.status(), await put.text()).toBe(200);

    const sign = await doctor.post(`/examinations/${examId}/conclusion/sign`);
    expect(sign.status(), await sign.text()).toBe(200);
    const st = (await (await doctor.get(`/examinations/${examId}/status`)).json()) as { status: string };
    expect(st.status).toBe('completed');
  });

  test('after the doctor signs, the PDF report is available to the nurse', async ({ request }) => {
    const nurse = await Api.login(request, U.nurse.username, U.nurse.password);
    const pdf = await nurse.get(`/examinations/${examId}/export/pdf`);
    expect(pdf.status()).toBe(200);
    expect(pdf.headers()['content-type']).toContain('application/pdf');
    expect((await pdf.body()).subarray(0, 4).toString()).toBe('%PDF');
  });

  test('doctor sees the examination in the UI', async ({ page }) => {
    await loginViaUi(page, U.doctor);
    await page.goto(`/exams/${examId}`);
    await expect(page).toHaveURL(new RegExp(`/exams/${examId}$`));
    await expect(page.getByText(examNo).first()).toBeVisible();
    await page.goto('/exams'); // list renders (default tab may hide completed exams)
    await expect(page.getByRole('heading').first()).toBeVisible();
  });

  test('admin sees the clinical actions in the audit trail (API + UI)', async ({ page, request }) => {
    const admin = await Api.login(request, U.admin.username, U.admin.password);
    const actions = new Set<string>();
    for (const action of ['upload', 'sign', 'status_change']) {
      const logs = await (await admin.get('/audit-logs', { action, limit: 100 })).json();
      if (logs.items.length) actions.add(action);
    }
    expect(actions.has('upload')).toBe(true);
    expect(actions.has('sign')).toBe(true);

    await loginViaUi(page, U.admin);
    await page.goto('/admin/audit');
    await expect(page.getByRole('heading', { name: 'Audit log' })).toBeVisible();
    await expect.poll(async () => page.getByRole('row').count(), { timeout: 15_000 }).toBeGreaterThan(1);
  });
});
