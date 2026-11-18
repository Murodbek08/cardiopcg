import { useMemo } from 'react';
import { Link, useNavigate, useParams } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import type { ColumnDef } from '@tanstack/react-table';
import { IconAlertTriangle, IconPencil, IconPlus, IconStethoscope } from '@tabler/icons-react';
import {
  Alert, Badge, Button, Card, CardBody, CardHeader, DataTable, EmptyState, ErrorState, PageHeader, SkeletonRows, StatusBadge, Tabs, TabsContent, TabsList, TabsTrigger,
  formatDate, formatDateTime, formatNumber, usePermission,
} from '@/shared';
import { useAuthStore } from '@/shared/store/auth';
import { maskName } from '@/shared/lib/mask';
import type { ExamListItem } from '@/shared/api/types';
import { usePatient, usePatientExams } from '../api';

export function PatientDetailPage() {
  const { t } = useTranslation('patients');
  const { id } = useParams({ strict: false }) as { id: string };
  const navigate = useNavigate();
  const role = useAuthStore((s) => s.user?.role);
  const canWrite = usePermission('patient:write');
  const canCreateExam = usePermission('exam:create');
  const unmasked = usePermission('patient:read_unmasked');
  const q = usePatient(id);
  const exams = usePatientExams(id);

  const examCols = useMemo<ColumnDef<ExamListItem>[]>(
    () => [
      { header: t('exam_cols.no'), cell: (c) => <span className="font-mono-num">{c.row.original.exam_no}</span> },
      { header: t('exam_cols.date'), cell: (c) => formatDateTime(c.row.original.examined_at) },
      { header: t('exam_cols.status'), cell: (c) => <StatusBadge kind="exam" value={c.row.original.status} /> },
      { header: t('exam_cols.priority'), meta: { hideBelow: 'md' }, cell: (c) => <StatusBadge kind="priority" value={c.row.original.priority} /> },
      // Clinical result only for roles that may see it (admin: aggregate class only, nurse: after sign-off handled by the next agent)
      { header: t('exam_cols.ai'), meta: { hideBelow: 'md' }, cell: (c) => <StatusBadge kind="pcg" value={c.row.original.ai?.pcg_class} /> },
    ],
    [t],
  );

  if (q.isLoading) return <SkeletonRows rows={6} />;
  if (q.isError) {
    return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  }
  const p = q.data!;
  const name = unmasked ? p.full_name : maskName(p.full_name);
  const activeAllergies = p.allergies.filter((a) => a.is_active);
  const archived = p.is_active === false;

  return (
    <div>
      <PageHeader
        title={name}
        description={<span className="font-mono-num">{p.mrn} &middot; {p.age} / {t(`common:gender.${p.gender}`)}{unmasked && p.blood_group !== 'unknown' ? ` · ${p.blood_group}` : ''}{unmasked && p.bmi ? ` · BMI ${p.bmi}` : ''}</span>}
        breadcrumbs={[{ label: t('title'), to: '/patients' }, { label: name }]}
        actions={
          <>
            {unmasked && <Button variant="outline" asChild><Link to="/patients/$id/timeline" params={{ id }}>{t('trends.title')}</Link></Button>}
            {canWrite && !archived && <Button variant="outline" asChild><Link to="/patients/$id/edit" params={{ id }}><IconPencil size={18} aria-hidden /> {t('common:actions.edit')}</Link></Button>}
            {canCreateExam && !archived && <Button asChild><Link to="/exams/new" search={{ patientId: id } as never}><IconPlus size={18} aria-hidden /> {t('new_exam')}</Link></Button>}
          </>
        }
      />
      {archived && <Alert tone="warning" className="mb-4">{t('archived')}</Alert>}
      {/* Allergies must always be visible (clinical safety) for roles that may see clinical detail */}
      {unmasked && activeAllergies.length > 0 && (
        <Alert tone="warning" className="mb-4" title={t('allergies')}>
          <span className="flex flex-wrap gap-2">{activeAllergies.map((a) => <Badge key={a.id} tone="warning" icon={IconAlertTriangle}>{a.substance}</Badge>)}</span>
        </Alert>
      )}
      {role === 'admin' && <Alert tone="info" className="mb-4">{t('admin_masked')}</Alert>}

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">{t('tabs.overview')}</TabsTrigger>
          {unmasked && <TabsTrigger value="history">{t('tabs.history')}</TabsTrigger>}
          <TabsTrigger value="exams">{t('tabs.exams')} ({exams.data?.items.length ?? 0})</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <div className="grid gap-4 md:grid-cols-3">
            <Card><CardHeader title={t('stats.exam_count')} /><CardBody><p className="text-display font-bold">{formatNumber(p.stats?.exam_count ?? p.exam_count ?? 0)}</p></CardBody></Card>
            <Card><CardHeader title={t('stats.last_exam')} /><CardBody><p className="text-h2 font-semibold">{formatDate(p.stats?.last_exam_at ?? p.last_exam_at)}</p></CardBody></Card>
            {unmasked ? (
              <Card><CardHeader title={t('medications')} /><CardBody>
                {p.current_medications.filter((m) => m.is_active).length === 0 ? <p className="text-sm text-muted">{t('none')}</p> : (
                  <ul className="space-y-1 text-sm">{p.current_medications.filter((m) => m.is_active).map((m) => <li key={m.id}>{m.drug_name} <span className="text-muted">{[m.dose, m.frequency].filter(Boolean).join(', ')}</span></li>)}</ul>
                )}
              </CardBody></Card>
            ) : (
              <Card><CardHeader title={t('stats.last_class')} /><CardBody><StatusBadge kind="pcg" value={p.stats?.last_pcg_class ?? null} /></CardBody></Card>
            )}
          </div>
        </TabsContent>

        {unmasked && (
          <TabsContent value="history">
            <Card><CardBody>
              {p.medical_history.length === 0 ? <p className="text-sm text-muted">{t('none')}</p> : (
                <ul className="divide-y divide-border">{p.medical_history.map((h) => (
                  <li key={h.id} className="flex items-center justify-between gap-3 py-2 text-sm"><span>{h.title}{h.icd10_code && <span className="ml-2 font-mono-num text-xs text-muted">{h.icd10_code}</span>}</span><Badge tone="neutral" icon={false}>{h.kind}</Badge></li>
                ))}</ul>
              )}
            </CardBody></Card>
          </TabsContent>
        )}

        <TabsContent value="exams">
          <div className="overflow-hidden rounded-lg border border-border bg-surface shadow-card">
            <DataTable
              columns={examCols}
              data={exams.data?.items ?? []}
              getRowId={(r) => r.id}
              isLoading={exams.isLoading}
              error={exams.error}
              onRetry={() => void exams.refetch()}
              onRowClick={(r) => void navigate({ to: '/exams/$id', params: { id: r.id } } as never)}
              emptyState={<EmptyState icon={IconStethoscope} title={t('no_exams')} />}
              caption={t('tabs.exams')}
            />
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
