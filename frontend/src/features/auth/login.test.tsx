import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from '@tanstack/react-router';
import { server } from '@/test/mocks/server';
import { MOCK_PASSWORD } from '@/test/mocks/data';
import { useAuthStore } from '@/shared/store/auth';
import { setupZodUz } from '@/shared/lib/zod-uz';
import { LoginPage, loginErrorKey } from './pages/login-page';
import { ApiError } from '@/shared/api/errors';

beforeAll(() => {
  setupZodUz();
  server.listen({ onUnhandledFrame: 'error' });
});
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => useAuthStore.setState({ status: 'anonymous', user: null, accessToken: null, logoutReason: null }));

function renderLogin(initial = '/login') {
  const root = createRootRoute();
  const login = createRoute({ getParentRoute: () => root, path: '/login', component: LoginPage });
  const admin = createRoute({ getParentRoute: () => root, path: '/admin', component: () => <p>ADMIN HOME</p> });
  const doctor = createRoute({ getParentRoute: () => root, path: '/doctor', component: () => <p>DOCTOR HOME</p> });
  const forgot = createRoute({ getParentRoute: () => root, path: '/forgot-password', component: () => <p>forgot</p> });
  const router = createRouter({ routeTree: root.addChildren([login, admin, doctor, forgot]), history: createMemoryHistory({ initialEntries: [initial] }) });
  render(<RouterProvider router={router} />);
  return router;
}

describe('LoginPage', () => {
  it('shows a generic error for bad credentials and clears the password field', async () => {
    renderLogin();
    await userEvent.type(await screen.findByLabelText(/Foydalanuvchi nomi/), 'admin.demo');
    await userEvent.type(screen.getByLabelText(/^Parol\*?$/), 'wrong-password');
    await userEvent.click(screen.getByRole('button', { name: 'Kirish' }));
    expect(await screen.findByText("Foydalanuvchi nomi yoki parol noto'g'ri")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Parol\*?$/)).toHaveValue('');
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it('validates username format before calling the API', async () => {
    renderLogin();
    await userEvent.type(await screen.findByLabelText(/Foydalanuvchi nomi/), 'a!');
    await userEvent.type(screen.getByLabelText(/^Parol\*?$/), 'x');
    await userEvent.click(screen.getByRole('button', { name: 'Kirish' }));
    expect(await screen.findByText(/3-32 belgi/)).toBeInTheDocument();
  });

  it('signs in, keeps the token in memory only and routes admins to /admin', async () => {
    const router = renderLogin();
    await userEvent.type(await screen.findByLabelText(/Foydalanuvchi nomi/), 'admin.demo');
    await userEvent.type(screen.getByLabelText(/^Parol\*?$/), MOCK_PASSWORD);
    await userEvent.click(screen.getByRole('button', { name: 'Kirish' }));
    expect(await screen.findByText('ADMIN HOME')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/admin');
    expect(useAuthStore.getState().user?.role).toBe('admin');
    expect(useAuthStore.getState().accessToken).toBeTruthy();
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain(useAuthStore.getState().accessToken!);
  });

  it('honours a safe ?next target but ignores an external one', async () => {
    const router = renderLogin('/login?next=%2Fdoctor');
    await userEvent.type(await screen.findByLabelText(/Foydalanuvchi nomi/), 'doctor.demo');
    await userEvent.type(screen.getByLabelText(/^Parol\*?$/), MOCK_PASSWORD);
    await userEvent.click(screen.getByRole('button', { name: 'Kirish' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/doctor'));
  });
});

describe('loginErrorKey', () => {
  const mk = (status: number, code: string, details?: Record<string, unknown>) => new ApiError({ status, code, message: code, details });
  it('maps lockout, suspension, rate limit and network without leaking which field was wrong', () => {
    expect(loginErrorKey(mk(401, 'INVALID_CREDENTIALS')).key).toBe('login.errors.invalid');
    expect(loginErrorKey(mk(423, 'ACCOUNT_LOCKED', { locked_until: new Date(Date.now() + 5 * 60_000).toISOString() }))).toMatchObject({ key: 'login.errors.locked', opts: { minutes: 5 } });
    expect(loginErrorKey(mk(423, 'ACCOUNT_LOCKED')).key).toBe('login.errors.locked_generic');
    expect(loginErrorKey(mk(403, 'ACCOUNT_SUSPENDED')).key).toBe('login.errors.suspended');
    expect(loginErrorKey(mk(429, 'RATE_LIMITED')).key).toBe('login.errors.rate_limited');
    expect(loginErrorKey(new ApiError({ status: 0, code: 'NETWORK_ERROR', message: 'x', isNetwork: true })).key).toBe('login.errors.network');
  });
});
