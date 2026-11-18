import { useMemo, useState } from 'react';
import { Link, useNavigate } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { IconAlertTriangle, IconCalendarStats, IconLoader2, IconPlus, IconSearch, IconWaveSine } from '@tabler/icons-react';
import { Button, Card, CardHeader, EmptyState, ErrorState, Input, KpiCard, PageHeader, Skeleton, StatusBadge, formatNumber, formatTime, today } from '@/shared';
import { useExams } from '@/features/exams';
import { useNurseKpis } from '../api';

/** Tablet-first nurse home: big primary action, quick patient search, today's work. No diagnosis/risk numbers here. */
export function NurseDashboardPage() {
  const { t } = useTranslation('nurse');
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const range = useMemo(() => ({ from: today(), to: today() }), []);
  const kpis = useNurseKpis(range);
  const todayExams = useExams({ mine: true, examined_from: today(), sort: '-examined_at', limit: 50 });
  const k = kpis.data;
  const items = todayExams.data?.items ?? [];
  const rerecord = k?.rejected_recordings ?? 0;

  return (
    <div className="space-y-5">
      <PageHeader title={t('title')} />
      <Button asChild size="touch" className="h-18 w-full text-h3">
        <Link to="/exams/new"><IconPlus size={28} aria-hidden /> {t('new_exam')}</Link>
      </Button>
      <form role="search" className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void navigate({ to: '/patients', search: { q: q.trim() || undefined } as never }); }}>
        <Input touch type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('search')} aria-label={t('search')} />
        <Button type="submit" size="touch"><IconSearch size={22} aria-hidden /><span className="sr-only">{t('common:actions.search')}</span></Button>
      </form>

      <section aria-label="KPI" className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <KpiCard label={t('kpi.today')} icon={IconCalendarStats} value={formatNumber(k?.exams_created_today)} isLoading={kpis.isLoading} error={kpis.error} onRetry={() => void kpis.refetch()} />
        <KpiCard label={t('kpi.processing')} icon={IconLoader2} value={formatNumber(k?.awaiting_ai)} isLoading={kpis.isLoading} error={kpis.error} />
        <KpiCard label={t('kpi.rerecord')} icon={IconAlertTriangle} value={formatNumber(rerecord)} invertDelta isLoading={kpis.isLoading} error={kpis.error} onClick={rerecord > 0 ? () => void navigate({ to: '/exams', search: { tab: 'failed' } as never }) : undefined} className={rerecord > 0 ? 'bg-warning-50' : undefined} />
        <KpiCard label={t('kpi.quality')} icon={IconWaveSine} value={k?.avg_recording_quality != null ? formatNumber(k.avg_recording_quality, 2) : '-'} isLoading={kpis.isLoading} error={kpis.error} hint={t('kpi.quality_hint')} />
      </section>

      <Card>
        <CardHeader title={t('today_exams')} />
        <div className="p-5">
          {todayExams.isLoading ? <div className="space-y-2"><Skeleton className="h-16" /><Skeleton className="h-16" /></div> : todayExams.isError ? <ErrorState compact error={todayExams.error} onRetry={() => void todayExams.refetch()} /> : items.length === 0 ? (
            <EmptyState icon={IconCalendarStats} title={t('today_empty')} action={<Button asChild size="touch"><Link to="/exams/new">{t('new_exam')}</Link></Button>} className="py-6" />
          ) : (
            <ul className="space-y-3">
              {items.map((e) => (
                <li key={e.id}>
                  <Link to={e.status === 'processing' || e.status === 'queued' ? '/exams/$id/progress' : '/exams/$id'} params={{ id: e.id }} className="flex min-h-16 items-center justify-between gap-3 rounded-lg border border-border px-4 py-2 hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-ring">
                    <span><span className="font-medium">{e.patient.full_name}</span><br /><span className="text-xs text-muted">{formatTime(e.examined_at)} &middot; {e.exam_no}</span></span>
                    <StatusBadge kind="exam" value={e.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>
    </div>
  );
}
