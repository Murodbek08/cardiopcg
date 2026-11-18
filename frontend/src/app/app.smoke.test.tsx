import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import { server } from '@/test/mocks/server';
import i18n from '@/i18n';
import { useAuthStore } from '@/shared/store/auth';
import { setupZodUz } from '@/shared/lib/zod-uz';
import { AppProviders, queryClient } from './providers/app-providers';
import { AppRouter, router } from './router';
import type { Role } from '@/shared/api/types';

// canvas/ECharts and wavesurfer need a real browser; the routing/data/i18n path is what this test covers.
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
    // recharts measures 0x0 in jsdom; React act() noise is not an app bug
    if (!/width\(0\)|height\(0\)|not wrapped in act|ResponsiveContainer/.test(msg)) consoleErrors.push(msg.slice(0, 300));
  });
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

export function signIn(role: Role, id = 'u-admin') {
  useAuthStore.setState({
    status: 'authenticated',
    accessToken: `tok-${role}`,
    logoutReason: null,
    user: { id, username: `${role}.demo`, full_name: `${role} Demo`, role, locale: 'uz', must_change_password: false },
  });
}

beforeEach(() => {
  queryClient.clear();
});

async function go(path: string) {
  await router.navigate({ to: path as never });
}

describe('admin app smoke (router + guards + data + i18n)', () => {
  it('renders every admin page with mocked API data and no missing translations', async () => {
    signIn('admin');
    render(
      <AppProviders>
        <AppRouter />
      </AppProviders>,
    );

    const pages: [string, RegExp | string][] = [
      ['/admin', 'Jami tekshiruv'],
      ['/admin/users', 'admin.demo'],
      ['/admin/users/new', 'Yangi foydalanuvchi'],
      ['/admin/users/u-doc', 'Karimov Aziz'],
      ['/admin/audit', 'Audit log'],
      ['/admin/settings', 'analysis.auto_start'],
      ['/admin/drugs', 'Metoprolol'],
      ['/admin/drugs/d-1', 'Dozalar'],
      ['/admin/reports', 'Hisobotlar va eksport'],
      ['/patients', /R\*\*\* /],
      ['/exams', 'E-20261118-0001'],
      ['/notifications', 'Kritik topilma: E-20261118-0003'],
      ['/profile', 'Sessiyalar'],
    ];
    for (const [path, expected] of pages) {
      if (false as boolean) {
        await go(path);
        await screen.findByText('Yangi dori', {}, { timeout: 8000 });
        continue;
      }
      await go(path);
      const found = await screen.findAllByText(expected, {}, { timeout: 8000 }).catch(() => null);
      expect(found, `page ${path} should show ${String(expected)}`).not.toBeNull();
    }
    expect([...missing].sort()).toEqual([]);
    expect(consoleErrors).toEqual([]);
  }, 120_000);

  it('patient names are masked for admin (no raw identity leaks into the list)', async () => {
    signIn('admin');
    render(<AppProviders><AppRouter /></AppProviders>);
    await go('/patients');
    await screen.findAllByText(/R\*\*\* A\*\*\*|K\*\*\* /, {}, { timeout: 8000 });
    expect(screen.queryByText(/Rahimov Aziz/)).toBeNull();
  }, 30_000);

  it('admin dashboard shows KPI values and chart cards load independently', async () => {
    signIn('admin');
    render(<AppProviders><AppRouter /></AppProviders>);
    await go('/admin');
    const kpis = await screen.findByRole('region', { name: 'KPI' }, { timeout: 8000 });
    await waitFor(() => expect(within(kpis).getByText('356')).toBeInTheDocument(), { timeout: 8000 });
    expect(await screen.findByText('Tekshiruvlar vaqt qatori')).toBeInTheDocument();
  });
});

describe('RBAC route guards', () => {
  it('doctor cannot open /admin or /admin/users (redirected to /403)', async () => {
    signIn('doctor', 'u-doc');
    render(<AppProviders><AppRouter /></AppProviders>);
    await go('/admin');
    await screen.findByText('Ruxsat yo\'q');
    expect(router.state.location.pathname).toBe('/403');
    await go('/admin/users');
    await waitFor(() => expect(router.state.location.pathname).toBe('/403'));
  });

  it('nurse cannot open /admin and sees the tablet bottom navigation on the nurse home', async () => {
    signIn('nurse', 'u-nurse');
    render(<AppProviders><AppRouter /></AppProviders>);
    await go('/admin/audit');
    await waitFor(() => expect(router.state.location.pathname).toBe('/403'));
    await go('/nurse');
    await screen.findAllByText('Bosh sahifa', {}, { timeout: 8000 });
  }, 30_000);

  it('anonymous users are redirected to /login with ?next', async () => {
    useAuthStore.setState({ status: 'anonymous', user: null, accessToken: null, logoutReason: null });
    render(<AppProviders><AppRouter /></AppProviders>);
    await go('/admin/users');
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));
    expect(router.state.location.search).toMatchObject({ next: expect.stringContaining('/admin/users') });
  });

  it('must_change_password forces /change-password for every route', async () => {
    useAuthStore.setState({
      status: 'authenticated', accessToken: 'tok', logoutReason: null,
      user: { id: 'u-admin', username: 'admin.demo', full_name: 'A', role: 'admin', locale: 'uz', must_change_password: true },
    });
    render(<AppProviders><AppRouter /></AppProviders>);
    await go('/admin');
    await waitFor(() => expect(router.state.location.pathname).toBe('/change-password'));
  });
});
