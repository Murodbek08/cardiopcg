import { useAuthStore } from '@/shared/store/auth';
import { API_BASE } from '@/shared/lib/constants';
import { backoffMs, type RealtimeEvent } from './sse';

type Listener = (ev: RealtimeEvent) => void;

/**
 * Global WebSocket channel (`/api/v1/ws?token=`). Auto-subscribes server side to user:{me} / role:{role}.
 * Reconnects with exponential backoff; sends a fresh token when the access token rotates.
 */
export class RealtimeClient {
  private ws: WebSocket | null = null;
  private attempt = 0;
  private closed = false;
  private listeners = new Set<Listener>();
  private statusListeners = new Set<(online: boolean) => void>();
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private unsubscribeStore: (() => void) | null = null;

  on(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }
  onStatus(fn: (online: boolean) => void): () => void {
    this.statusListeners.add(fn);
    return () => this.statusListeners.delete(fn);
  }

  start(): void {
    this.closed = false;
    this.connect();
    let last = useAuthStore.getState().accessToken;
    this.unsubscribeStore = useAuthStore.subscribe((s) => {
      if (s.accessToken && s.accessToken !== last && this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'auth', token: s.accessToken }));
      }
      last = s.accessToken;
    });
  }

  subscribe(channel: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: 'subscribe', channels: [channel] }));
  }

  stop(): void {
    this.closed = true;
    this.unsubscribeStore?.();
    if (this.retryTimer) clearTimeout(this.retryTimer);
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.ws?.close(1000);
    this.ws = null;
  }

  private emitStatus(online: boolean) {
    this.statusListeners.forEach((l) => l(online));
  }

  private connect(): void {
    const token = useAuthStore.getState().accessToken;
    if (!token || this.closed) return;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}${API_BASE}/ws?token=${encodeURIComponent(token)}`);
    this.ws = ws;
    ws.onopen = () => {
      this.attempt = 0;
      this.emitStatus(true);
      this.pingTimer = setInterval(() => ws.readyState === WebSocket.OPEN && ws.send('{"type":"ping"}'), 25_000);
    };
    ws.onmessage = (m) => {
      try {
        const ev = JSON.parse(String(m.data)) as RealtimeEvent;
        if (ev.type === 'pong') return;
        this.listeners.forEach((l) => l(ev));
      } catch {
        /* ignore */
      }
    };
    ws.onclose = (ev) => {
      if (this.pingTimer) clearInterval(this.pingTimer);
      this.emitStatus(false);
      if (this.closed) return;
      // 4401/4403/4429: do not hammer the server
      if (ev.code === 4401 || ev.code === 4403) return;
      this.retryTimer = setTimeout(() => this.connect(), backoffMs(this.attempt++));
    };
    ws.onerror = () => ws.close();
  }
}

export const realtime = new RealtimeClient();
