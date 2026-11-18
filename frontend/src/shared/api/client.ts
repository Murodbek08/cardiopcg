import axios, { AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from 'axios';
import { API_BASE } from '@/shared/lib/constants';
import { useAuthStore } from '@/shared/store/auth';
import { normalizeError } from './errors';
import type { RefreshResponse } from './types';

type RetriableConfig = InternalAxiosRequestConfig & { _retry?: boolean };

/** Endpoints that must never trigger the refresh-and-retry dance. */
const NO_REFRESH_PATHS = ['/auth/login', '/auth/refresh', '/auth/logout', '/auth/reset-password'];

function uuid(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
}

/** Bare client (no interceptors) used for the refresh call itself. */
export const rawApi: AxiosInstance = axios.create({ baseURL: API_BASE, withCredentials: true, timeout: 30_000 });

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  timeout: 30_000,
  headers: { Accept: 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  if (token) config.headers.set('Authorization', `Bearer ${token}`);
  config.headers.set('X-Request-ID', uuid());
  config.headers.set('Accept-Language', document.documentElement.lang || 'uz');
  return config;
});

// ---------- single-flight refresh ----------
let refreshing: Promise<string> | null = null;

/**
 * Exchanges the httpOnly refresh cookie for a new access token. Concurrent callers share one request
 * (single-flight), so N parallel 401s result in exactly one POST /auth/refresh.
 */
export function refreshAccessToken(): Promise<string> {
  if (!refreshing) {
    refreshing = rawApi
      .post<RefreshResponse>('/auth/refresh')
      .then((r) => {
        useAuthStore.getState().setToken(r.data.access_token);
        return r.data.access_token;
      })
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

/** Test helper: reset module state between tests. */
export function __resetRefreshState(): void {
  refreshing = null;
}

api.interceptors.response.use(undefined, async (error: unknown) => {
  if (!(error instanceof AxiosError) || !error.config) throw normalizeError(error);
  const config = error.config as RetriableConfig;
  const status = error.response?.status;
  const url = config.url ?? '';
  const skip = NO_REFRESH_PATHS.some((p) => url.includes(p));

  if (status === 401 && !config._retry && !skip) {
    config._retry = true;
    try {
      const token = await refreshAccessToken();
      config.headers.set('Authorization', `Bearer ${token}`);
      return await api(config);
    } catch (refreshErr) {
      const apiErr = normalizeError(refreshErr);
      // Only a definitive rejection of the refresh token ends the session; a network blip does not.
      if (!apiErr.isNetwork && apiErr.status !== 0 && apiErr.status < 500) {
        useAuthStore.getState().logout(apiErr.code === 'TOKEN_REUSE_DETECTED' ? 'token_reuse' : 'session_expired');
      }
      throw apiErr;
    }
  }
  throw normalizeError(error);
});

/** Convenience: typed GET returning `data`. */
export async function get<T>(url: string, params?: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
  const res = await api.get<T>(url, { params: cleanParams(params), signal, paramsSerializer: { indexes: null } });
  return res.data;
}
export async function post<T = void>(url: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
  const res = await api.post<T>(url, body, { headers });
  return res.data;
}
export async function patch<T = void>(url: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
  const res = await api.patch<T>(url, body, { headers });
  return res.data;
}
export async function put<T = void>(url: string, body?: unknown): Promise<T> {
  const res = await api.put<T>(url, body);
  return res.data;
}
export async function del<T = void>(url: string): Promise<T> {
  const res = await api.delete<T>(url);
  return res.data;
}

/** Drops undefined/null/'' so they are not serialized into the query string. */
export function cleanParams(p?: Record<string, unknown>): Record<string, unknown> | undefined {
  if (!p) return undefined;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(p)) {
    if (v === undefined || v === null || v === '') continue;
    if (Array.isArray(v) && v.length === 0) continue;
    out[k] = v;
  }
  return out;
}

/** Downloads a binary response (CSV/PDF) through the authenticated client. */
export async function downloadFile(url: string, params?: Record<string, unknown>, fallbackName = 'download'): Promise<void> {
  const res = await api.get<Blob>(url, { params: cleanParams(params), responseType: 'blob', paramsSerializer: { indexes: null } });
  const cd = String(res.headers['content-disposition'] ?? '');
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  const name = m?.[1] ? decodeURIComponent(m[1]) : fallbackName;
  const href = URL.createObjectURL(res.data);
  const a = document.createElement('a');
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 10_000);
}
