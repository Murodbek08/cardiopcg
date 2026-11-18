import { useMemo } from 'react';
import { z } from 'zod';
import { Link, useNavigate } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import type { ColumnDef } from '@tanstack/react-table';
import { IconPlus, IconUsers } from '@tabler/icons-react';
import { ALL, Button, DataTable, EmptyState, Input, PageHeader, Select, StatusBadge, formatDateTime } from '@/shared';
import { useSearchInput, useUrlState } from '@/shared/hooks/url-state';
import { optStr } from '@/shared/lib/zod-uz';
import type { UserListItem } from '@/shared/api/types';
import { useUsers } from '../api';

const schema = z.object({
  role: z.enum(['admin', 'doctor', 'nurse']).optional().catch(undefined),
  status: z.enum(['active', 'suspended', 'pending']).optional().catch(undefined),
  q: optStr.catch(undefined),
  sort: optStr.catch(undefined),
  page: z.coerce.number().int().min(1).catch(1),
  size: z.coerce.number().int().min(5).max(100).catch(20),
});

export function UsersListPage() {
  const { t } = useTranslation('admin');
  const navigate = useNavigate();
  const [u, setUrl] = useUrlState(schema);
  const [qInput, setQInput] = useSearchInput(u.q, (q) => setUrl({ q }, { resetPage: true }));

  const q = useUsers({ role: u.role, status: u.status, q: u.q, sort: u.sort, page: u.page, page_size: u.size });

  const columns = useMemo<ColumnDef<UserListItem>[]>(
    () => [
      { header: t('users.fields.username'), accessorKey: 'username', meta: { sortKey: 'username' }, cell: (c) => <span className="font-mono-num font-medium">{c.row.original.username}</span> },
      { header: t('users.fields.full_name'), accessorKey: 'full_name', meta: { sortKey: 'full_name' } },
      { header: t('users.fields.role'), accessorKey: 'role', cell: (c) => t(`common:role.${c.row.original.role}`) },
      { header: t('users.fields.specialty'), accessorKey: 'specialty', meta: { hideBelow: 'lg' }, cell: (c) => c.row.original.specialty ?? c.row.original.department ?? '-' },
      { header: t('users.fields.status'), accessorKey: 'status', cell: (c) => <StatusBadge kind="user" value={c.row.original.status} /> },
      { header: t('users.fields.last_login'), accessorKey: 'last_login_at', meta: { sortKey: 'last_login_at', hideBelow: 'md' }, cell: (c) => formatDateTime(c.row.original.last_login_at) },
    ],
    [t],
  );

  return (
    <div>
      <PageHeader
        title={t('users.title')}
        actions={
          <Button asChild>
            <Link to="/admin/users/new">
              <IconPlus size={18} aria-hidden /> {t('users.new')}
            </Link>
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="w-full sm:w-64">
          <Input type="search" placeholder={t('users.search')} aria-label={t('users.search')} value={qInput} onChange={(e) => setQInput(e.target.value)} />
        </div>
        <div className="w-44">
          <Select aria-label={t('users.fields.role')} value={u.role ?? ALL} onValueChange={(v) => setUrl({ role: v === ALL ? undefined : (v as 'admin') }, { resetPage: true })}
            options={[{ value: ALL, label: `${t('users.fields.role')}: ${t('common:state.all')}` }, ...(['admin', 'doctor', 'nurse'] as const).map((r) => ({ value: r, label: t(`common:role.${r}`) }))]} />
        </div>
        <div className="w-44">
          <Select aria-label={t('users.fields.status')} value={u.status ?? ALL} onValueChange={(v) => setUrl({ status: v === ALL ? undefined : (v as 'active') }, { resetPage: true })}
            options={[{ value: ALL, label: `${t('users.fields.status')}: ${t('common:state.all')}` }, ...(['active', 'suspended', 'pending'] as const).map((s) => ({ value: s, label: t(`users.status.${s}`) }))]} />
        </div>
        {(u.role || u.status || u.q) && (
          <Button variant="ghost" onClick={() => { setQInput(''); setUrl({ role: undefined, status: undefined, q: undefined }, { resetPage: true }); }}>
            {t('common:actions.clear_filters')}
          </Button>
        )}
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
          onSortChange={(sort) => setUrl({ sort }, { resetPage: true })}
          onRowClick={(r) => void navigate({ to: '/admin/users/$id', params: { id: r.id } } as never)}
          pagination={{ mode: 'offset', page: u.page, pageSize: u.size, total: q.data?.total ?? null, onPageChange: (page) => setUrl({ page }), onPageSizeChange: (size) => setUrl({ size }, { resetPage: true }) }}
          emptyState={<EmptyState icon={IconUsers} title={u.role || u.status || u.q ? t('users.empty_filtered') : t('users.empty')} action={<Button asChild><Link to="/admin/users/new">{t('users.new')}</Link></Button>} />}
          renderCard={(r) => (
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate font-medium">{r.full_name}</p>
                <p className="text-xs text-muted">{r.username} - {t(`common:role.${r.role}`)}</p>
              </div>
              <StatusBadge kind="user" value={r.status} />
            </div>
          )}
          caption={t('users.title')}
        />
      </div>
    </div>
  );
}
