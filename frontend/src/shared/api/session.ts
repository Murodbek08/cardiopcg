import { api, post, get, refreshAccessToken, rawApi } from './client';
import { useAuthStore } from '@/shared/store/auth';
import type { LoginResponse, Me, SessionUser } from './types';
import { normalizeError } from './errors';

/** Decode the `exp` claim (seconds) without verifying: only used to schedule a proactive refresh. */
export function jwtExpiry(token: string): number | null {
  try {
    const part = token.split('.')[1];
    if (!part) return null;
    const json = atob(part.replace(/-/g, '+').replace(/_/g, '/'));
    const exp = (JSON.parse(json) as { exp?: number }).exp;
    return typeof exp === 'number' ? exp : null;
  } catch {
    return null;
  }
}

let timer: ReturnType<typeof setTimeout> | null = null;
let channel: BroadcastChannel | null = null;
let started = false;

type ChannelMsg = { type: 'logout' } | { type: 'token'; token: string };

function post_(msg: ChannelMsg) {
  try {
    channel?.postMessage(msg);
  } catch {
    /* ignore */
  }
}

function schedule(token: string | null) {
  if (timer) clearTimeout(timer);
  timer = null;
  if (!token) return;
  const exp = jwtExpiry(token);
  if (!exp) return;
  // refresh when 60 s remain (never sooner than 5 s from now)
  const delay = Math.max(exp * 1000 - Date.now() - 60_000, 5_000);
  timer = setTimeout(() => {
    refreshAccessToken().catch(() => {
      /* the 401 interceptor / next request surfaces a dead session */
    });
  }, delay);
}

/** Wire proactive refresh + cross-tab sync. Idempotent. */
export function initSession(): void {
  if (started) return;
  started = true;
  let lastToken = useAuthStore.getState().accessToken;
  let lastStatus = useAuthStore.getState().status;
  useAuthStore.subscribe((s) => {
    if (s.accessToken !== lastToken) {
      lastToken = s.accessToken;
      schedule(s.accessToken);
      if (s.accessToken) post_({ type: 'token', token: s.accessToken });
    }
    if (s.status !== lastStatus) {
      if (s.status === 'anonymous' && lastStatus === 'authenticated' && s.logoutReason !== null) post_({ type: 'logout' });
      lastStatus = s.status;
    }
  });
  if (typeof BroadcastChannel !== 'undefined') {
    channel = new BroadcastChannel('cardiopcg-auth');
    channel.onmessage = (ev: MessageEvent<ChannelMsg>) => {
      const m = ev.data;
      if (m.type === 'logout') {
        // Do not re-broadcast: set state directly
        useAuthStore.setState({ status: 'anonymous', user: null, accessToken: null, logoutReason: 'logout' });
      } else if (m.type === 'token' && useAuthStore.getState().status === 'authenticated') {
        lastToken = m.token;
        useAuthStore.getState().setToken(m.token);
        schedule(m.token);
      }
    };
  }
}

/** On page load: restore the session from the refresh cookie (access token is memory-only). */
export async function bootstrapSession(): Promise<void> {
  const store = useAuthStore.getState();
  if (store.status !== 'unknown') return;
  try {
    const token = await refreshAccessToken();
    const me = await get<Me>('/auth/me');
    useAuthStore.getState().setSession(toSessionUser(me), token);
  } catch (e) {
    const err = normalizeError(e);
    if (err.status === 401 || err.status === 403 || err.isNetwork || err.status === 0 || err.status >= 400) {
      useAuthStore.getState().setAnonymous();
    }
  }
}

export function toSessionUser(me: Me | SessionUser): SessionUser {
  return {
    id: me.id,
    username: me.username,
    full_name: me.full_name,
    role: me.role,
    locale: me.locale,
    must_change_password: me.must_change_password,
  };
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const res = await rawApi.post<LoginResponse>('/auth/login', { username, password }).catch((e) => {
    throw normalizeError(e);
  });
  useAuthStore.getState().setSession(res.data.user, res.data.access_token);
  return res.data;
}

export async function logout(reason: 'logout' | 'idle' = 'logout'): Promise<void> {
  try {
    await post('/auth/logout');
  } catch {
    /* server-side revoke best effort */
  }
  useAuthStore.getState().logout(reason);
  post_({ type: 'logout' });
}

export async function changePassword(current_password: string, new_password: string): Promise<void> {
  await api.post('/auth/change-password', { current_password, new_password }).catch((e) => {
    throw normalizeError(e);
  });
}
