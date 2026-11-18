import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearch } from '@tanstack/react-router';
import type { z } from 'zod';

/**
 * URL-backed state (filters, page, tab, period). Parsed with a zod schema that supplies defaults via
 * `.catch()`, so malformed query strings never crash a page. Updates replace history entries.
 */
export function useUrlState<S extends z.ZodType<Record<string, unknown>>>(schema: S) {
  const raw = useSearch({ strict: false }) as Record<string, unknown>;
  const navigate = useNavigate();
  const state = useMemo(() => schema.parse(raw) as z.output<S>, [schema, raw]);
  const set = useCallback(
    (patch: Partial<z.output<S>>, opts?: { resetPage?: boolean }) => {
      void navigate({
        to: '.',
        replace: true,
        search: ((prev: Record<string, unknown>) => {
          const next: Record<string, unknown> = { ...prev, ...patch };
          if (opts?.resetPage) delete next.page;
          for (const k of Object.keys(next)) {
            if (next[k] === undefined || next[k] === '' || next[k] === null) delete next[k];
          }
          return next;
        }) as never,
      });
    },
    [navigate],
  );
  return [state, set] as const;
}

/**
 * Text search box bound to a URL param: typing is debounced (300 ms) before the URL/query changes, and
 * external URL changes (back button, clear filters) flow back into the input.
 */
export function useSearchInput(urlValue: string | undefined, onCommit: (v: string | undefined) => void, delay = 300) {
  const [input, setInput] = useState(urlValue ?? '');
  const [debounced, setDebounced] = useState(input);
  const commit = useRef(onCommit);
  useEffect(() => {
    commit.current = onCommit;
  });
  const first = useRef(true);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(input), delay);
    return () => clearTimeout(id);
  }, [input, delay]);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    if (debounced !== (urlValue ?? '')) commit.current(debounced || undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);
  useEffect(() => {
    setInput(urlValue ?? '');
    setDebounced(urlValue ?? '');
  }, [urlValue]);
  return [input, setInput] as const;
}
