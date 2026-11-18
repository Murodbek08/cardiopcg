import { useMemo, useState } from 'react';
import { z } from 'zod';
import { Link, useNavigate } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import type { ColumnDef } from '@tanstack/react-table';
import { IconPlus, IconUsersGroup, IconAlertTriangle } from '@tabler/icons-react';
import { ALL, Badge, Button, DataTable, EmptyState, Field, Input, PageHeader, Select, formatDate, formatNumber, usePermission } from '@/shared';
import { useSearchInput, useUrlState } from '@/shared/hooks/url-state';
import { optStr } from '@/shared/lib/zod-uz';
import { useAuthStore } from '@/shared/store/auth';
import { maskName, maskPhone } from '@/shared/lib/mask';
import type { PatientListItem } from '@/shared/api/types';
import { usePatients } from '../api';

const schema = z.object({
  q: optStr.catch(undefined),
  gender: z.enum(['male', 'female']).optional().catch(undefined),
  age_min: z.coerce.number().int().min(0).max(120).optional().catch(undefined),
  age_max: z.coerce.number().int().min(0).max(120).optional().catch(undefined),
  allergies: z.enum(['1']).optional().catch(undefined),
  sort: optStr.catch(undefined),
  size: z.coerce.number().int().min(10).max(100).catch(20),
});

export function PatientsListPage() {
  const { t } = useTranslation('patients');
  const navigate = useNavigate();
  const role = useAuthStore((s) => s.user?.role);
  const canCreate = usePermission('patient:write');
  const masked = !usePermission('patient:read_unmasked');
  const [u, setUrl] = useUrlState(schema);
  const [cursors, setCursors] = useState<string[]>([]);
  const reset = (p: Parameters<typeof setUrl>[0]) => { setCursors([]); setUrl(p); };
  const [qInput, setQInput] = useSearchInput(u.q, (q) => reset({ q }));

  const rangeInvalid = u.age_min !== undefined && u.age_max !== undefined && u.age_min > u.age_max;
  const q = usePatients({ q: u.q, gender: u.gender, age_min: u.age_min, age_max: u.age_max, has_allergies: u.allergies ? true : undefined, sort: u.sort, limit: u.size, cursor: cursors.at(-1) });
  const filtered = !!(u.q || u.gender || u.age_min !== undefined || u.age_max !== undefined || u.allergies);

  const columns = useMemo<ColumnDef<PatientListItem>[]>(
    () => [
      { header: 'MRN', cell: (c) => <span className="font-mono-num">{c.row.original.mrn}</span> },
      { header: t('cols.name'), meta: { sortKey: 'last_name' }, cell: (c) => <span className="font-medium">{masked ? maskName(c.row.original.full_name) : c.row.original.full_name}</span> },
      { header: t('cols.age_gender'), meta: { sortKey: 'birth_date' }, cell: (c) => `${c.row.original.age} / ${t(`common:gender.${c.row.original.gender}`)}` },
      { header: t('cols.phone'), meta: { hideBelow: 'lg' }, cell: (c) => (masked ? maskPhone(c.row.original.phone) : c.row.original.phone ?? '-') },
      { header: t('cols.last_exam'), meta: { sortKey: 'last_exam_at', hideBelow: 'md' }, cell: (c) => formatDate(c.row.original.last_exam_at) },
      { header: t('cols.exams'), meta: { hideBelow: 'md' }, cell: (c) => formatNumber(c.row.original.exam_count) },
      { header: t('cols.allergy'), meta: { hideBelow: 'sm' }, cell: (c) => (c.row.original.has_allergies ? <Badge tone="warning" icon={IconAlertTriangle}>{t('allergy')}</Badge> : <span className="text-muted">-</span>) },
    ],
    [t, masked],
  );

  return (
    <div>
      <PageHeader
        title={`${t('title')}${q.data?.page?.total != null ? ` (${formatNumber(q.data.page.total)})` : ''}`}
        description={role === 'admin' ? t('admin_masked') : undefined}
        actions={canCreate ? <Button asChild><Link to="/patients/new"><IconPlus size={18} aria-hidden /> {t('new')}</Link></Button> : undefined}
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <Field label={t('filters.search')} className="lg:col-span-2"><Input type="search" value={qInput} onChange={(e) => setQInput(e.target.value)} placeholder={t('filters.search_placeholder')} /></Field>
        <Field label={t('filters.gender')}>
          <Select value={u.gender ?? ALL} onValueChange={(v) => reset({ gender: v === ALL ? undefined : (v as 'male') })} options={[{ value: ALL, label: t('common:state.all') }, { value: 'male', label: t('common:gender.male') }, { value: 'female', label: t('common:gender.female') }]} />
        </Field>
        <Field label={t('filters.age_min')} error={rangeInvalid ? t('filters.age_range_error') : undefined}>
          <Input type="number" inputMode="numeric" min={0} max={120} value={u.age_min ?? ''} onChange={(e) => reset({ age_min: e.target.value === '' ? undefined : Number(e.target.value) })} />
        </Field>
        <Field label={t('filters.age_max')}>
          <Input type="number" inputMode="numeric" min={0} max={120} value={u.age_max ?? ''} onChange={(e) => reset({ age_max: e.target.value === '' ? undefined : Number(e.target.value) })} />
        </Field>
        <Field label={t('filters.allergy')}>
          <Select value={u.allergies ?? ALL} onValueChange={(v) => reset({ allergies: v === ALL ? undefined : '1' })} options={[{ value: ALL, label: t('common:state.all') }, { value: '1', label: t('allergy') }]} />
        </Field>
      </div>
      {filtered && <div className="mb-3"><Button variant="ghost" size="sm" onClick={() => { setQInput(''); setCursors([]); void navigate({ to: '.', search: {} as never, replace: true }); }}>{t('common:actions.clear_filters')}</Button></div>}
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
          onRowClick={(r) => void navigate({ to: '/patients/$id', params: { id: r.id } } as never)}
          pagination={{ mode: 'cursor', hasNext: !!q.data?.page?.next_cursor, hasPrev: cursors.length > 0, onNext: () => { const c = q.data?.page?.next_cursor; if (c) setCursors((s) => [...s, c]); }, onPrev: () => setCursors((s) => s.slice(0, -1)), total: q.data?.page?.total ?? null, pageSize: u.size, onPageSizeChange: (size) => reset({ size }) }}
          emptyState={
            <EmptyState icon={IconUsersGroup} title={filtered ? t('empty_filtered') : t('empty')}
              action={filtered ? <Button variant="outline" onClick={() => { setQInput(''); setCursors([]); void navigate({ to: '.', search: {} as never, replace: true }); }}>{t('common:actions.clear_filters')}</Button> : canCreate ? <Button asChild><Link to="/patients/new">{t('new')}</Link></Button> : undefined} />
          }
          renderCard={(r) => (
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0"><p className="truncate font-medium">{masked ? maskName(r.full_name) : r.full_name}</p><p className="text-xs text-muted">{r.mrn} &middot; {r.age} / {t(`common:gender.${r.gender}`)}</p></div>
              {r.has_allergies && <Badge tone="warning" icon={IconAlertTriangle}>{t('allergy')}</Badge>}
            </div>
          )}
          caption={t('title')}
        />
      </div>
    </div>
  );
}
