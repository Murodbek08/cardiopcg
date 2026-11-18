import { QueryClient } from '@tanstack/react-query';
import { ApiError } from './errors';

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 10 * 60_000,
        refetchOnWindowFocus: true,
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
          return failureCount < 1;
        },
      },
      mutations: { retry: false },
    },
  });
}

/** Query key factory. Keep keys centralised so invalidation is explicit. */
export const qk = {
  me: ['me'] as const,
  users: {
    all: ['users'] as const,
    list: (f: unknown) => ['users', 'list', f] as const,
    detail: (id: string) => ['users', 'detail', id] as const,
  },
  patients: {
    all: ['patients'] as const,
    list: (f: unknown) => ['patients', 'list', f] as const,
    detail: (id: string) => ['patients', 'detail', id] as const,
    timeline: (id: string) => ['patients', 'timeline', id] as const,
  },
  exams: {
    all: ['exams'] as const,
    list: (f: unknown) => ['exams', 'list', f] as const,
    detail: (id: string) => ['exams', 'detail', id] as const,
    segments: (id: string) => ['exams', 'segments', id] as const,
  },
  audit: { list: (f: unknown) => ['audit', 'list', f] as const, recent: ['audit', 'recent'] as const },
  settings: ['settings'] as const,
  health: ['health', 'deep'] as const,
  drugs: {
    all: ['drugs'] as const,
    list: (f: unknown) => ['drugs', 'list', f] as const,
    detail: (id: string) => ['drugs', 'detail', id] as const,
  },
  analytics: {
    admin: (name: string, p: unknown) => ['analytics', 'admin', name, p] as const,
  },
  notifications: {
    list: (f: unknown) => ['notifications', 'list', f] as const,
    unread: ['notifications', 'unread'] as const,
  },
  exports: (id: string) => ['exports', id] as const,
};
