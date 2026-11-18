import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { get, qk } from '@/shared';
import type { ExamDetail, ExamListItem, Paged, PcgSegment } from '@/shared/api/types';

export type StatusTab = 'all' | 'uploaded' | 'analyzing' | 'review' | 'completed' | 'failed';

export const STATUS_TABS: Record<StatusTab, string[] | undefined> = {
  all: undefined,
  uploaded: ['uploaded'],
  analyzing: ['queued', 'processing'],
  review: ['ai_ready', 'in_review'],
  completed: ['completed'],
  failed: ['failed'],
};

export interface ExamsFilter {
  status?: string[];
  q?: string;
  patient_id?: string;
  mine?: boolean;
  pcg_class?: string;
  severity?: string;
  needs_review?: boolean;
  examined_from?: string;
  examined_to?: string;
  sort?: string;
  cursor?: string;
  limit: number;
}

export function useExams(f: ExamsFilter) {
  return useQuery({
    queryKey: qk.exams.list(f),
    queryFn: ({ signal }) => get<Paged<ExamListItem>>('/examinations', { ...f, with_total: true }, signal),
    placeholderData: keepPreviousData,
    // analysing rows update through WS events ('exams' keys are invalidated); light polling as a fallback
    refetchInterval: (q) => (q.state.data?.items.some((i) => i.status === 'queued' || i.status === 'processing') ? 10_000 : false),
  });
}

export function useExam(id: string) {
  return useQuery({ queryKey: qk.exams.detail(id), queryFn: ({ signal }) => get<ExamDetail>(`/examinations/${id}`, undefined, signal) });
}

export function useSegments(id: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.exams.segments(id),
    queryFn: ({ signal }) => get<{ items: PcgSegment[] }>(`/examinations/${id}/segments`, undefined, signal),
    enabled,
    select: (d) => d.items,
  });
}

// ======================================================================= Phase 2: clinical API
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { del, patch, post, put, uploadFile } from '@/shared';
import type {
  AiReport, AiReportNurse, AnalysisResult, Conclusion, ConclusionInput, ExamStatusInfo, Prescription, Recording,
} from '@/shared/api/types';

export type CreateExamInput = {
  patient_id: string;
  priority?: 'routine' | 'urgent' | 'emergency';
  complaints?: string | null;
  symptoms?: string[];
  patient_position?: string | null;
  assigned_doctor_id?: string | null;
  heart_rate_bpm?: number | null;
  bp_systolic?: number | null;
  bp_diastolic?: number | null;
  spo2_pct?: number | null;
  temperature_c?: number | null;
  weight_kg_at_exam?: number | null;
};

export function useCreateExam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: CreateExamInput) => post<ExamDetail>('/examinations', b),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.exams.all }),
  });
}

export function useUpdateExam(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: Partial<CreateExamInput>) => patch<ExamDetail>(`/examinations/${id}`, b),
    onSuccess: (d) => qc.setQueryData(qk.exams.detail(id), d),
  });
}

export function uploadRecording(examId: string, file: File, opts: { site?: string; kind?: 'audio' | 'other_image'; replace?: boolean; onProgress?: (p: number) => void; signal?: AbortSignal }) {
  return uploadFile<Recording>({
    url: `/examinations/${examId}/recordings${opts.replace ? '?replace=true' : ''}`,
    file,
    fields: { kind: opts.kind ?? 'audio', ...(opts.site ? { site: opts.site } : {}) },
    onProgress: opts.onProgress,
    signal: opts.signal,
  });
}

export const deleteRecording = (rid: string) => del(`/recordings/${rid}`);

export function useAnalyze(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (opts?: { rerun?: boolean }) => post<{ job_id: string; exam_status: string }>(opts?.rerun ? `/examinations/${id}/reanalyze` : `/examinations/${id}/analyze`, opts?.rerun ? undefined : {}),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.exams.all }),
  });
}

export function useCancelExam(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (reason: string) => post(`/examinations/${id}/cancel`, { reason }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.exams.all }),
  });
}

export function useExamStatus(id: string, enabled: boolean, interval: number | false) {
  return useQuery({ queryKey: ['exams', 'status', id], queryFn: ({ signal }) => get<ExamStatusInfo>(`/examinations/${id}/status`, undefined, signal), enabled, refetchInterval: interval });
}

export function useAnalysis(id: string, enabled: boolean) {
  return useQuery({ queryKey: ['exams', 'analysis', id], queryFn: ({ signal }) => get<AnalysisResult>(`/examinations/${id}/analysis`, undefined, signal), enabled });
}

export function useReport(id: string, enabled: boolean) {
  return useQuery({ queryKey: ['exams', 'report', id], queryFn: ({ signal }) => get<AiReport | AiReportNurse>(`/examinations/${id}/report`, undefined, signal), enabled, retry: false });
}

export function usePublicSettings() {
  return useQuery({ queryKey: ['settings', 'public'], queryFn: ({ signal }) => get<Record<string, unknown>>('/settings/public', undefined, signal), staleTime: 10 * 60_000 });
}

export function useDoctors() {
  return useQuery({ queryKey: ['users', 'doctors'], queryFn: ({ signal }) => get<{ id: string; full_name: string; specialty?: string | null }[]>('/users/doctors', undefined, signal), staleTime: 5 * 60_000 });
}

export function useRegenerateReport(id: string) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: () => post(`/examinations/${id}/report/regenerate`), onSuccess: () => void qc.invalidateQueries({ queryKey: qk.exams.detail(id) }) });
}

// ---- prescription
export function usePrescriptionActions(examId: string) {
  const qc = useQueryClient();
  const inv = () => void qc.invalidateQueries({ queryKey: qk.exams.detail(examId) });
  return {
    approve: useMutation({ mutationFn: (v: { id: string; override_reason?: string }) => post<Prescription>(`/prescription-items/${v.id}/approve`, { override_reason: v.override_reason ?? null }), onSuccess: inv }),
    reject: useMutation({ mutationFn: (v: { id: string; reason: string }) => post<Prescription>(`/prescription-items/${v.id}/reject`, { reason: v.reason }), onSuccess: inv }),
    edit: useMutation({ mutationFn: (v: { id: string; body: Record<string, unknown> }) => patch(`/prescription-items/${v.id}`, v.body), onSuccess: inv }),
    add: useMutation({ mutationFn: (body: Record<string, unknown>) => post(`/examinations/${examId}/prescription/items`, body), onSuccess: inv }),
    safety: useMutation({ mutationFn: () => post(`/examinations/${examId}/prescription/safety-check`), onSuccess: inv }),
    regenerate: useMutation({ mutationFn: () => post(`/examinations/${examId}/prescription/regenerate`), onSuccess: inv }),
  };
}

// ---- conclusion
export function useConclusionActions(examId: string) {
  const qc = useQueryClient();
  const inv = () => {
    void qc.invalidateQueries({ queryKey: qk.exams.detail(examId) });
    void qc.invalidateQueries({ queryKey: qk.exams.all });
  };
  return {
    save: useMutation({ mutationFn: (b: ConclusionInput) => put<Conclusion>(`/examinations/${examId}/conclusion`, b), onSuccess: inv }),
    sign: useMutation({ mutationFn: () => post(`/examinations/${examId}/conclusion/sign`), onSuccess: inv }),
    amend: useMutation({ mutationFn: (b: ConclusionInput & { amend_reason: string }) => post<Conclusion>(`/examinations/${examId}/conclusion/amend`, b), onSuccess: inv }),
  };
}

export function useConclusionHistory(examId: string, enabled: boolean) {
  return useQuery({ queryKey: ['exams', 'conclusion-history', examId], queryFn: ({ signal }) => get<Conclusion[]>(`/examinations/${examId}/conclusion/history`, undefined, signal), enabled });
}
