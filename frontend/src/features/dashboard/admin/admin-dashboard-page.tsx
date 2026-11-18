import { useMemo } from 'react';
import { z } from 'zod';
import { Link, useNavigate } from '@tanstack/react-router';
import { useIsFetching, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  IconStethoscope, IconUsers, IconClockBolt, IconAlertOctagon, IconBrain, IconListCheck, IconDatabase, IconCoin, IconRefresh, IconDownload,
} from '@tabler/icons-react';
import {
  Alert, Badge, Button, Card, CardHeader, ChartCard, DonutChart, BarsChart, Heatmap, KpiCard, PageHeader, PercentGauge, PeriodPicker, Skeleton, ErrorState,
  StatusBadge, TimeSeriesChart, formatDateTime, formatNumber, resolvePeriod, type Period, type PeriodKey, type HeatCell,
} from '@/shared';
import { useUrlState } from '@/shared/hooks/url-state';
import { validateRange } from '@/shared/ui/period-picker';
import {
  useAiPerformance, useDistribution, useHealthDeep, useHeatmap, useKpis, useRecentAudit, useSystemAnalytics, useTimeseries, useWorkload,
} from './api';

const schema = z.object({
  range: z.enum(['today', '7d', '30d', '90d', 'custom']).catch('30d'),
  from: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().catch(undefined),
  to: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).optional().catch(undefined),
});

const WEEKDAYS = ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh', 'Ya'];
const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'));

function useTranslatedLabel() {
  const { t } = useTranslation('clinical');
  return (dim: string, key: string) => {
    if (dim === 'pcg_class') return t(`pcg_class.${key}`, { defaultValue: key });
    if (dim === 'severity') return t(`severity.${key}`, { defaultValue: key });
    return key;
  };
}

export function AdminDashboardPage() {
  const { t } = useTranslation('dashboard');
  const [url, setUrl] = useUrlState(schema);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const fetching = useIsFetching({ queryKey: ['analytics'] });

  const period: Period = useMemo(() => {
    const p = resolvePeriod(url.range as PeriodKey, { from: url.from, to: url.to });
    return url.range === 'custom' && !validateRange(p.from, p.to) ? resolvePeriod('30d') : p;
  }, [url.range, url.from, url.to]);
  const r = useMemo(() => ({ from: period.from, to: period.to }), [period.from, period.to]);

  const kpis = useKpis(r);
  const k = kpis.data?.kpis;
  const health = useHealthDeep();
  const workload = useWorkload(r);
  const system = useSystemAnalytics(r);
  const tsExams = useTimeseries(r, 'examinations');
  const tsDone = useTimeseries(r, 'completed');
  const pcg = useDistribution(r, 'pcg_class');
  const severity = useDistribution(r, 'severity');
  const age = useDistribution(r, 'age_group');
  const heat = useHeatmap(r);
  const ai = useAiPerformance(r);
  const audit = useRecentAudit();
  const label = useTranslatedLabel();

  const timeData = useMemo(() => {
    const map = new Map<string, Record<string, string | number | null>>();
    for (const p of tsExams.data?.series ?? []) map.set(p.t, { t: p.t, examinations: p.value, completed: 0 });
    for (const p of tsDone.data?.series ?? []) map.set(p.t, { ...(map.get(p.t) ?? { t: p.t, examinations: 0 }), completed: p.value });
    return [...map.values()].sort((a, b) => String(a.t).localeCompare(String(b.t)));
  }, [tsExams.data, tsDone.data]);

  const heatCells: HeatCell[] = useMemo(() => {
    const items = heat.data?.items ?? [];
    const zeroBased = items.some((i) => i.dow === 0);
    return items.map((i) => ({ x: i.hour, y: zeroBased ? (i.dow + 6) % 7 : i.dow - 1, value: i.value }));
  }, [heat.data]);

  const latestAi = ai.data?.model_versions?.[0];
  const dsState = health.data?.checks?.deepseek_key;
  const dsOk = dsState === 'configured';
  const queueTotal = workload.data ? workload.data.queue.queued + workload.data.queue.processing + workload.data.queue.ai_ready + workload.data.queue.in_review : null;
  const recentErrors = system.data?.recent_errors ?? [];

  const exportKpis = () => {
    if (!k) return;
    const rows = Object.entries(k).map(([key, v]) => `${key},${v.value ?? ''},${v.delta_pct ?? ''}`);
    const blob = new Blob(['\uFEFFkpi,value,delta_pct\n' + rows.join('\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `kpis_${period.from}_${period.to}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const kv = (key: string) => k?.[key];

  return (
    <div>
      <PageHeader
        title={t('admin.title')}
        actions={
          <>
            <PeriodPicker value={period} onChange={(p) => setUrl({ range: p.key, from: p.key === 'custom' ? p.from : undefined, to: p.key === 'custom' ? p.to : undefined })} />
            <Button variant="outline" onClick={() => void qc.invalidateQueries({ queryKey: ['analytics'] })} loading={fetching > 0}>
              <IconRefresh size={18} aria-hidden /> {t('common:actions.refresh')}
            </Button>
            <Button variant="outline" onClick={exportKpis} disabled={!k}>
              <IconDownload size={18} aria-hidden /> {t('common:actions.export')}
            </Button>
          </>
        }
      />

      <section aria-label="KPI" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label={t('kpi.examinations_total')} icon={IconStethoscope} value={formatNumber(kv('examinations_total')?.value)} deltaPct={kv('examinations_total')?.delta_pct} isLoading={kpis.isLoading} error={kpis.error} onRetry={() => void kpis.refetch()} onClick={() => void navigate({ to: '/exams' })} />
        <KpiCard label={t('kpi.active_users')} icon={IconUsers} value={formatNumber(kv('active_users')?.value)} deltaPct={kv('active_users')?.delta_pct} isLoading={kpis.isLoading} error={kpis.error} onClick={() => void navigate({ to: '/admin/users' })} />
        <KpiCard label={t('kpi.avg_ai_processing_sec')} icon={IconClockBolt} value={formatNumber(kv('avg_ai_processing_sec')?.value, 1)} unit="s" deltaPct={kv('avg_ai_processing_sec')?.delta_pct} invertDelta isLoading={kpis.isLoading} error={kpis.error} />
        <KpiCard label={t('kpi.failed_analyses')} icon={IconAlertOctagon} value={formatNumber(kv('failed_analyses')?.value)} deltaPct={kv('failed_analyses')?.delta_pct} invertDelta isLoading={kpis.isLoading} error={kpis.error} onClick={() => void navigate({ to: '/exams', search: { status: 'failed' } as never })} />
        <KpiCard
          label={t('kpi.deepseek')}
          icon={IconBrain}
          isLoading={health.isLoading}
          error={undefined}
          value={
            health.isError ? (
              <StatusBadge kind="job" value="failed" />
            ) : (
              <Badge tone={dsOk ? 'success' : dsState ? 'danger' : 'neutral'}>{dsState ? (dsOk ? t('health.up') : t('health.down')) : t('health.unknown')}</Badge>
            )
          }
          hint={health.data?.status === 'degraded' ? t('health.degraded') : undefined}
          onClick={() => void navigate({ to: '/admin/settings' })}
        />
        <KpiCard label={t('kpi.queue')} icon={IconListCheck} value={formatNumber(queueTotal)} isLoading={workload.isLoading} error={workload.error} onRetry={() => void workload.refetch()} hint={workload.data?.queue.oldest_pending_min ? t('kpi.oldest', { min: workload.data.queue.oldest_pending_min }) : undefined} />
        <KpiCard label={t('kpi.storage')} icon={IconDatabase} value={formatNumber(kv('storage_used_gb')?.value, 1)} unit="GB" isLoading={kpis.isLoading} error={kpis.error} />
        <KpiCard label={t('kpi.llm_cost')} icon={IconCoin} value={formatNumber(kv('llm_cost_usd')?.value, 2)} unit="USD" deltaPct={kv('llm_cost_usd')?.delta_pct} invertDelta isLoading={kpis.isLoading} error={kpis.error} />
      </section>

      {health.isError && (
        <Alert tone="warning" className="mt-4" title={t('health.unavailable')}>
          {t('health.unavailable_body')}
        </Alert>
      )}

      <section className="mt-6 grid gap-4 lg:grid-cols-2">
        <ChartCard
          title={t('chart.exams_timeseries')}
          caption={`${period.from} - ${period.to}`}
          isLoading={tsExams.isLoading || tsDone.isLoading}
          error={tsExams.error ?? tsDone.error}
          onRetry={() => { void tsExams.refetch(); void tsDone.refetch(); }}
          isEmpty={!timeData.length}
          table={{ columns: [t('chart.date'), t('chart.examinations'), t('chart.completed')], rows: timeData.map((d) => [d.t as string, d.examinations as number, d.completed as number]) }}
          exportName="exams-timeseries"
        >
          <TimeSeriesChart data={timeData} series={[{ key: 'examinations', label: t('chart.examinations') }, { key: 'completed', label: t('chart.completed') }]} />
        </ChartCard>

        <ChartCard
          title={t('chart.pcg_distribution')}
          isLoading={pcg.isLoading}
          error={pcg.error}
          onRetry={() => void pcg.refetch()}
          isEmpty={!pcg.data?.items.length}
          table={{ columns: [t('chart.class'), t('chart.count'), '%'], rows: (pcg.data?.items ?? []).map((i) => [label('pcg_class', i.key), i.count, i.pct]) }}
          exportName="pcg-distribution"
        >
          <DonutChart data={(pcg.data?.items ?? []).map((i) => ({ name: label('pcg_class', i.key), value: i.count }))} centerLabel={t('common:state.total')} />
        </ChartCard>

        <ChartCard
          title={t('chart.agreement')}
          info={t('chart.agreement_info')}
          isLoading={ai.isLoading}
          error={ai.error}
          onRetry={() => void ai.refetch()}
          isEmpty={!latestAi}
          table={{ columns: [t('chart.model'), 'n', t('chart.agree'), t('chart.partial'), t('chart.disagree')], rows: (ai.data?.model_versions ?? []).map((m) => [m.version, m.n, m.agreement_pct, m.partial_pct, m.disagree_pct]) }}
          exportName="ai-agreement"
        >
          <PercentGauge value={latestAi?.agreement_pct} n={latestAi?.n} label={t('chart.agree')} />
        </ChartCard>

        <ChartCard
          title={t('chart.age_groups')}
          isLoading={age.isLoading}
          error={age.error}
          onRetry={() => void age.refetch()}
          isEmpty={!age.data?.items.length}
          table={{ columns: [t('chart.age_group'), t('chart.count'), '%'], rows: (age.data?.items ?? []).map((i) => [i.key, i.count, i.pct]) }}
          exportName="age-groups"
        >
          <BarsChart data={(age.data?.items ?? []).map((i) => ({ name: i.key, count: i.count }))} series={[{ key: 'count', label: t('chart.count') }]} />
        </ChartCard>

        <ChartCard
          title={t('chart.activity_heatmap')}
          isLoading={heat.isLoading}
          error={heat.error}
          onRetry={() => void heat.refetch()}
          isEmpty={!heatCells.length}
          table={{ columns: [t('chart.weekday'), t('chart.hour'), t('chart.count')], rows: heatCells.map((c) => [WEEKDAYS[c.y] ?? c.y, HOURS[c.x] ?? c.x, c.value]) }}
          exportName="activity-heatmap"
          height={300}
        >
          <Heatmap cells={heatCells} xLabels={HOURS} yLabels={WEEKDAYS} valueLabel={t('chart.examinations')} />
        </ChartCard>

        <ChartCard
          title={t('chart.workload')}
          isLoading={workload.isLoading}
          error={workload.error}
          onRetry={() => void workload.refetch()}
          isEmpty={!workload.data?.doctors.length}
          table={{ columns: [t('chart.doctor'), t('chart.assigned'), t('chart.completed'), t('chart.pending')], rows: (workload.data?.doctors ?? []).map((d) => [d.full_name, d.assigned, d.completed, d.pending]) }}
          exportName="doctor-workload"
          height={300}
        >
          <BarsChart horizontal data={(workload.data?.doctors ?? []).map((d) => ({ name: d.full_name, assigned: d.assigned, completed: d.completed }))} series={[{ key: 'assigned', label: t('chart.assigned') }, { key: 'completed', label: t('chart.completed') }]} />
        </ChartCard>

        <ChartCard
          title={t('chart.severity')}
          isLoading={severity.isLoading}
          error={severity.error}
          onRetry={() => void severity.refetch()}
          isEmpty={!severity.data?.items.length}
          table={{ columns: [t('chart.severity'), t('chart.count'), '%'], rows: (severity.data?.items ?? []).map((i) => [label('severity', i.key), i.count, i.pct]) }}
          exportName="severity"
        >
          <DonutChart data={(severity.data?.items ?? []).map((i) => ({ name: label('severity', i.key), value: i.count }))} centerLabel={t('common:state.total')} />
        </ChartCard>

        <Card>
          <CardHeader title={t('recent.errors')} />
          <div className="p-5">
            {system.isLoading ? (
              <Skeleton className="h-24" />
            ) : system.isError ? (
              <ErrorState compact error={system.error} onRetry={() => void system.refetch()} />
            ) : recentErrors.length === 0 ? (
              <p className="text-sm text-muted">{t('recent.no_errors')}</p>
            ) : (
              <ul className="space-y-2 text-sm">
                {recentErrors.slice(0, 5).map((e, i) => (
                  <li key={i} className="flex items-start justify-between gap-3">
                    <span className="min-w-0"><Badge tone="danger">{e.source}</Badge> <span className="break-words">{e.message}</span></span>
                    <span className="shrink-0 text-xs text-muted">{formatDateTime(e.ts)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title={t('recent.audit')} actions={<Link to="/admin/audit" className="text-sm text-brand-600 hover:underline dark:text-brand-300">{t('common:actions.show_more')}</Link>} />
          <div className="p-5">
            {audit.isLoading ? (
              <Skeleton className="h-24" />
            ) : audit.isError ? (
              <ErrorState compact error={audit.error} onRetry={() => void audit.refetch()} />
            ) : !audit.data?.items.length ? (
              <p className="text-sm text-muted">{t('common:state.empty')}</p>
            ) : (
              <ul className="divide-y divide-border text-sm">
                {audit.data.items.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                    <span className="flex items-center gap-2">
                      <Badge tone={a.success ? 'neutral' : 'danger'} icon={false}>{a.action}</Badge>
                      <span className="text-muted">{a.user?.username ?? 'system'}</span>
                      <span className="font-mono-num text-xs text-muted">{a.resource_type ?? ''}</span>
                    </span>
                    <span className="text-xs text-muted">{formatDateTime(a.ts)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      </section>
    </div>
  );
}
