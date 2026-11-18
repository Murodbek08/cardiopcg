import { useMemo, useState } from 'react';
import { z } from 'zod';
import { useTranslation } from 'react-i18next';
import type { ColumnDef } from '@tanstack/react-table';
import { IconDownload, IconShieldLock, IconAlertTriangle } from '@tabler/icons-react';
import { ALL, Alert, Badge, Button, DataTable, EmptyState, Field, Input, PageHeader, Select, Sheet, downloadFile, formatDateTime, toast, errorMessage, today, daysAgo, cleanParams } from '@/shared';
import { useSearchInput, useUrlState } from '@/shared/hooks/url-state';
import { optStr } from '@/shared/lib/zod-uz';
import type { AuditLogItem } from '@/shared/api/types';
import { AUDIT_ACTIONS, AUDIT_GROUPS, auditRangeOk, useAudit } from '../api';
import { JsonDiffViewer } from '../components/json-diff';

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const schema = z.object({
  from: isoDate.optional().catch(undefined),
  to: isoDate.optional().catch(undefined),
  action: optStr.catch(undefined),
  result: z.enum(['true', 'false']).optional().catch(undefined),
  resource: optStr.catch(undefined),
  q: optStr.catch(undefined),
  size: z.coerce.number().int().min(10).max(200).catch(50),
});

export function AuditPage() {
  const { t } = useTranslation('admin');
  const [u, setUrl] = useUrlState(schema);
  const [cursors, setCursors] = useState<string[]>([]);
  const [selected, setSelected] = useState<AuditLogItem | null>(null);
  const [qInput, setQInput] = useSearchInput(u.q, (q) => { setCursors([]); setUrl({ q }); });

  const from = u.from ?? daysAgo(6);
  const to = u.to ?? today();
  const rangeOk = auditRangeOk(from, to);
  const filter = { from, to, action: u.action, success: u.result, resource_type: u.resource, q: u.q, limit: u.size, cursor: cursors.at(-1) };
  const q = useAudit(filter);
  const rows = useMemo(() => q.data?.items ?? [], [q.data]);

  const suspicious = useMemo(() => {
    const failed = rows.filter((r) => r.action === 'login_failed').length;
    const reuse = rows.some((r) => r.action === 'token_reuse_detected');
    const denied = rows.filter((r) => r.action === 'permission_denied').length;
    return failed >= 5 || reuse || denied >= 5 ? { failed, reuse, denied } : null;
  }, [rows]);

  const reset = (patch: Parameters<typeof setUrl>[0]) => { setCursors([]); setUrl(patch); };

  const columns = useMemo<ColumnDef<AuditLogItem>[]>(
    () => [
      { header: t('audit.cols.time'), cell: (c) => <span className="whitespace-nowrap font-mono-num text-xs">{formatDateTime(c.row.original.ts)}</span> },
      { header: t('audit.cols.user'), cell: (c) => c.row.original.user?.username ?? <span className="text-muted">system</span> },
      { header: t('audit.cols.action'), cell: (c) => <Badge tone={c.row.original.success ? 'neutral' : 'danger'} icon={false}>{c.row.original.action}</Badge> },
      { header: t('audit.cols.resource'), meta: { hideBelow: 'md' }, cell: (c) => <span className="font-mono-num text-xs">{c.row.original.resource_type ?? '-'}{c.row.original.resource_id ? `:${c.row.original.resource_id.slice(0, 8)}` : ''}</span> },
      { header: t('audit.cols.result'), cell: (c) => <Badge tone={c.row.original.success ? 'success' : 'danger'}>{c.row.original.status_code ?? (c.row.original.success ? 'OK' : 'ERR')}</Badge> },
      { header: 'IP', meta: { hideBelow: 'lg' }, cell: (c) => <span className="font-mono-num text-xs">{c.row.original.ip ?? '-'}</span> },
    ],
    [t],
  );

  const exportCsv = async () => {
    try {
      await downloadFile('/audit-logs/export', cleanParams({ format: 'csv', ...filter, cursor: undefined, limit: undefined, from: `${from}T00:00:00Z`, to: `${to}T23:59:59Z` }), `audit_${from}_${to}.csv`);
    } catch (e) {
      toast.error(errorMessage(e, t as never));
    }
  };

  return (
    <div>
      <PageHeader title={t('audit.title')} description={t('audit.append_only')} actions={<Button variant="outline" onClick={() => void exportCsv()} disabled={!rangeOk}><IconDownload size={18} aria-hidden /> {t('audit.export')}</Button>} />

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <Field label={t('audit.filters.from')}><Input type="date" value={from} max={to} onChange={(e) => reset({ from: e.target.value })} /></Field>
        <Field label={t('audit.filters.to')} error={!rangeOk ? t('audit.range_error') : undefined}><Input type="date" value={to} min={from} max={today()} onChange={(e) => reset({ to: e.target.value })} /></Field>
        <Field label={t('audit.filters.action')}>
          <Select value={u.action ?? ALL} onValueChange={(v) => reset({ action: v === ALL ? undefined : v })}
            options={[{ value: ALL, label: t('common:state.all') }, ...Object.entries(AUDIT_GROUPS).flatMap(([g, list]) => list.filter((a) => (AUDIT_ACTIONS as readonly string[]).includes(a)).map((a) => ({ value: a, label: `${t(`audit.groups.${g}`)}: ${a}` })))]} />
        </Field>
        <Field label={t('audit.filters.result')}>
          <Select value={u.result ?? ALL} onValueChange={(v) => reset({ result: v === ALL ? undefined : (v as 'true') })}
            options={[{ value: ALL, label: t('common:state.all') }, { value: 'true', label: t('audit.ok') }, { value: 'false', label: t('audit.failed') }]} />
        </Field>
        <Field label={t('audit.filters.resource')}><Input value={u.resource ?? ''} onChange={(e) => reset({ resource: e.target.value || undefined })} placeholder="patient, examination" /></Field>
        <Field label={t('audit.filters.search')}><Input type="search" value={qInput} onChange={(e) => setQInput(e.target.value)} placeholder="/api/v1/..." /></Field>
      </div>

      {suspicious && (
        <Alert tone="warning" className="mb-4" title={t('audit.suspicious')}>
          <span className="inline-flex items-center gap-1"><IconAlertTriangle size={14} aria-hidden /> {t('audit.suspicious_body', suspicious)}</span>
        </Alert>
      )}

      <div className="overflow-hidden rounded-lg border border-border bg-surface shadow-card">
        <DataTable
          columns={columns}
          data={rows}
          getRowId={(r) => String(r.id)}
          isLoading={q.isLoading}
          isFetching={q.isFetching}
          error={q.error}
          onRetry={() => void q.refetch()}
          onRowClick={setSelected}
          pagination={{
            mode: 'cursor',
            hasNext: !!q.data?.page?.next_cursor,
            hasPrev: cursors.length > 0,
            onNext: () => { const c = q.data?.page?.next_cursor; if (c) setCursors((s) => [...s, c]); },
            onPrev: () => setCursors((s) => s.slice(0, -1)),
            pageSize: u.size,
            onPageSizeChange: (size) => reset({ size }),
            total: q.data?.page?.total ?? null,
          }}
          emptyState={<EmptyState icon={IconShieldLock} title={t('audit.empty')} />}
          caption={t('audit.title')}
        />
      </div>

      <Sheet open={!!selected} onOpenChange={(o) => !o && setSelected(null)} title={selected ? `${selected.action} #${selected.id}` : ''} description={selected ? formatDateTime(selected.ts) : undefined} width="max-w-2xl">
        {selected && (
          <div className="space-y-5 text-sm">
            <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-2">
              {([
                ['audit.cols.user', selected.user ? `${selected.user.username} (${selected.user.role})` : 'system'],
                ['audit.detail.request_id', selected.request_id],
                ['audit.detail.method', selected.method && selected.path ? `${selected.method} ${selected.path}` : null],
                ['audit.detail.status', selected.status_code],
                ['IP', selected.ip],
                ['audit.detail.user_agent', selected.user_agent],
                ['audit.cols.resource', selected.resource_type ? `${selected.resource_type}${selected.resource_id ? `:${selected.resource_id}` : ''}` : null],
              ] as [string, string | number | null | undefined][]).map(([k, v]) => v !== null && v !== undefined && v !== '' && (
                <div key={k} className="contents">
                  <dt className="text-muted">{k.includes('.') ? t(k) : k}</dt>
                  <dd className="break-all font-mono text-xs">{v}</dd>
                </div>
              ))}
            </dl>
            {selected.meta && Object.keys(selected.meta).length > 0 && (
              <div>
                <h3 className="mb-1.5 font-semibold">{selected.action === 'ai_call' ? t('audit.detail.ai') : t('audit.detail.meta')}</h3>
                <pre className="overflow-x-auto rounded-md bg-surface-2 p-3 text-xs">{JSON.stringify(selected.meta, null, 2)}</pre>
              </div>
            )}
            {selected.changes && (
              <div>
                <h3 className="mb-1.5 font-semibold">{t('audit.detail.changes')}</h3>
                <JsonDiffViewer before={selected.changes.before} after={selected.changes.after} />
              </div>
            )}
          </div>
        )}
      </Sheet>
    </div>
  );
}
