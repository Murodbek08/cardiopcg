import { useMemo } from 'react';
import { Link, useParams } from '@tanstack/react-router';
import { useQueries } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Alert, BarsChart, Button, Card, CardBody, CardHeader, ChartCard, ErrorState, PageHeader, SkeletonRows, StatusBadge, TimeSeriesChart, formatDate, formatDateTime, get } from '@/shared';
import type { ExamDetail } from '@/shared/api/types';
import { usePatient, usePatientExams } from '../api';

/** Trends from the patient's examinations: metrics absent for an exam stay as gaps (never zero). */
export function PatientTrendsPage() {
  const { t } = useTranslation('patients');
  const { id } = useParams({ strict: false }) as { id: string };
  const patient = usePatient(id);
  const exams = usePatientExams(id);
  const list = useMemo(() => (exams.data?.items ?? []).filter((e) => e.status !== 'draft' && e.status !== 'cancelled').sort((a, b) => a.examined_at.localeCompare(b.examined_at)).slice(-10), [exams.data]);
  const details = useQueries({ queries: list.map((e) => ({ queryKey: ['exams', 'detail', e.id], queryFn: ({ signal }: { signal: AbortSignal }) => get<ExamDetail>(`/examinations/${e.id}`, undefined, signal), staleTime: 60_000 })) });
  const loading = exams.isLoading || details.some((d) => d.isLoading);

  const rows = useMemo(
    () => details.flatMap((d) => (d.data ? [d.data] : [])).map((e) => ({
      t: formatDate(e.examined_at), hr: e.analysis?.heart_rate_bpm ?? e.heart_rate_bpm ?? null, sys: e.bp_systolic ?? null, dia: e.bp_diastolic ?? null,
      grade: e.analysis?.murmur_grade ?? null, confidence: e.analysis ? Math.round(e.analysis.confidence * 100) : null,
    })),
    [details],
  );

  if (patient.isError) return <ErrorState error={patient.error} onRetry={() => void patient.refetch()} />;
  return (
    <div className="space-y-5">
      <PageHeader title={`${patient.data?.full_name ?? ''}: ${t('trends.title')}`} breadcrumbs={[{ label: t('title'), to: '/patients' }, { label: patient.data?.full_name ?? '...', to: `/patients/${id}` }, { label: t('trends.title') }]} />
      {!loading && list.length < 2 && <Alert tone="info">{t('trends.need_two')}</Alert>}
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title={t('trends.hr')} isLoading={loading} isEmpty={!rows.some((r) => r.hr != null)} table={{ columns: [t('exam_cols.date'), 'HR'], rows: rows.map((r) => [r.t, r.hr]) }} height={240}>
          <TimeSeriesChart data={rows} series={[{ key: 'hr', label: 'HR (bpm)' }]} xKey="t" />
        </ChartCard>
        <ChartCard title={t('trends.bp')} isLoading={loading} isEmpty={!rows.some((r) => r.sys != null)} table={{ columns: [t('exam_cols.date'), t('trends.sys'), t('trends.dia')], rows: rows.map((r) => [r.t, r.sys, r.dia]) }} height={240}>
          <TimeSeriesChart data={rows} series={[{ key: 'sys', label: t('trends.sys') }, { key: 'dia', label: t('trends.dia') }]} xKey="t" />
        </ChartCard>
        <ChartCard title={t('trends.murmur')} isLoading={loading} isEmpty={!rows.some((r) => r.grade != null)} table={{ columns: [t('exam_cols.date'), t('trends.murmur')], rows: rows.map((r) => [r.t, r.grade]) }} height={240}>
          <BarsChart data={rows} xKey="t" series={[{ key: 'grade', label: t('trends.murmur') }]} />
        </ChartCard>
        <ChartCard title={t('trends.confidence')} isLoading={loading} isEmpty={!rows.some((r) => r.confidence != null)} table={{ columns: [t('exam_cols.date'), '%'], rows: rows.map((r) => [r.t, r.confidence]) }} height={240}>
          <TimeSeriesChart data={rows} series={[{ key: 'confidence', label: '%' }]} xKey="t" unit="%" />
        </ChartCard>
      </div>
      <Card>
        <CardHeader title={t('trends.timeline')} />
        <CardBody>
          {exams.isLoading ? <SkeletonRows rows={3} /> : (
            <ol className="space-y-3">
              {[...(exams.data?.items ?? [])].sort((a, b) => b.examined_at.localeCompare(a.examined_at)).map((e) => (
                <li key={e.id} className="flex flex-wrap items-center justify-between gap-2 border-l-2 border-brand-500 pl-3 text-sm">
                  <span><span className="font-mono-num">{e.exam_no}</span> <span className="text-muted">{formatDateTime(e.examined_at)}</span></span>
                  <span className="flex items-center gap-2"><StatusBadge kind="exam" value={e.status} /><StatusBadge kind="pcg" value={e.ai?.pcg_class} /><Button asChild size="sm" variant="outline"><Link to="/exams/$id" params={{ id: e.id }}>{t('common:actions.open')}</Link></Button></span>
                </li>
              ))}
            </ol>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
