import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { api, cleanParams, get } from '@/shared';
import { normalizeError } from '@/shared/api/errors';
import type { ExportJob } from '@/shared/api/types';

export type ExportKind = 'examinations' | 'patients' | 'analytics_timeseries' | 'conclusions';

export interface ExportRequest {
  kind: ExportKind;
  filters: Record<string, unknown>;
  columns?: string[];
  anonymize: boolean;
}

export const DEFAULT_COLUMNS: Record<ExportKind, string[]> = {
  examinations: ['exam_no', 'mrn', 'age', 'gender', 'examined_at', 'ai_class', 'ai_confidence', 'final_class', 'agreement', 'severity', 'doctor'],
  patients: ['mrn', 'age', 'gender', 'exam_count', 'last_exam_at'],
  analytics_timeseries: ['date', 'examinations', 'completed', 'abnormal'],
  conclusions: ['exam_no', 'final_class', 'final_severity', 'agreement', 'signed_at', 'doctor'],
};

export interface JobRecord {
  id: string;
  kind: ExportKind;
  label: string;
  from: string;
  to: string;
  createdAt: string;
  status: ExportJob['status'];
  fileUrl?: string | null;
  sizeBytes?: number | null;
  error?: string | null;
}

interface JobsState {
  jobs: JobRecord[];
  add: (j: JobRecord) => void;
  patch: (id: string, p: Partial<JobRecord>) => void;
  clear: () => void;
}

/** Job ids only (no PHI); kept per tab session because the API has no list endpoint (doc 01, 3.13). */
export const useExportJobs = create<JobsState>()(
  persist(
    (set) => ({
      jobs: [],
      add: (j) => set((s) => ({ jobs: [j, ...s.jobs].slice(0, 30) })),
      patch: (id, p) => set((s) => ({ jobs: s.jobs.map((j) => (j.id === id ? { ...j, ...p } : j)) })),
      clear: () => set({ jobs: [] }),
    }),
    { name: 'cardiopcg-exports', storage: createJSONStorage(() => sessionStorage) },
  ),
);

export type StartResult = { mode: 'inline'; blob: Blob; filename: string } | { mode: 'job'; exportId: string };

/** POST /export/csv: small exports return text/csv directly (200); large ones return 202 + export_id. */
export async function startExport(req: ExportRequest): Promise<StartResult> {
  try {
    const res = await api.post('/export/csv', req, { responseType: 'blob', validateStatus: (s) => s === 200 || s === 202 });
    if (res.status === 202) {
      const json = JSON.parse(await (res.data as Blob).text()) as { export_id: string };
      return { mode: 'job', exportId: json.export_id };
    }
    const type = String(res.headers['content-type'] ?? '');
    if (type.includes('application/json')) {
      const json = JSON.parse(await (res.data as Blob).text()) as { export_id?: string };
      if (json.export_id) return { mode: 'job', exportId: json.export_id };
    }
    const cd = String(res.headers['content-disposition'] ?? '');
    const m = /filename="?([^";]+)"?/i.exec(cd);
    return { mode: 'inline', blob: res.data as Blob, filename: m?.[1] ?? `${req.kind}.csv` };
  } catch (e) {
    throw normalizeError(e);
  }
}

export const fetchExport = (id: string) => get<ExportJob>(`/export/${id}`);

export function saveBlob(blob: Blob, filename: string): void {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
}

export { cleanParams };
