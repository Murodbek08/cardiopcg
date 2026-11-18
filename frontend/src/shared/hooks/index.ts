import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { api } from '@/shared/api/client';
import { useAuthStore } from '@/shared/store/auth';
import { can, type Permission } from '@/shared/lib/permissions';

export function useDebounce<T>(value: T, delay = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return v;
}

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(query);
      m.addEventListener('change', cb);
      return () => m.removeEventListener('change', cb);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

export function useOnline(): boolean {
  return useSyncExternalStore(
    (cb) => {
      window.addEventListener('online', cb);
      window.addEventListener('offline', cb);
      return () => {
        window.removeEventListener('online', cb);
        window.removeEventListener('offline', cb);
      };
    },
    () => navigator.onLine,
    () => true,
  );
}

/** UI-level permission check. Server is still authoritative; hidden controls are never rendered. */
export function usePermission(permission: Permission): boolean {
  const role = useAuthStore((s) => s.user?.role ?? null);
  return can(role, permission);
}

/**
 * Fetches a protected binary (audio / spectrogram PNG) through the authenticated client and returns an
 * object URL. Tokens never appear in URLs.
 */
export function useAuthedBlobUrl(path: string | null | undefined): { url: string | null; loading: boolean; error: unknown } {
  const [state, setState] = useState<{ url: string | null; loading: boolean; error: unknown }>({ url: null, loading: !!path, error: null });
  const last = useRef<string | null>(null);
  useEffect(() => {
    if (!path) {
      setState({ url: null, loading: false, error: null });
      return;
    }
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    api
      .get<Blob>(path.replace(/^\/api\/v1/, ''), { responseType: 'blob' })
      .then((r) => {
        if (cancelled) return;
        if (last.current) URL.revokeObjectURL(last.current);
        last.current = URL.createObjectURL(r.data);
        setState({ url: last.current, loading: false, error: null });
      })
      .catch((error) => !cancelled && setState({ url: null, loading: false, error }));
    return () => {
      cancelled = true;
    };
  }, [path]);
  useEffect(
    () => () => {
      if (last.current) URL.revokeObjectURL(last.current);
    },
    [],
  );
  return state;
}
