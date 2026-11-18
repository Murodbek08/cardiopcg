import { fetchEventSource } from '@microsoft/fetch-event-source';
import { API_BASE } from '@/shared/lib/constants';
import { useAuthStore } from '@/shared/store/auth';
import { refreshAccessToken } from './client';

/** Envelope used by both WS and SSE (doc 01, section 6). */
export interface RealtimeEvent<T = Record<string, unknown>> {
  v: number;
  id: string;
  type: string;
  ts: string;
  data: T;
}

export interface SseOptions {
  /** Path relative to API base, e.g. `/examinations/{id}/events`. */
  path: string;
  onEvent: (ev: RealtimeEvent) => void;
  onOpen?: () => void;
  /** Called when we give up on SSE (caller should fall back to polling). */
  onFallback?: () => void;
  maxRetries?: number;
}

class FatalSseError extends Error {}

/** Exponential backoff schedule: 1, 2, 4, 8 ... capped at 30 s. */
export function backoffMs(attempt: number): number {
  return Math.min(1000 * 2 ** attempt, 30_000);
}

/**
 * fetch-based SSE (EventSource cannot send Authorization). Resumes with Last-Event-ID, reconnects with
 * exponential backoff, refreshes the access token on 401, and falls back to polling after `maxRetries`.
 * Returns a disposer.
 */
export function connectSse(opts: SseOptions): () => void {
  const ctrl = new AbortController();
  let attempt = 0;
  const max = opts.maxRetries ?? 6;
  let lastEventId = '';

  void fetchEventSource(`${API_BASE}${opts.path}`, {
    signal: ctrl.signal,
    credentials: 'include',
    openWhenHidden: true,
    headers: {
      Accept: 'text/event-stream',
      ...(useAuthStore.getState().accessToken ? { Authorization: `Bearer ${useAuthStore.getState().accessToken}` } : {}),
    },
    async onopen(res) {
      if (res.ok && res.headers.get('content-type')?.includes('text/event-stream')) {
        attempt = 0;
        opts.onOpen?.();
        return;
      }
      if (res.status === 401) {
        await refreshAccessToken();
        throw new Error('retry-after-refresh');
      }
      if (res.status >= 400 && res.status < 500 && res.status !== 429) throw new FatalSseError(`SSE ${res.status}`);
      throw new Error(`SSE ${res.status}`);
    },
    onmessage(msg) {
      if (msg.id) lastEventId = msg.id;
      if (!msg.data) return;
      try {
        const parsed = JSON.parse(msg.data) as RealtimeEvent;
        opts.onEvent({ ...parsed, type: parsed.type ?? msg.event });
      } catch {
        /* ignore malformed frame */
      }
    },
    onerror(err) {
      if (err instanceof FatalSseError || attempt >= max) {
        opts.onFallback?.();
        throw err; // stops the retry loop
      }
      const wait = backoffMs(attempt++);
      void lastEventId;
      return wait; // fetch-event-source retries after this many ms
    },
  }).catch(() => {
    /* aborted or fatal: fallback already signalled */
  });

  return () => ctrl.abort();
}
