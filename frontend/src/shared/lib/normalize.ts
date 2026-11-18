import type { Paged } from '@/shared/api/types';

export interface NormalizedPage<T> {
  items: T[];
  total: number | null;
  nextCursor: string | null;
}

/** Accepts the cursor envelope (`page.next_cursor/total`), the offset envelope or a bare array. */
export function normalizePage<T>(raw: Paged<T> | T[] | null | undefined): NormalizedPage<T> {
  if (!raw) return { items: [], total: 0, nextCursor: null };
  if (Array.isArray(raw)) return { items: raw, total: raw.length, nextCursor: null };
  const total = raw.page?.total ?? raw.total ?? null;
  return { items: raw.items ?? [], total, nextCursor: raw.page?.next_cursor ?? null };
}
