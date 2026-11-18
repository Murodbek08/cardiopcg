import { useMemo, useState } from 'react';
import { z } from 'zod';
import { useNavigate } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import type { ColumnDef } from '@tanstack/react-table';
import { IconStethoscope } from '@tabler/icons-react';
import { DataTable, EmptyState, Field, Input, PageHeader, StatusBadge, Tabs, TabsList, TabsTrigger, formatDateTime, formatNumber, formatPercent, usePermission } from '@/shared';
import { useSearchInput, useUrlState } from '@/shared/hooks/url-state';
import { optStr } from '@/shared/lib/zod-uz';
import { maskName } from '@/shared/lib/mask';
import type { ExamListItem } from '@/shared/api/types';
import { STATUS_TABS, useExams, type StatusTab } from '../api';

const schema = z.object({
  tab: z.enum(['all', 'uploaded', 'analyzing', 'review', 'completed', 'failed']).catch('all'),
  q: optStr.catch(undefined),
  patient: optStr.catch(undefined),
  sort: optStr.catch(undefined),
  size: z.coerce.number().int().min(10).max(100).catch(20),
});

export function ExamsListPage() {
  const { t } = useTranslation('exams');
  const navigate = useNavigate();
  const masked = !usePermission('patient:read_unmasked');
  const [u, setUrl] = useUrlState(schema);
  const [cursors, setCursors] = useState<string[]>([]);
  const reset = (p: Parameters<typeof setUrl>[0]) => { setCursors([]); setUrl(p); };
  const [qInput, setQInput] = useSearchInput(u.q, (q) => reset({ q }));
  const q = useExams({ status: STATUS_TABS[u.tab as StatusTab], q: u.q, patient_id: u.patient, sort: u.sort, limit: u.size, cursor: cursors.at(-1) });

  const columns = useMemo<ColumnDef<ExamListItem>[]>(
    () => [
      { header: t('columns.exam_no'), meta: { sortKey: 'created_at' }, cell: (c) => <span className="font-mono-num">{c.row.original.exam_no}</span> },
      { header: t('columns.patient'), cell: (c) => <span>{masked ? maskName(c.row.original.patient.full_name) : c.row.original.patient.full_name}<span className="ml-2 text-xs text-muted">{c.row.original.patient.mrn}</span></span> },
      { header: t('columns.date'), meta: { sortKey: 'examined_at', hideBelow: 'md' }, cell: (c) => formatDateTime(c.row.original.examined_at) },
      { header: t('columns.created_by'), meta: { hideBelow: 'lg' }, cell: (c) => c.row.original.performed_by.full_name },
      { header: t('columns.status'), meta: { sortKey: 'status' }, cell: (c) => <StatusBadge kind="exam" value={c.row.original.status} /> },
      { header: t('columns.ai'), meta: { hideBelow: 'md', sortKey: 'severity' }, cell: (c) => c.row.original.ai ? <span className="inline-flex items-center gap-2"><StatusBadge kind="pcg" value={c.row.original.ai.pcg_class} /><span className="text-xs text-muted">{formatPercent(c.row.original.ai.confidence * 100, 0)}</span></span> : <span className="text-muted">-</span> },
      { header: t('columns.recordings'), meta: { hideBelow: 'lg' }, cell: (c) => formatNumber(c.row.original.recording_count) },
    ],
    [t, masked],
  );

  return (
    <div>
      <PageHeader title={`${t('title')}${q.data?.page?.total != null ? ` (${formatNumber(q.data.page.total)})` : ''}`} description={masked ? t('readonly_admin') : undefined} />
      <Tabs value={u.tab} onValueChange={(v) => reset({ tab: v as StatusTab })}>
        <TabsList>
          {(Object.keys(STATUS_TABS) as StatusTab[]).map((k) => <TabsTrigger key={k} value={k}>{t(`tabs.${k}`)}</TabsTrigger>)}
        </TabsList>
      </Tabs>
      <div className="my-4 max-w-sm">
        <Field label={t('search_placeholder')}><Input type="search" value={qInput} onChange={(e) => setQInput(e.target.value)} /></Field>
      </div>
      <div className="overflow-hidden rounded-lg border border-border bg-surface shadow-card">
        <DataTable
          columns={columns}
          data={q.data?.items ?? []}
          getRowId={(r) => r.id}
          isLoading={q.isLoading}
          isFetching={q.isFetching}
          error={q.error}
          onRetry={() => void q.refetch()}
          sort={u.sort}
          onSortChange={(sort) => reset({ sort })}
          onRowClick={(r) => void navigate({ to: '/exams/$id', params: { id: r.id } } as never)}
          pagination={{ mode: 'cursor', hasNext: !!q.data?.page?.next_cursor, hasPrev: cursors.length > 0, onNext: () => { const c = q.data?.page?.next_cursor; if (c) setCursors((s) => [...s, c]); }, onPrev: () => setCursors((s) => s.slice(0, -1)), total: q.data?.page?.total ?? null, pageSize: u.size, onPageSizeChange: (size) => reset({ size }) }}
          emptyState={<EmptyState icon={IconStethoscope} title={u.q || u.tab !== 'all' ? t('empty_filtered') : t('empty')} />}
          renderCard={(r) => (
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0"><p className="font-mono-num font-medium">{r.exam_no}</p><p className="truncate text-xs text-muted">{masked ? maskName(r.patient.full_name) : r.patient.full_name}</p></div>
              <StatusBadge kind="exam" value={r.status} />
            </div>
          )}
          caption={t('title')}
        />
      </div>
    </div>
  );
}
