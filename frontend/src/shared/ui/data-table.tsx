import type { ReactNode } from 'react';
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef, type RowData } from '@tanstack/react-table';
import { useTranslation } from 'react-i18next';
import { IconArrowDown, IconArrowUp, IconSelector, IconChevronLeft, IconChevronRight } from '@tabler/icons-react';
import { cn } from '@/shared/lib/cn';
import { PAGE_SIZES } from '@/shared/lib/constants';
import { formatNumber } from '@/shared/lib/format';
import { Button } from './button';
import { Select } from './select';
import { EmptyState, ErrorState, Skeleton, DelayedSkeleton } from './feedback';
import { IconSearchOff } from '@tabler/icons-react';

declare module '@tanstack/react-table' {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData extends RowData, TValue> {
    /** Responsive: hide this column below the given breakpoint. */
    hideBelow?: 'sm' | 'md' | 'lg';
    /** Server sort key. When omitted the column is not sortable. */
    sortKey?: string;
    className?: string;
  }
}

/** `-field` = descending, `field` = ascending (doc 01, 3.14). */
export function nextSort(current: string | undefined, key: string): string | undefined {
  if (current === key) return `-${key}`;
  if (current === `-${key}`) return undefined;
  return key;
}

export interface OffsetPagination {
  mode: 'offset';
  page: number; // 1-based
  pageSize: number;
  total: number | null;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
}
export interface CursorPagination {
  mode: 'cursor';
  hasNext: boolean;
  hasPrev: boolean;
  onNext: () => void;
  onPrev: () => void;
  total?: number | null;
  pageSize?: number;
  onPageSizeChange?: (size: number) => void;
}

export interface DataTableProps<T> {
  columns: ColumnDef<T, never>[] | ColumnDef<T, unknown>[];
  data: T[];
  getRowId?: (row: T) => string;
  isLoading?: boolean;
  isFetching?: boolean;
  error?: unknown;
  onRetry?: () => void;
  sort?: string;
  onSortChange?: (sort: string | undefined) => void;
  pagination?: OffsetPagination | CursorPagination;
  onRowClick?: (row: T) => void;
  emptyState?: ReactNode;
  /** Phones/tablets (<md): render rows as cards instead of a table. */
  renderCard?: (row: T) => ReactNode;
  skeletonRows?: number;
  caption?: string;
  className?: string;
  rowClassName?: (row: T) => string | undefined;
}

const hideCls = { sm: 'max-sm:hidden', md: 'max-md:hidden', lg: 'max-lg:hidden' } as const;

export function DataTable<T>({
  columns, data, getRowId, isLoading, isFetching, error, onRetry, sort, onSortChange, pagination, onRowClick, emptyState,
  renderCard, skeletonRows = 8, caption, className, rowClassName,
}: DataTableProps<T>) {
  const { t } = useTranslation();
  const table = useReactTable<T>({
    data,
    columns: columns as ColumnDef<T, unknown>[],
    getCoreRowModel: getCoreRowModel(),
    getRowId: getRowId ? (r) => getRowId(r) : undefined,
    manualPagination: true,
    manualSorting: true,
  });

  if (error && !data.length) return <ErrorState error={error} onRetry={onRetry} />;

  const rows = table.getRowModel().rows;
  const showEmpty = !isLoading && rows.length === 0;

  return (
    <div className={cn('relative', className)} aria-busy={isLoading || undefined}>
      {isFetching && !isLoading && <div className="absolute inset-x-0 top-0 z-10 h-0.5 animate-pulse bg-brand-500" role="progressbar" aria-label={t('state.loading')} />}

      {renderCard && (
        <div className="space-y-2 md:hidden">
          {isLoading ? (
            <DelayedSkeleton>{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="mb-2 h-20 w-full" />)}</DelayedSkeleton>
          ) : (
            rows.map((r) => (
              <div
                key={r.id}
                onClick={onRowClick ? () => onRowClick(r.original) : undefined}
                className={cn('rounded-lg border border-border bg-surface p-3', onRowClick && 'cursor-pointer active:bg-surface-2')}
              >
                {renderCard(r.original)}
              </div>
            ))
          )}
        </div>
      )}

      <div className={cn('overflow-x-auto', renderCard && 'max-md:hidden')}>
        <table className="w-full border-collapse text-sm">
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="border-b border-border bg-surface-2/60 text-left">
                {hg.headers.map((h) => {
                  const meta = h.column.columnDef.meta;
                  const sortKey = meta?.sortKey;
                  const active = sort === sortKey ? 'asc' : sort === `-${sortKey}` ? 'desc' : null;
                  return (
                    <th
                      key={h.id}
                      scope="col"
                      aria-sort={active === 'asc' ? 'ascending' : active === 'desc' ? 'descending' : undefined}
                      className={cn('whitespace-nowrap px-3 py-2.5 text-xs font-semibold uppercase tracking-wide text-muted', meta?.hideBelow && hideCls[meta.hideBelow], meta?.className)}
                    >
                      {h.isPlaceholder ? null : sortKey && onSortChange ? (
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 rounded hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
                          onClick={() => onSortChange(nextSort(sort, sortKey))}
                        >
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {active === 'asc' ? <IconArrowUp size={14} aria-hidden /> : active === 'desc' ? <IconArrowDown size={14} aria-hidden /> : <IconSelector size={14} aria-hidden />}
                        </button>
                      ) : (
                        flexRender(h.column.columnDef.header, h.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {isLoading
              ? Array.from({ length: skeletonRows }).map((_, i) => (
                  <tr key={i} className="border-b border-border">
                    {table.getVisibleLeafColumns().map((c) => (
                      <td key={c.id} className={cn('px-3 py-3', c.columnDef.meta?.hideBelow && hideCls[c.columnDef.meta.hideBelow])}>
                        <Skeleton className="h-4 w-full max-w-40" />
                      </td>
                    ))}
                  </tr>
                ))
              : rows.map((r) => (
                  <tr
                    key={r.id}
                    onClick={onRowClick ? () => onRowClick(r.original) : undefined}
                    onKeyDown={onRowClick ? (e) => (e.key === 'Enter' ? onRowClick(r.original) : undefined) : undefined}
                    tabIndex={onRowClick ? 0 : undefined}
                    className={cn('border-b border-border last:border-0', onRowClick && 'cursor-pointer hover:bg-surface-2/70 focus-visible:bg-surface-2', rowClassName?.(r.original))}
                  >
                    {r.getVisibleCells().map((c) => (
                      <td key={c.id} className={cn('px-3 py-2.5 align-middle', c.column.columnDef.meta?.hideBelow && hideCls[c.column.columnDef.meta.hideBelow], c.column.columnDef.meta?.className)}>
                        {flexRender(c.column.columnDef.cell, c.getContext())}
                      </td>
                    ))}
                  </tr>
                ))}
          </tbody>
        </table>
      </div>

      {showEmpty && (emptyState ?? <EmptyState icon={IconSearchOff} title={t('state.no_results')} />)}
      {pagination && <TablePagination p={pagination} count={rows.length} />}
    </div>
  );
}

function TablePagination({ p, count }: { p: OffsetPagination | CursorPagination; count: number }) {
  const { t } = useTranslation();
  const sizeSelect = (size: number | undefined, on?: (n: number) => void) =>
    on && size ? (
      <div className="flex items-center gap-2 text-sm text-muted">
        <span>{t('state.rows_per_page')}</span>
        <Select
          aria-label={t('state.rows_per_page')}
          className="h-8 w-20"
          value={String(size)}
          onValueChange={(v) => on(Number(v))}
          options={PAGE_SIZES.map((s) => ({ value: String(s), label: s }))}
        />
      </div>
    ) : null;

  if (p.mode === 'offset') {
    const pages = p.total !== null ? Math.max(1, Math.ceil(p.total / p.pageSize)) : null;
    const from = count ? (p.page - 1) * p.pageSize + 1 : 0;
    const to = (p.page - 1) * p.pageSize + count;
    return (
      <nav className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-3 py-3" aria-label="Pagination">
        <div className="text-sm text-muted">{p.total !== null ? t('state.showing', { from: formatNumber(from), to: formatNumber(to), total: formatNumber(p.total) }) : null}</div>
        <div className="flex items-center gap-3">
          {sizeSelect(p.pageSize, p.onPageSizeChange)}
          <Button size="icon-sm" variant="outline" aria-label={t('pagination.prev')} disabled={p.page <= 1} onClick={() => p.onPageChange(p.page - 1)}>
            <IconChevronLeft size={16} aria-hidden />
          </Button>
          <span className="text-sm tabular-nums">{pages ? t('state.page_of', { page: p.page, pages }) : p.page}</span>
          <Button size="icon-sm" variant="outline" aria-label={t('pagination.next')} disabled={pages ? p.page >= pages : count < p.pageSize} onClick={() => p.onPageChange(p.page + 1)}>
            <IconChevronRight size={16} aria-hidden />
          </Button>
        </div>
      </nav>
    );
  }
  return (
    <nav className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-3 py-3" aria-label="Pagination">
      <div className="text-sm text-muted">{p.total != null ? `${t('state.total')}: ${formatNumber(p.total)}` : null}</div>
      <div className="flex items-center gap-3">
        {sizeSelect(p.pageSize, p.onPageSizeChange)}
        <Button size="sm" variant="outline" disabled={!p.hasPrev} onClick={p.onPrev}>
          <IconChevronLeft size={16} aria-hidden /> {t('pagination.prev')}
        </Button>
        <Button size="sm" variant="outline" disabled={!p.hasNext} onClick={p.onNext}>
          {t('pagination.next')} <IconChevronRight size={16} aria-hidden />
        </Button>
      </div>
    </nav>
  );
}
