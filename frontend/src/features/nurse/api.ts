import { useQuery } from '@tanstack/react-query';
import { get } from '@/shared';

type Range = { from: string; to: string };

export function useNurseKpis(r: Range) {
  return useQuery({
    queryKey: ['analytics', 'nurse', 'kpis', r],
    queryFn: ({ signal }) => get<Record<string, number | null>>('/analytics/nurse/kpis', { ...r, tz: 'Asia/Tashkent' }, signal),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}
