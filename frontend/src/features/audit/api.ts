import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { get, qk } from '@/shared';
import type { AuditLogItem, Paged } from '@/shared/api/types';

export interface AuditFilter {
  from?: string;
  to?: string;
  action?: string;
  success?: 'true' | 'false';
  resource_type?: string;
  q?: string;
  cursor?: string;
  limit: number;
}

export const AUDIT_ACTIONS = [
  'login', 'login_failed', 'logout', 'token_refresh', 'token_reuse_detected', 'password_change', 'password_reset', 'create', 'read',
  'update', 'delete', 'restore', 'export', 'download', 'upload', 'assign', 'ai_call', 'status_change', 'sign', 'approve', 'reject',
  'permission_denied', 'settings_change',
] as const;

export const AUDIT_GROUPS: Record<string, string[]> = {
  auth: ['login', 'login_failed', 'logout', 'token_refresh', 'token_reuse_detected', 'password_change', 'password_reset'],
  data: ['create', 'read', 'update', 'delete', 'restore', 'assign', 'status_change'],
  files: ['upload', 'download', 'export'],
  clinical: ['sign', 'approve', 'reject', 'ai_call'],
  security: ['permission_denied', 'settings_change'],
};

/** Server accepts at most 90 days per request (doc 03, 3.20). */
export function auditRangeOk(from?: string, to?: string): boolean {
  if (!from || !to) return true;
  if (from > to) return false;
  return (new Date(to).getTime() - new Date(from).getTime()) / 86_400_000 <= 90;
}

export function useAudit(f: AuditFilter) {
  return useQuery({
    queryKey: qk.audit.list(f),
    queryFn: ({ signal }) => get<Paged<AuditLogItem>>('/audit-logs', { ...f, to: f.to ? `${f.to}T23:59:59Z` : undefined, from: f.from ? `${f.from}T00:00:00Z` : undefined }, signal),
    placeholderData: keepPreviousData,
    enabled: auditRangeOk(f.from, f.to),
  });
}
