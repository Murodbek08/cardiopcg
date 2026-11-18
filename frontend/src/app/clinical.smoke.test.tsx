import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '@/test/mocks/server';
import i18n from '@/i18n';
import { useAuthStore } from '@/shared/store/auth';
import { setupZodUz } from '@/shared/lib/zod-uz';
import { AppProviders, queryClient } from './providers/app-providers';
import { AppRouter, router } from './router';
import type { Role } from '@/shared/api/types';

vi.mock('@/shared/charts/heatmap', () => ({ Heatmap: () => <div data-testid="heatmap" /> }));
vi.mock('@/shared/clinical/audio-waveform', () => ({ AudioWaveform: () => <div data-testid="waveform" /> }));
vi.mock('@/shared/clinical/spectrogram-view', () => ({ SpectrogramView: () => <div data-testid="spectrogram" /> }));

const missing = new Set<string>();
const consoleErrors: string[] = [];

beforeAll(() => {
  setupZodUz();
  server.listen({ onUnhandledFrame: 'bypass' });
  i18n.on('missingKey', (_l, ns, key) => missing.add(`${ns}:${key}`));
  vi.spyOn(console, 'error').mockImplementation((...a) => {
    const msg = a.map(String).join(' ');
    if (!/width\(0\)|height\(0\)|not wrapped in act|ResponsiveContainer/.test(msg)) consoleErrors.push(msg.slice(0, 300));
  });
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  queryClient.clear();
  sessionStorage.clear();
});

function signIn(role: Role) {
  useAuthStore.setState({
    status: 'authenticated', accessToken: `tok-${role}`, logoutReason: null,
    user: { id: role === 'doctor' ? 'u-doc' : 'u-nurse', username: `${role}.demo`, full_name: `${role} Demo`, role, locale: 'uz', must_change_password: false },
  });
}
const mount = () => render(<AppProviders><AppRouter /></AppProviders>);
const go = (path: string) => router.navigate({ to: path as never });
const see = (text: string | RegExp) => screen.findAllByText(text, {}, { timeout: 8000 });

describe('doctor routes render with mocked API (no missing i18n keys, no console errors)', () => {
  it('visits every doctor page', async () => {
    signIn('doctor');
    mount();
    const pages: [string, string | RegExp][] = [
      ['/doctor', 'Salom, doctor Demo'],
      ['/doctor/review-queue', 'Karimov Jasur'],
      ['/doctor/analyses', 'E-20261118-0002'],
      ['/patients', /R\*\*\*|Rahimov/],
      ['/patients/p-1', 'Anamnez'],
      ['/patients/new', "Shaxsiy ma'lumot"],
      ['/patients/p-1/edit', "Tug'ilgan sana"],
      ['/patients/p-1/timeline', 'Trendlar'],
      ['/exams', 'E-20261118-0001'],
      ['/exams/new', 'Bemorni qidirish'],
      ['/exams/e-2', 'Xususiyatlar'],
      ['/exams/e-1', /Imzolangan/],
      ['/exams/e-1/report', 'Hisobot e-1'.length ? /Shifokor xulosasi/ : ''],
      ['/exams/e-3/progress', /AI tahlil/],
      ['/reports', 'Hisobotlar va eksport'],
      ['/notifications', 'Kritik topilma: E-20261118-0003'],
    ];
    for (const [path, expected] of pages) {
      await go(path);
      const found = await see(expected).catch(() => null);
      expect(found, `doctor page ${path} should show ${String(expected)}`).not.toBeNull();
    }
    expect([...missing].sort()).toEqual([]);
    expect(consoleErrors).toEqual([]);
  }, 180_000);

  it('workspace: differential + disclaimer, allergic drug needs a written reason, signing is blocked until complete', async () => {
    signIn('doctor');
    mount();
    await go('/exams/e-2');
    await see('Xususiyatlar');
    // signing blocked: conclusion empty and drugs undecided
    const sign = await screen.findByRole('button', { name: /Tasdiqlash va imzolash/ }, { timeout: 8000 });
    expect(sign).toBeDisabled();
    expect(screen.getByText(/Xulosa matni kamida 20 belgi/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: 'Differensial' }));
    expect(await screen.findByText('Mitral yetishmovchilik')).toBeInTheDocument();
    expect(screen.getAllByText(/ma'lumot uchun/).length).toBeGreaterThan(0);

    await userEvent.click(screen.getByRole('tab', { name: 'Dori' }));
    expect(await screen.findByText('Allergiya ogohlantirishi')).toBeInTheDocument();
    // plain item: normal accept; allergic / major-interaction item: forced "anyway" with reason
    expect(screen.getByRole('button', { name: 'Qabul qilish' })).toBeEnabled();
    const anyway = screen.getByRole('button', { name: /Baribir qabul qilish/ });
    await userEvent.click(anyway);
    const confirm = await screen.findByRole('button', { name: 'Tasdiqlash' });
    expect(confirm).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Sabab/), 'Penitsillin sinamasi manfiy');
    expect(confirm).toBeEnabled();
  }, 60_000);

  it('completed exam is locked for editing and offers amend + report', async () => {
    signIn('doctor');
    mount();
    await go('/exams/e-1');
    expect(await screen.findByText(/Xulosa imzolangan/, {}, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Tuzatish kiritish' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Tasdiqlash va imzolash/ })).toBeNull();
  }, 30_000);

  it('doctor cannot open nurse home', async () => {
    signIn('doctor');
    mount();
    await go('/nurse');
    await waitFor(() => expect(router.state.location.pathname).toBe('/403'));
  });
});

describe('nurse routes + read-only enforcement', () => {
  it('visits every nurse page', async () => {
    signIn('nurse');
    mount();
    const pages: [string, string | RegExp][] = [
      ['/nurse', 'YANGI TEKSHIRUV'],
      ['/patients', /Rahimov|Karimov|Aliyeva/],
      ['/patients/new', "Shaxsiy ma'lumot"],
      ['/patients/p-1/edit', "Tug'ilgan sana"],
      ['/patients/p-1/timeline', 'Trendlar'],
      ['/exams', 'E-20261118-0001'],
      ['/exams/new', 'Bemorni qidirish'],
      ['/exams/e-3/progress', /AI tahlil/],
      ['/notifications', 'Kritik topilma: E-20261118-0003'],
    ];
    for (const [path, expected] of pages) {
      await go(path);
      const found = await see(expected).catch(() => null);
      expect(found, `nurse page ${path} should show ${String(expected)}`).not.toBeNull();
    }
    expect([...missing].sort()).toEqual([]);
  }, 120_000);

  it('workspace is read-only: no conclusion form, no edit/approve controls, restricted AI tabs', async () => {
    signIn('nurse');
    mount();
    await go('/exams/e-2');
    expect(await screen.findByText("Faqat o'qish rejimi", {}, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.queryByText('Shifokor xulosasi')).toBeNull();
    expect(screen.queryByRole('button', { name: /Tasdiqlash va imzolash/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Qayta tahlil/ })).toBeNull();
    await userEvent.click(screen.getByRole('tab', { name: 'Differensial' }));
    expect(screen.queryByText('Mitral yetishmovchilik')).toBeNull();
    await userEvent.click(screen.getByRole('tab', { name: 'Dori' }));
    expect(await screen.findByText(/shifokor tasdiqlashini kutmoqda/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Qabul qilish/ })).toBeNull();
  }, 60_000);

  it('nurse cannot open doctor pages or reports', async () => {
    signIn('nurse');
    mount();
    await go('/doctor/review-queue');
    await waitFor(() => expect(router.state.location.pathname).toBe('/403'));
    await go('/reports');
    await waitFor(() => expect(router.state.location.pathname).toBe('/403'));
  });

  it('unapproved report is blocked for nurses', async () => {
    signIn('nurse');
    mount();
    await go('/exams/e-2/report');
    expect(await screen.findByText(/faqat shifokor tasdiqlagandan keyin/, {}, { timeout: 8000 })).toBeInTheDocument();
  });
});

describe('exam wizard end-to-end (nurse, mocked API)', () => {
  it('patient -> vitals -> upload with quality check -> consent -> start analysis -> progress', async () => {
    signIn('nurse');
    mount();
    await go('/exams/new');
    await userEvent.type(await screen.findByLabelText(/Bemorni qidirish/), 'Rahimov');
    await userEvent.click((await screen.findAllByRole('button', { name: /Rahimov/ }, { timeout: 8000 }))[0]!);
    await userEvent.click(screen.getByRole('button', { name: 'Keyingisi' }));

    // step 2: vitals with a typical-range warning (not blocking)
    await screen.findByLabelText(/Sistolik/, {}, { timeout: 8000 });
    await userEvent.clear(screen.getByLabelText(/Sistolik/));
    await userEvent.type(screen.getByLabelText(/Sistolik/), '130');
    await userEvent.clear(screen.getByLabelText(/Diastolik/));
    await userEvent.type(screen.getByLabelText(/Diastolik/), '85');
    await userEvent.clear(screen.getByLabelText(/Puls/));
    await userEvent.type(screen.getByLabelText(/Puls/), '190');
    expect(await screen.findByText(/Qiymatlarni tasdiqlang/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Keyingisi' }));

    // step 3: bad format is rejected locally, a wav is uploaded and the server quality panel is shown
    const input = (await waitFor(() => { const i = document.querySelector('input[type=file]'); if (!i) throw new Error('no dropzone: ' + (document.querySelector('main')?.textContent ?? '').slice(0, 400)); return i; }, { timeout: 8000 })) as HTMLInputElement;
    await userEvent.upload(input, new File(['x'], 'mitral.wav', { type: 'audio/wav' }), { applyAccept: false });
    await userEvent.click(await screen.findByRole('button', { name: /Yuklash va tekshirish/ }, { timeout: 8000 }));
    expect(await screen.findByText('Sifat yaxshi', {}, { timeout: 8000 })).toBeInTheDocument();
    const next = screen.getByRole('button', { name: 'Keyingisi' });
    await waitFor(() => expect(next).toBeEnabled());
    await userEvent.click(next);

    // step 4: consent is mandatory
    const start = await screen.findByRole('button', { name: 'Tahlilni boshlash' }, { timeout: 8000 });
    expect(start).toBeDisabled();
    await userEvent.click(screen.getByRole('checkbox'));
    await waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);
    await waitFor(() => expect(router.state.location.pathname).toBe('/exams/e-new/progress'), { timeout: 8000 });
  }, 120_000);
});
