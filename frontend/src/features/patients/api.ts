import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { get, qk } from '@/shared';
import type { ExamListItem, Paged, PatientDetail, PatientListItem } from '@/shared/api/types';

export interface PatientsFilter {
  q?: string;
  gender?: string;
  age_min?: number;
  age_max?: number;
  has_allergies?: boolean;
  sort?: string;
  cursor?: string;
  limit: number;
}

export function usePatients(f: PatientsFilter) {
  return useQuery({
    queryKey: qk.patients.list(f),
    queryFn: ({ signal }) => get<Paged<PatientListItem>>('/patients', { ...f, with_total: true }, signal),
    placeholderData: keepPreviousData,
    enabled: !(f.age_min !== undefined && f.age_max !== undefined && f.age_min > f.age_max),
  });
}

export function usePatient(id: string) {
  return useQuery({ queryKey: qk.patients.detail(id), queryFn: ({ signal }) => get<PatientDetail>(`/patients/${id}`, undefined, signal) });
}

export function usePatientExams(patientId: string) {
  return useQuery({
    queryKey: ['patients', 'exams', patientId],
    queryFn: ({ signal }) => get<Paged<ExamListItem>>('/examinations', { patient_id: patientId, limit: 50 }, signal),
  });
}
