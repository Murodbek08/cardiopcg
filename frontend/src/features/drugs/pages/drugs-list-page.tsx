import { useMemo, useState } from 'react';
import { z } from 'zod';
import { Link, useNavigate } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import type { ColumnDef } from '@tanstack/react-table';
import { IconPill, IconPlus, IconUpload, IconDownload } from '@tabler/icons-react';
import {
  ALL, Alert, Button, DataTable, Dialog, EmptyState, FileDropzone, Input, PageHeader, Select, StatusBadge, downloadFile, formatDate, toast, errorMessage, formatNumber,
} from '@/shared';
import { useSearchInput, useUrlState } from '@/shared/hooks/url-state';
import { optStr } from '@/shared/lib/zod-uz';
import type { DrugListItem } from '@/shared/api/types';
import { importDrugsCsv, useDrugs, type ImportReport } from '../api';

const schema = z.object({
  q: optStr.catch(undefined),
  group: optStr.catch(undefined),
  status: z.enum(['draft', 'published', 'archived']).optional().catch(undefined),
  page: z.coerce.number().int().min(1).catch(1),
  size: z.coerce.number().int().min(5).max(100).catch(20),
});

function ImportDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useTranslation('drugs');
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (dry: boolean) => {
    if (!file) return;
    setBusy(true);
    try {
      const r = await importDrugsCsv(file, dry);
      setReport(r);
      if (!dry) {
        toast.success(t('import.done', { count: r.valid }));
        onOpenChange(false);
      }
    } catch (e) {
      toast.error(errorMessage(e, t as never));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => { if (!o) { setFile(null); setReport(null); } onOpenChange(o); }}
      title={t('import.title')}
      description={t('import.body')}
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>{t('common:actions.cancel')}</Button>
          <Button variant="outline" disabled={!file} loading={busy} onClick={() => void run(true)}>{t('import.preview')}</Button>
          <Button disabled={!file || !report || report.errors.length > 0 || report.valid === 0} loading={busy} onClick={() => void run(false)}>{t('import.apply')}</Button>
        </>
      }
    >
      <div className="space-y-4">
        <FileDropzone accept={['.csv']} maxSizeBytes={5 * 1024 * 1024} onFiles={(f) => { setFile(f[0] ?? null); setReport(null); }} onReject={() => toast.error(t('common:dropzone.bad_type'))} />
        {file && <p className="text-sm">{file.name}</p>}
        {report && (
          <div className="space-y-2">
            <Alert tone={report.errors.length ? 'warning' : 'success'}>
              {t('import.summary', { total: formatNumber(report.total), valid: formatNumber(report.valid), errors: report.errors.length })}
            </Alert>
            {report.errors.length > 0 && (
              <div className="max-h-56 overflow-auto rounded-md border border-border">
                <table className="w-full text-sm">
                  <thead><tr className="border-b border-border bg-surface-2 text-left text-xs"><th className="px-2 py-1.5">{t('import.row')}</th><th className="px-2 py-1.5">{t('import.error')}</th></tr></thead>
                  <tbody>{report.errors.map((e) => <tr key={e.row} className="border-b border-border last:border-0"><td className="px-2 py-1.5 tabular-nums">{e.row}</td><td className="px-2 py-1.5">{e.message}</td></tr>)}</tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </Dialog>
  );
}

export function DrugsListPage() {
  const { t } = useTranslation('drugs');
  const navigate = useNavigate();
  const [u, setUrl] = useUrlState(schema);
  const [qInput, setQInput] = useSearchInput(u.q, (q) => setUrl({ q }, { resetPage: true }));
  const [importOpen, setImportOpen] = useState(false);
  const q = useDrugs({ q: u.q, group: u.group, status: u.status, page: u.page, page_size: u.size });

  const columns = useMemo<ColumnDef<DrugListItem>[]>(
    () => [
      { header: t('cols.inn'), cell: (c) => <span className="font-medium">{c.row.original.inn}</span> },
      { header: t('cols.trade'), meta: { hideBelow: 'md' }, cell: (c) => c.row.original.trade_names.join(', ') || '-' },
      { header: t('cols.group'), meta: { hideBelow: 'sm' }, cell: (c) => c.row.original.group },
      { header: t('cols.version'), meta: { hideBelow: 'lg' }, cell: (c) => `v${c.row.original.version}` },
      { header: t('cols.status'), cell: (c) => <StatusBadge kind="drug" value={c.row.original.status} /> },
      { header: t('cols.updated'), meta: { hideBelow: 'lg' }, cell: (c) => formatDate(c.row.original.updated_at) },
    ],
    [t],
  );

  return (
    <div>
      <PageHeader
        title={`${t('title')}${q.data?.total != null ? ` (${formatNumber(q.data.total)})` : ''}`}
        description={t('subtitle')}
        actions={
          <>
            <Button variant="outline" onClick={() => setImportOpen(true)}><IconUpload size={18} aria-hidden /> {t('import.title')}</Button>
            <Button variant="outline" onClick={() => void downloadFile('/admin/drugs/export', undefined, 'drugs.csv').catch((e) => toast.error(errorMessage(e, t as never)))}><IconDownload size={18} aria-hidden /> {t('common:actions.export')}</Button>
            <Button asChild><Link to="/admin/drugs/new"><IconPlus size={18} aria-hidden /> {t('new')}</Link></Button>
          </>
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="w-full sm:w-64"><Input type="search" value={qInput} onChange={(e) => setQInput(e.target.value)} placeholder={t('search')} aria-label={t('search')} /></div>
        <div className="w-44"><Select aria-label={t('cols.status')} value={u.status ?? ALL} onValueChange={(v) => setUrl({ status: v === ALL ? undefined : (v as 'draft') }, { resetPage: true })}
          options={[{ value: ALL, label: `${t('cols.status')}: ${t('common:state.all')}` }, ...(['draft', 'published', 'archived'] as const).map((s) => ({ value: s, label: t(`status.${s}`) }))]} /></div>
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
          onRowClick={(r) => void navigate({ to: '/admin/drugs/$id', params: { id: r.id } } as never)}
          pagination={{ mode: 'offset', page: u.page, pageSize: u.size, total: q.data?.total ?? null, onPageChange: (page) => setUrl({ page }), onPageSizeChange: (size) => setUrl({ size }, { resetPage: true }) }}
          emptyState={<EmptyState icon={IconPill} title={t('empty')} action={<Button asChild><Link to="/admin/drugs/new">{t('new')}</Link></Button>} />}
          renderCard={(r) => (<div className="flex items-center justify-between gap-2"><div><p className="font-medium">{r.inn}</p><p className="text-xs text-muted">{r.group}</p></div><StatusBadge kind="drug" value={r.status} /></div>)}
          caption={t('title')}
        />
      </div>
      <ImportDialog open={importOpen} onOpenChange={setImportOpen} />
    </div>
  );
}
