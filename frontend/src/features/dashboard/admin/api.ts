import { useQuery } from '@tanstack/react-query';
import { get, qk } from '@/shared';
import type { AdminKpis, AiPerformance, AuditLogItem, Distribution, HealthDeep, HeatmapResponse, Paged, SystemAnalytics, Timeseries, WorkloadResponse } from '@/shared/api/types';

export type RangeParams = { from: string; to: string };

const ANALYTICS_STALE = 2 * 60_000;

function useAdmin<T>(name: string, params: Record<string, unknown>, path: string) {
  return useQuery({
    queryKey: qk.analytics.admin(name, params),
    queryFn: ({ signal }) => get<T>(path, { tz: 'Asia/Tashkent', ...params }, signal),
    staleTime: ANALYTICS_STALE,
    refetchInterval: 60_000, // no global SSE stream in doc 01: poll, WS events also invalidate ['analytics']
    placeholderData: (prev) => prev,
  });
}

export const useKpis = (r: RangeParams) => useAdmin<AdminKpis>('kpis', r, '/analytics/admin/kpis');
export const useTimeseries = (r: RangeParams, metric: string, granularity = 'day') =>
  useAdmin<Timeseries>(`ts:${metric}`, { ...r, metric, granularity }, '/analytics/admin/timeseries');
export const useDistribution = (r: RangeParams, dimension: string) =>
  useAdmin<Distribution>(`dist:${dimension}`, { ...r, dimension }, '/analytics/admin/distributions');
export const useWorkload = (r: RangeParams) => useAdmin<WorkloadResponse>('workload', r, '/analytics/admin/workload');
export const useHeatmap = (r: RangeParams) => useAdmin<HeatmapResponse>('heatmap', { ...r, metric: 'examinations' }, '/analytics/admin/heatmap');
export const useAiPerformance = (r: RangeParams) => useAdmin<AiPerformance>('ai', r, '/analytics/admin/ai-performance');
export const useSystemAnalytics = (r: RangeParams) => useAdmin<SystemAnalytics>('system', r, '/analytics/admin/system');

export function useHealthDeep() {
  return useQuery({ queryKey: qk.health, queryFn: ({ signal }) => get<HealthDeep>('/system/health/deep', undefined, signal), refetchInterval: 30_000, retry: 0 });
}

export function useRecentAudit() {
  return useQuery({ queryKey: qk.audit.recent, queryFn: ({ signal }) => get<Paged<AuditLogItem>>('/audit-logs', { limit: 5 }, signal), refetchInterval: 60_000 });
}
