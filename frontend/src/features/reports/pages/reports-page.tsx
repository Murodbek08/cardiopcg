import { useEffect, useMemo, useState } from 'react';
import { useQueries } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { IconDownload, IconFileExport, IconRefresh } from '@tabler/icons-react';
import {
  Alert, BarsChart, Button, Card, CardBody, CardHeader, ChartCard, CheckboxField, DonutChart, EmptyState, Field, Input, PageHeader, RadioGroup, RadioItem, StatusBadge,
  TimeSeriesChart, daysAgo, errorMessage, formatBytes, formatDateTime, get, qk, today, toast, usePermission,
} from '@/shared';
import { useAuthStore } from '@/shared/store/auth';
import type { Distribution, Timeseries } from '@/shared/api/types';
import { validateRange } from '@/shared/ui/period-picker';
import { DEFAULT_COLUMNS, fetchExport, saveBlob, startExport, useExportJobs, type ExportKind, type JobRecord } from '../api';

type TemplateId = 'monthly' | 'ai_accuracy' | 'workload' | 'patients';
const TEMPLATES: Record<TemplateId, { kind: ExportKind; filters: (from: string, to: string) => Record<string, unknown> }> = {
  monthly: { kind: 'examinations', filters: (from, to) => ({ examined_from: from, examined_to: to }) },
  ai_accuracy: { kind: 'conclusions', filters: (from, to) => ({ examined_from: from, examined_to: to, status: ['completed'] }) },
  workload: { kind: 'analytics_timeseries', filters: (from, to) => ({ from, to }) },
  patients: { kind: 'patients', filters: (from, to) => ({ created_from: from, created_to: to }) },
};

function Preview({ template, from, to }: { template: TemplateId; from: string; to: string }) {
  const { t } = useTranslation('admin');
  const admin = useAuthStore((s) => s.user?.role === 'admin');
  const base = admin ? '/analytics/admin' : '/analytics/doctor';
  const params = { from, to, tz: 'Asia/Tashkent' };
  const [ts, dist] = useQueries({
    queries: [
      { queryKey: qk.analytics.admin('report-ts', { ...params, template, base }), queryFn: () => get<Timeseries>(`${base}/timeseries`, { ...params, metric: template === 'ai_accuracy' && !admin ? 'agreement' : 'examinations', granularity: 'day' }), staleTime: 60_000 },
      { queryKey: qk.analytics.admin('report-dist', { ...params, template, base }), queryFn: () => get<Distribution>(`${base}/distributions`, { ...params, dimension: admin ? 'pcg_class' : 'final_pcg_class' }), staleTime: 60_000 },
    ],
  });
  const series = (ts.data?.series ?? []).map((p) => ({ t: p.t, value: p.value }));
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ChartCard title={t('reports.preview_ts')} isLoading={ts.isLoading} error={ts.error} onRetry={() => void ts.refetch()} isEmpty={!series.length}
        table={{ columns: [t('reports.date'), t('reports.value')], rows: series.map((s) => [s.t, s.value]) }} exportName="report-preview-ts" height={240}>
        {template === 'workload' ? <BarsChart data={series.map((s) => ({ name: s.t, value: s.value }))} series={[{ key: 'value', label: t('reports.value') }]} /> : <TimeSeriesChart data={series} series={[{ key: 'value', label: t('reports.value') }]} area />}
      </ChartCard>
      <ChartCard title={t('reports.preview_dist')} isLoading={dist.isLoading} error={dist.error} onRetry={() => void dist.refetch()} isEmpty={!dist.data?.items.length}
        table={{ columns: [t('reports.class'), t('reports.value'), '%'], rows: (dist.data?.items ?? []).map((i) => [i.key, i.count, i.pct]) }} exportName="report-preview-dist" height={240}>
        <DonutChart data={(dist.data?.items ?? []).map((i) => ({ name: i.key, value: i.count }))} />
      </ChartCard>
    </div>
  );
}

function JobRow({ job }: { job: JobRecord }) {
  const { t } = useTranslation('admin');
  const patchJob = useExportJobs((s) => s.patch);
  const pending = job.status === 'pending' || job.status === 'running';
  useEffect(() => {
    if (!pending) return;
    let stop = false;
    const tick = async () => {
      try {
        const r = await fetchExport(job.id);
        if (stop) return;
        patchJob(job.id, { status: r.status, fileUrl: r.file_url, sizeBytes: r.size_bytes, error: r.error });
      } catch (e) {
        if (!stop) patchJob(job.id, { status: 'failed', error: errorMessage(e, t as never) });
      }
    };
    const id = setInterval(() => void tick(), 3000);
    void tick();
    return () => { stop = true; clearInterval(id); };
  }, [pending, job.id, patchJob, t]);
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 border-b border-border py-3 last:border-0">
      <div className="min-w-0">
        <p className="font-medium">{job.label}</p>
        <p className="text-xs text-muted">{`${job.from} - ${job.to} · ${formatDateTime(job.createdAt)}${job.sizeBytes ? ` · ${formatBytes(job.sizeBytes)}` : ''}`}</p>
        {job.error && <p className="text-xs text-danger-500">{job.error}</p>}
      </div>
      <div className="flex items-center gap-2">
        <StatusBadge kind="job" value={job.status} />
        {job.status === 'succeeded' && job.fileUrl && (
          <Button size="sm" asChild><a href={job.fileUrl} download><IconDownload size={16} aria-hidden /> {t('common:actions.download')}</a></Button>
        )}
        {job.status === 'failed' && <Button size="sm" variant="outline" onClick={() => patchJob(job.id, { status: 'pending', error: null })}><IconRefresh size={16} aria-hidden /> {t('common:actions.retry')}</Button>}
      </div>
    </li>
  );
}

export function ReportsPage() {
  const { t } = useTranslation('admin');
  const role = useAuthStore((s) => s.user?.role);
  const canPhi = usePermission('patient:export');
  const { jobs, add, clear } = useExportJobs();
  const [template, setTemplate] = useState<TemplateId>('monthly');
  const [from, setFrom] = useState(daysAgo(29));
  const [to, setTo] = useState(today());
  const [anonymize, setAnonymize] = useState(true);
  const [busy, setBusy] = useState(false);

  const yearOk = useMemo(() => validateRange(from, to), [from, to]);
  const spec = TEMPLATES[template];
  // Admin exports are always anonymised (no personal identifiers); a doctor may opt out for own patients.
  const forceAnon = role === 'admin' || !canPhi;

  const submit = async () => {
    setBusy(true);
    try {
      const res = await startExport({ kind: spec.kind, filters: spec.filters(from, to), columns: DEFAULT_COLUMNS[spec.kind], anonymize: forceAnon ? true : anonymize });
      const label = t(`reports.templates.${template}`);
      if (res.mode === 'inline') {
        saveBlob(res.blob, res.filename);
        add({ id: `inline-${Date.now()}`, kind: spec.kind, label, from, to, createdAt: new Date().toISOString(), status: 'succeeded' });
        toast.success(t('reports.downloaded'));
      } else {
        add({ id: res.exportId, kind: spec.kind, label, from, to, createdAt: new Date().toISOString(), status: 'pending' });
        toast.info(t('reports.queued'));
      }
    } catch (e) {
      toast.error(errorMessage(e, t as never));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader title={t('reports.title')} description={t('reports.subtitle')} />
      <Card>
        <CardHeader title={t('reports.builder')} />
        <CardBody className="space-y-5">
          <div>
            <p className="mb-2 text-sm font-medium">{t('reports.template')}</p>
            <RadioGroup value={template} onValueChange={(v) => setTemplate(v as TemplateId)} aria-label={t('reports.template')}>
              {(Object.keys(TEMPLATES) as TemplateId[]).filter((id) => !(role !== 'admin' && id === 'workload')).map((id) => <RadioItem key={id} value={id} label={t(`reports.templates.${id}`)} />)}
            </RadioGroup>
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label={t('reports.from')}><Input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label={t('reports.to')} error={!yearOk ? t('reports.range_error') : undefined}><Input type="date" value={to} min={from} max={today()} onChange={(e) => setTo(e.target.value)} /></Field>
            <div className="flex flex-col justify-end gap-1">
              <p className="text-sm font-medium">{t('reports.format')}</p>
              <p className="flex h-10 items-center text-sm">CSV (UTF-8)</p>
            </div>
          </div>
          <div className="space-y-2">
            <CheckboxField label={t('reports.anonymize')} checked={forceAnon ? true : anonymize} disabled={forceAnon} onCheckedChange={(c) => setAnonymize(c === true)} />
            {forceAnon ? <p className="text-xs text-muted">{t('reports.anonymize_forced')}</p> : !anonymize && <Alert tone="warning">{t('reports.phi_warning')}</Alert>}
          </div>
          <div className="flex justify-end">
            <Button onClick={() => void submit()} loading={busy} disabled={!yearOk}><IconFileExport size={18} aria-hidden /> {t('reports.create')}</Button>
          </div>
        </CardBody>
      </Card>

      <h2 className="mb-3 mt-8 text-h2 font-semibold">{t('reports.preview')}</h2>
      {yearOk ? <Preview template={template} from={from} to={to} /> : <Alert tone="warning">{t('reports.range_error')}</Alert>}

      <Card className="mt-8">
        <CardHeader title={t('reports.jobs')} actions={jobs.length > 0 ? <Button size="sm" variant="ghost" onClick={clear}>{t('common:actions.clear_filters')}</Button> : undefined} />
        <CardBody>
          {jobs.length === 0 ? <EmptyState title={t('reports.no_jobs')} className="py-6" /> : <ul>{jobs.map((j) => <JobRow key={j.id} job={j} />)}</ul>}
        </CardBody>
      </Card>
    </div>
  );
}
