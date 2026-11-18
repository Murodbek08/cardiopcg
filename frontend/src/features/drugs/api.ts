import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { get, normalizePage, post, put, qk, uploadFile } from '@/shared';
import type { DrugDetail, DrugListItem, Paged } from '@/shared/api/types';

/**
 * Drug knowledge-base admin endpoints (`/api/v1/admin/drugs*`), verified against backend/openapi.json
 * and backend/app/schemas/drugs.py (field names, list envelope `{items, page:{page,page_size,total}}`).
 */
const BASE = '/admin/drugs';

export interface DrugsFilter {
  q?: string;
  group?: string;
  status?: string;
  page: number;
  page_size: number;
}

export function useDrugs(f: DrugsFilter, enabled = true) {
  return useQuery({
    queryKey: qk.drugs.list(f),
    queryFn: async ({ signal }) => normalizePage(await get<Paged<DrugListItem> | DrugListItem[]>(BASE, { ...f }, signal)),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useDrug(id: string | undefined) {
  return useQuery({ queryKey: qk.drugs.detail(id ?? ''), queryFn: ({ signal }) => get<DrugDetail>(`${BASE}/${id}`, undefined, signal), enabled: !!id });
}

export type DrugInput = Omit<DrugDetail, 'id' | 'version' | 'status' | 'updated_at'>;

export function useSaveDrug(id?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: DrugInput) => (id ? put<DrugDetail>(`${BASE}/${id}`, body) : post<DrugDetail>(BASE, body)),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.drugs.all }),
  });
}

export function useDrugLifecycle(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (action: 'publish' | 'archive') => post<DrugDetail>(`${BASE}/${id}/${action}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.drugs.all }),
  });
}

export interface ImportReport {
  total: number;
  valid: number;
  errors: { row: number; message: string }[];
}

export function importDrugsCsv(file: File, dryRun: boolean): Promise<ImportReport> {
  return uploadFile<ImportReport>({ url: `${BASE}/import?dry_run=${dryRun}`, file });
}

/** Items required before a drug may be published (doc 03, 3.22 validation). */
export function publishBlockers(d: Pick<DrugDetail, 'sources' | 'dose_rules' | 'group' | 'inn'>): ('sources' | 'dose_rules' | 'group' | 'inn')[] {
  const out: ('sources' | 'dose_rules' | 'group' | 'inn')[] = [];
  if (!d.inn?.trim()) out.push('inn');
  if (!d.group?.trim()) out.push('group');
  if (!d.dose_rules?.length) out.push('dose_rules');
  if (!d.sources?.length) out.push('sources');
  return out;
}

export interface DrugVersion { version: number; status: string; change?: string | null; changed_by?: string | null; created_at: string }
export function useDrugVersions(id: string | undefined) {
  return useQuery({ queryKey: ['drugs', 'versions', id], queryFn: ({ signal }) => get<{ items: DrugVersion[] }>(`${BASE}/${id}/versions`, undefined, signal), enabled: !!id });
}
