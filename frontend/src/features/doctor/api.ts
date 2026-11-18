import { useQuery } from '@tanstack/react-query';
import { get } from '@/shared';
import type { Distribution, KpiValue, PatientBrief, Severity, PcgClass, Timeseries } from '@/shared/api/types';

type Range = { from: string; to: string };
const STALE = 2 * 60_000;
const common = { staleTime: STALE, refetchInterval: 60_000, placeholderData: <T,>(p: T) => p } as const;

export interface DoctorKpis { period: Range; kpis: Record<string, KpiValue> }
export interface QueueItem { exam_id: string; exam_no: string; patient: PatientBrief; priority: 'routine' | 'urgent' | 'emergency'; severity: Severity | null; ai_class: PcgClass | null; waiting_min: number | null }
export interface AiVsDoctor {
  total: number; agree: number; partial: number; disagree: number; agreement_pct: number | null; weighted_agreement_pct: number | null;
  disagreements: { exam_id: string; ai_class: string; final_class: string; reason: string | null; signed_at: string }[];
  trend: { t: string; agreement_pct: number }[];
}
export interface FollowUp { exam_id: string; exam_no: string; follow_up_date: string; notes: string | null; patient: PatientBrief }

const useDoc = <T,>(key: string, r: Range | null, path: string, params: Record<string, unknown> = {}) =>
  useQuery({ queryKey: ['analytics', 'doctor', key, r, params], queryFn: ({ signal }) => get<T>(path, { ...r, tz: 'Asia/Tashkent', ...params }, signal), ...common });

export const useDoctorKpis = (r: Range) => useDoc<DoctorKpis>('kpis', r, '/analytics/doctor/kpis');
export const useDoctorQueue = () => useDoc<{ items: QueueItem[] }>('queue', null, '/analytics/doctor/queue');
export const useDoctorTimeseries = (r: Range, metric: string) => useDoc<Timeseries>(`ts:${metric}`, r, '/analytics/doctor/timeseries', { metric, granularity: 'day' });
export const useDoctorDistribution = (r: Range, dimension: string) => useDoc<Distribution>(`dist:${dimension}`, r, '/analytics/doctor/distributions', { dimension });
export const useAiVsDoctor = (r: Range) => useDoc<AiVsDoctor>('aivs', r, '/analytics/doctor/ai-vs-doctor');
export const useFollowUps = () => useDoc<{ items: FollowUp[] }>('followups', null, '/analytics/doctor/follow-ups', { days: 30 });
