import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { api, __resetRefreshState } from './client';
import { ApiError } from './errors';
import { useAuthStore } from '@/shared/store/auth';

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

beforeEach(() => {
  __resetRefreshState();
  useAuthStore.setState({
    status: 'authenticated',
    accessToken: 'old',
    logoutReason: null,
    user: { id: 'u', username: 'x', full_name: 'X', role: 'doctor', locale: 'uz', must_change_password: false },
  });
});

function protectedHandlers(refresh: () => Response) {
  let refreshCalls = 0;
  server.use(
    http.get('*/api/v1/things', ({ request }) =>
      request.headers.get('authorization') === 'Bearer new'
        ? HttpResponse.json({ ok: true })
        : HttpResponse.json({ error: { code: 'TOKEN_EXPIRED', message: 'exp' } }, { status: 401 }),
    ),
    http.post('*/api/v1/auth/refresh', () => {
      refreshCalls++;
      return refresh();
    }),
  );
  return () => refreshCalls;
}

describe('api client: single-flight token refresh', () => {
  it('N parallel 401s trigger exactly ONE refresh and every request is retried with the new token', async () => {
    const calls = protectedHandlers(() => HttpResponse.json({ access_token: 'new', token_type: 'bearer', expires_in: 900 }));
    const results = await Promise.all(Array.from({ length: 6 }, () => api.get('/things')));
    expect(results.every((r) => r.data.ok === true)).toBe(true);
    expect(calls()).toBe(1);
    expect(useAuthStore.getState().accessToken).toBe('new');
  });

  it('refresh rejected -> session ends (session_expired) and the error is a normalized ApiError', async () => {
    protectedHandlers(() => HttpResponse.json({ error: { code: 'REFRESH_INVALID', message: 'no' } }, { status: 401 }));
    await expect(api.get('/things')).rejects.toBeInstanceOf(ApiError);
    expect(useAuthStore.getState().status).toBe('anonymous');
    expect(useAuthStore.getState().logoutReason).toBe('session_expired');
  });

  it('token reuse detected -> logoutReason token_reuse', async () => {
    protectedHandlers(() => HttpResponse.json({ error: { code: 'TOKEN_REUSE_DETECTED', message: 'reuse' } }, { status: 401 }));
    await expect(api.get('/things')).rejects.toBeInstanceOf(ApiError);
    expect(useAuthStore.getState().logoutReason).toBe('token_reuse');
  });

  it('a network failure during refresh does NOT log the user out', async () => {
    protectedHandlers(() => HttpResponse.error());
    await expect(api.get('/things')).rejects.toBeInstanceOf(ApiError);
    expect(useAuthStore.getState().status).toBe('authenticated');
  });

  it('never retries login (401 there is a credentials error, not an expired token)', async () => {
    let refreshed = 0;
    server.use(
      http.post('*/api/v1/auth/login', () => HttpResponse.json({ error: { code: 'INVALID_CREDENTIALS', message: 'bad' } }, { status: 401 })),
      http.post('*/api/v1/auth/refresh', () => {
        refreshed++;
        return HttpResponse.json({});
      }),
    );
    await expect(api.post('/auth/login', {})).rejects.toMatchObject({ code: 'INVALID_CREDENTIALS', status: 401 });
    expect(refreshed).toBe(0);
  });

  it('sends the bearer token and a request id on every request', async () => {
    let auth = '';
    let rid = '';
    server.use(
      http.get('*/api/v1/echo', ({ request }) => {
        auth = request.headers.get('authorization') ?? '';
        rid = request.headers.get('x-request-id') ?? '';
        return HttpResponse.json({});
      }),
    );
    await api.get('/echo');
    expect(auth).toBe('Bearer old');
    expect(rid.length).toBeGreaterThan(8);
  });
});

describe('access token is memory-only', () => {
  it('never writes tokens to localStorage / sessionStorage', () => {
    useAuthStore.getState().setSession(
      { id: 'u', username: 'x', full_name: 'X', role: 'admin', locale: 'uz', must_change_password: false },
      'secret-token-value',
    );
    const dump = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage });
    expect(dump).not.toContain('secret-token-value');
  });
});
