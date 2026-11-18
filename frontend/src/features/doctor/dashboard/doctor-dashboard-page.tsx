import { useMemo } from 'react';
import { z } from 'zod';
import { Link, useNavigate } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { IconChecklist, IconCircleCheck, IconClockHour4, IconFlame, IconPlus, IconScale } from '@tabler/icons-react';
import {
  Alert, BarsChart, Badge, Button, Card, CardHeader, ChartCard, DonutChart, EmptyState, ErrorState, KpiCard, PageHeader, PercentGauge, PeriodPicker, Skeleton, StatusBadge, TimeSeriesChart,
  formatDate, formatNumber, resolvePeriod, usePermission, type Period, type PeriodKey,
} from '@/shared';
import { useUrlState } from '@/shared/hooks/url-state';
import { useAuthStore } from '@/shared/store/auth';
import { validateRange } from '@/shared/ui/period-picker';
import { useAiVsDoctor, useDoctorDistribution, useDoctorKpis, useDoctorQueue, useDoctorTimeseries, useFollowUps } from '../api';

const schema = z.object({
  range: z.enum(['today', '7d', '30d', '90d', 'custom']).catch('30d'),
  from: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().catch(undefined),
  to: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().catch(undefined),
});

export function DoctorDashboardPage() {
  const { t } = useTranslation('doctor');
  const name = useAuthStore((s) => s.user?.full_name);
  const canCreate = usePermission('exam:create');
  const navigate = useNavigate();
  const [u, setUrl] = useUrlState(schema);
  const period: Period = useMemo(() => {
    const p = resolvePeriod(u.range as PeriodKey, { from: u.from, to: u.to });
    return u.range === 'custom' && !validateRange(p.from, p.to) ? resolvePeriod('30d') : p;
  }, [u.range, u.from, u.to]);
  const r = useMemo(() => ({ from: period.from, to: period.to }), [period.from, period.to]);

  const kpis = useDoctorKpis(r);
  const queue = useDoctorQueue();
  const done = useDoctorTimeseries(r, 'completed');
  const agr = useDoctorTimeseries(r, 'agreement');
  const aivs = useAiVsDoctor(r);
  const cls = useDoctorDistribution(r, 'final_pcg_class');
  const age = useDoctorDistribution(r, 'age_group');
  const fu = useFollowUps();
  const k = kpis.data?.kpis;
  const v = (key: string) => k?.[key]?.value;
  const urgent = v('urgent_waiting') ?? 0;
  const label = (key: string) => (key ? (t(`clinical:pcg_class.${key}`, { defaultValue: key }) as string) : key);
  const items = queue.data?.items ?? [];

  return (
    <div>
      <PageHeader title={t('dashboard.greeting', { name })} actions={<>
        <PeriodPicker value={period} onChange={(p) => setUrl({ range: p.key, from: p.key === 'custom' ? p.from : undefined, to: p.key === 'custom' ? p.to : undefined })} />
        {canCreate && <Button asChild><Link to="/exams/new"><IconPlus size={18} aria-hidden /> {t('dashboard.new_exam')}</Link></Button>}
      </>} />
      {urgent > 0 && <Alert tone="danger" className="mb-4" title={t('dashboard.urgent_alert', { count: urgent })}>{t('dashboard.urgent_body')}</Alert>}

      <section aria-label="KPI" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label={t('kpi.my_pending')} icon={IconChecklist} value={formatNumber(v('my_pending'))} isLoading={kpis.isLoading} error={kpis.error} onRetry={() => void kpis.refetch()} onClick={() => void navigate({ to: '/doctor/review-queue' })} />
        <KpiCard label={t('kpi.completed_today')} icon={IconCircleCheck} value={formatNumber(v('my_completed_today'))} isLoading={kpis.isLoading} error={kpis.error} />
        <KpiCard label={t('kpi.urgent_waiting')} icon={IconFlame} value={formatNumber(v('urgent_waiting'))} invertDelta isLoading={kpis.isLoading} error={kpis.error} />
        <KpiCard label={t('kpi.avg_time')} icon={IconClockHour4} value={formatNumber(v('avg_time_to_conclusion_min'), 1)} unit={t('kpi.min')} isLoading={kpis.isLoading} error={kpis.error} />
        <KpiCard label={t('kpi.agreement')} icon={IconScale} value={v('ai_agreement_pct') != null ? `${formatNumber(v('ai_agreement_pct'), 1)}%` : '-'} isLoading={kpis.isLoading} error={kpis.error} hint={t('kpi.agreement_info')} />
        <KpiCard label={t('kpi.completed_period')} icon={IconCircleCheck} value={formatNumber(v('my_completed_period'))} isLoading={kpis.isLoading} error={kpis.error} />
        <KpiCard label={t('kpi.patients_seen')} icon={IconChecklist} value={formatNumber(v('patients_seen'))} isLoading={kpis.isLoading} error={kpis.error} />
        <KpiCard label={t('kpi.followups')} icon={IconClockHour4} value={formatNumber(v('follow_ups_due_7d'))} isLoading={kpis.isLoading} error={kpis.error} />
      </section>

      <section className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card className="lg:row-span-1">
          <CardHeader title={t('dashboard.queue')} actions={<Link to="/doctor/review-queue" className="text-sm text-brand-600 hover:underline dark:text-brand-300">{t('common:actions.show_more')}</Link>} />
          <div className="p-5">
            {queue.isLoading ? <Skeleton className="h-40" /> : queue.isError ? <ErrorState compact error={queue.error} onRetry={() => void queue.refetch()} /> : items.length === 0 ? <EmptyState icon={IconCircleCheck} title={t('dashboard.queue_empty')} className="py-6" /> : (
              <ul className="divide-y divide-border">
                {items.slice(0, 8).map((i) => (
                  <li key={i.exam_id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
                    <span className="min-w-0"><span className="font-medium">{i.patient.full_name}</span> <span className="text-xs text-muted">{i.patient.age} / {t(`common:gender.${i.patient.gender}`)}</span><br /><span className="text-xs text-muted">{i.exam_no} &middot; {i.waiting_min != null ? `${i.waiting_min} ${t('kpi.min')}` : ''}</span></span>
                    <span className="flex items-center gap-2"><StatusBadge kind="priority" value={i.priority} /><StatusBadge kind="severity" value={i.severity} /><Button asChild size="sm"><Link to="/exams/$id" params={{ id: i.exam_id }}>{t('common:actions.open')}</Link></Button></span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
        <ChartCard title={t('chart.completed')} isLoading={done.isLoading} error={done.error} onRetry={() => void done.refetch()} isEmpty={!done.data?.series.length}
          table={{ columns: [t('chart.date'), t('chart.completed')], rows: (done.data?.series ?? []).map((s) => [s.t, s.value]) }}>
          <TimeSeriesChart data={(done.data?.series ?? []).map((s) => ({ t: s.t, value: s.value }))} series={[{ key: 'value', label: t('chart.completed') }]} area />
        </ChartCard>
        <ChartCard title={t('chart.agreement')} info={t('kpi.agreement_info')} isLoading={aivs.isLoading} error={aivs.error} onRetry={() => void aivs.refetch()} isEmpty={!aivs.data}
          table={{ columns: [t('chart.agree'), t('chart.partial'), t('chart.disagree')], rows: aivs.data ? [[aivs.data.agree, aivs.data.partial, aivs.data.disagree]] : [] }}>
          <div className="grid h-full grid-cols-2 gap-2"><PercentGauge value={aivs.data?.agreement_pct} n={aivs.data?.total} label={t('chart.agree')} />
            <DonutChart data={[{ name: t('chart.agree'), value: aivs.data?.agree ?? 0 }, { name: t('chart.partial'), value: aivs.data?.partial ?? 0 }, { name: t('chart.disagree'), value: aivs.data?.disagree ?? 0 }]} /></div>
        </ChartCard>
        <ChartCard title={t('chart.agreement_trend')} isLoading={agr.isLoading || aivs.isLoading} error={agr.error} isEmpty={!agr.data?.series.length}
          table={{ columns: [t('chart.date'), '%'], rows: (agr.data?.series ?? []).map((s) => [s.t, s.value]) }}>
          <TimeSeriesChart data={(agr.data?.series ?? []).map((s) => ({ t: s.t, value: s.value }))} series={[{ key: 'value', label: '%' }]} unit="%" />
        </ChartCard>
        <ChartCard title={t('chart.final_class')} isLoading={cls.isLoading} error={cls.error} isEmpty={!cls.data?.items.length}
          table={{ columns: [t('chart.class'), t('chart.count')], rows: (cls.data?.items ?? []).map((i) => [label(i.key), i.count]) }}>
          <BarsChart horizontal data={(cls.data?.items ?? []).map((i) => ({ name: label(i.key), count: i.count }))} series={[{ key: 'count', label: t('chart.count') }]} />
        </ChartCard>
        <ChartCard title={t('chart.age_groups')} isLoading={age.isLoading} error={age.error} isEmpty={!age.data?.items.length}
          table={{ columns: [t('chart.age_group'), t('chart.count')], rows: (age.data?.items ?? []).map((i) => [i.key, i.count]) }}>
          <BarsChart data={(age.data?.items ?? []).map((i) => ({ name: i.key, count: i.count }))} series={[{ key: 'count', label: t('chart.count') }]} />
        </ChartCard>
        <Card className="lg:col-span-2">
          <CardHeader title={t('dashboard.followups')} />
          <div className="p-5">
            {fu.isLoading ? <Skeleton className="h-16" /> : fu.isError ? <ErrorState compact error={fu.error} onRetry={() => void fu.refetch()} /> : (fu.data?.items.length ?? 0) === 0 ? <p className="text-sm text-muted">{t('common:state.empty')}</p> : (
              <ul className="divide-y divide-border text-sm">{fu.data!.items.slice(0, 6).map((f) => <li key={f.exam_id} className="flex items-center justify-between gap-2 py-2"><span>{f.patient.full_name} <span className="text-xs text-muted">{f.exam_no}</span></span><Badge tone="info" icon={false}>{formatDate(f.follow_up_date)}</Badge></li>)}</ul>
            )}
          </div>
        </Card>
      </section>
    </div>
  );
}
