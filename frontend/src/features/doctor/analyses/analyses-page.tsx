import { useMemo, useState } from 'react';
import { z } from 'zod';
import { useNavigate } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import type { ColumnDef } from '@tanstack/react-table';
import { IconBrain } from '@tabler/icons-react';
import { ALL, DataTable, EmptyState, Field, PageHeader, Select, StatusBadge, Tabs, TabsList, TabsTrigger, formatDateTime, formatPercent } from '@/shared';
import { useUrlState } from '@/shared/hooks/url-state';
import type { ExamListItem } from '@/shared/api/types';
import { useExams } from '@/features/exams';

const schema = z.object({
  tab: z.enum(['all', 'pending', 'done']).catch('all'),
  cls: z.enum(['normal', 'murmur', 'extra_heart_sound', 'artifact']).optional().catch(undefined),
  sev: z.enum(['none', 'mild', 'moderate', 'severe', 'critical']).optional().catch(undefined),
});

/** AI analyses list + history: every examination that has an AI result (doctor scope: all, mine toggle by tab). */
export function AnalysesPage() {
  const { t } = useTranslation('doctor');
  const navigate = useNavigate();
  const [u, setUrl] = useUrlState(schema);
  const [cursors, setCursors] = useState<string[]>([]);
  const reset = (p: Parameters<typeof setUrl>[0]) => { setCursors([]); setUrl(p); };
  const status = u.tab === 'pending' ? ['ai_ready', 'in_review'] : u.tab === 'done' ? ['completed'] : ['ai_ready', 'in_review', 'completed'];
  const q = useExams({ status, pcg_class: u.cls, severity: u.sev, sort: '-examined_at', limit: 20, cursor: cursors.at(-1) });

  const columns = useMemo<ColumnDef<ExamListItem>[]>(() => [
    { header: t('analyses.exam'), cell: (c) => <span className="font-mono-num">{c.row.original.exam_no}</span> },
    { header: t('analyses.patient'), cell: (c) => c.row.original.patient.full_name },
    { header: t('analyses.date'), meta: { hideBelow: 'md' }, cell: (c) => formatDateTime(c.row.original.examined_at) },
    { header: t('analyses.class'), cell: (c) => <StatusBadge kind="pcg" value={c.row.original.ai?.pcg_class} /> },
    { header: t('analyses.severity'), cell: (c) => <StatusBadge kind="severity" value={c.row.original.ai?.severity} /> },
    { header: t('analyses.confidence'), meta: { hideBelow: 'md' }, cell: (c) => (c.row.original.ai ? formatPercent(c.row.original.ai.confidence * 100, 0) : '-') },
    { header: t('analyses.status'), cell: (c) => <StatusBadge kind="exam" value={c.row.original.status} /> },
  ], [t]);

  return (
    <div>
      <PageHeader title={t('analyses.title')} description={t('analyses.hint')} />
      <Tabs value={u.tab} onValueChange={(v) => reset({ tab: v as 'all' })}><TabsList>{(['all', 'pending', 'done'] as const).map((k) => <TabsTrigger key={k} value={k}>{t(`analyses.tabs.${k}`)}</TabsTrigger>)}</TabsList></Tabs>
      <div className="my-4 grid max-w-xl gap-3 sm:grid-cols-2">
        <Field label={t('analyses.class')}><Select value={u.cls ?? ALL} onValueChange={(v) => reset({ cls: v === ALL ? undefined : (v as 'normal') })} options={[{ value: ALL, label: t('common:state.all') }, ...(['normal', 'murmur', 'extra_heart_sound', 'artifact'] as const).map((c) => ({ value: c, label: t(`clinical:pcg_class.${c}`) }))]} /></Field>
        <Field label={t('analyses.severity')}><Select value={u.sev ?? ALL} onValueChange={(v) => reset({ sev: v === ALL ? undefined : (v as 'mild') })} options={[{ value: ALL, label: t('common:state.all') }, ...(['none', 'mild', 'moderate', 'severe', 'critical'] as const).map((c) => ({ value: c, label: t(`clinical:severity.${c}`) }))]} /></Field>
      </div>
      <div className="overflow-hidden rounded-lg border border-border bg-surface shadow-card">
        <DataTable columns={columns} data={q.data?.items ?? []} getRowId={(r) => r.id} isLoading={q.isLoading} isFetching={q.isFetching} error={q.error} onRetry={() => void q.refetch()}
          onRowClick={(r) => void navigate({ to: '/exams/$id', params: { id: r.id } } as never)}
          pagination={{ mode: 'cursor', hasNext: !!q.data?.page?.next_cursor, hasPrev: cursors.length > 0, onNext: () => { const c = q.data?.page?.next_cursor; if (c) setCursors((s) => [...s, c]); }, onPrev: () => setCursors((s) => s.slice(0, -1)), total: q.data?.page?.total ?? null }}
          emptyState={<EmptyState icon={IconBrain} title={t('analyses.empty')} />} caption={t('analyses.title')}
          renderCard={(r) => <div className="flex items-center justify-between gap-2"><div><p className="font-mono-num font-medium">{r.exam_no}</p><p className="text-xs text-muted">{r.patient.full_name}</p></div><StatusBadge kind="pcg" value={r.ai?.pcg_class} /></div>} />
      </div>
    </div>
  );
}
