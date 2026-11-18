import { useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { IconArrowsMaximize, IconDownload, IconTable, IconChartBar, IconInfoCircle } from '@tabler/icons-react';
import { Card, CardHeader } from '@/shared/ui/card';
import { Button } from '@/shared/ui/button';
import { Dialog } from '@/shared/ui/dialog';
import { Skeleton, ErrorState, EmptyState } from '@/shared/ui/feedback';
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, Tooltip } from '@/shared/ui/tabs';
import { cn } from '@/shared/lib/cn';

export interface ChartTable {
  columns: string[];
  rows: (string | number | null)[][];
}

export interface ChartCardProps {
  title: string;
  /** Short plain-language explanation shown as a tooltip (e.g. definition of "agreement"). */
  info?: string;
  caption?: string;
  isLoading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  isEmpty?: boolean;
  emptyText?: string;
  /** Data behind the chart: powers the "view as table" toggle and CSV export (a11y alternative). */
  table?: ChartTable;
  exportName?: string;
  height?: number;
  className?: string;
  actions?: ReactNode;
  children: ReactNode;
}

function toCsv(t: ChartTable): string {
  const esc = (v: string | number | null) => {
    let s = v === null ? '' : String(v);
    if (/^[=+\-@]/.test(s)) s = `'${s}`; // CSV formula injection guard
    return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return '\uFEFF' + [t.columns, ...t.rows].map((r) => r.map(esc).join(',')).join('\n');
}

function download(href: string, name: string) {
  const a = document.createElement('a');
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function exportPng(root: HTMLElement, name: string): Promise<void> {
  const canvas = root.querySelector('canvas');
  if (canvas) {
    download(canvas.toDataURL('image/png'), `${name}.png`);
    return;
  }
  const svg = root.querySelector('svg.recharts-surface') as SVGSVGElement | null;
  if (!svg) return;
  const { width, height } = svg.getBoundingClientRect();
  const xml = new XMLSerializer().serializeToString(svg);
  const img = new Image();
  const url = URL.createObjectURL(new Blob([xml], { type: 'image/svg+xml;charset=utf-8' }));
  await new Promise<void>((res, rej) => {
    img.onload = () => res();
    img.onerror = () => rej(new Error('png export failed'));
    img.src = url;
  });
  const c = document.createElement('canvas');
  c.width = width * 2;
  c.height = height * 2;
  const ctx = c.getContext('2d');
  if (ctx) {
    ctx.scale(2, 2);
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--surface') || '#fff';
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(img, 0, 0, width, height);
    download(c.toDataURL('image/png'), `${name}.png`);
  }
  URL.revokeObjectURL(url);
}

/** Card + figure/figcaption + "view as table" + CSV/PNG export + fullscreen. Each chart loads independently. */
export function ChartCard({ title, info, caption, isLoading, error, onRetry, isEmpty, emptyText, table, exportName, height = 280, className, actions, children }: ChartCardProps) {
  const { t } = useTranslation();
  const [asTable, setAsTable] = useState(false);
  const [full, setFull] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const name = exportName ?? title.toLowerCase().replace(/\s+/g, '-');

  const content = (h: number) => (
    <div style={{ height: h }} className="w-full">
      {isLoading ? (
        <Skeleton className="h-full w-full" />
      ) : error ? (
        <ErrorState compact error={error} onRetry={onRetry} />
      ) : isEmpty ? (
        <EmptyState title={emptyText ?? t('state.empty_period')} className="py-6" />
      ) : asTable && table ? (
        <div className="h-full overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase text-muted">
                {table.columns.map((c) => (
                  <th key={c} scope="col" className="px-2 py-1.5">{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((r, i) => (
                <tr key={i} className="border-b border-border last:border-0">
                  {r.map((v, j) => (
                    <td key={j} className="px-2 py-1.5 tabular-nums">{v ?? '-'}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        children
      )}
    </div>
  );

  const menu = (
    <>
      {actions}
      {table && !isLoading && !error && !isEmpty && (
        <Tooltip content={asTable ? t('actions.view_chart') : t('actions.view_table')}>
          <Button size="icon-sm" variant="ghost" aria-pressed={asTable} aria-label={asTable ? t('actions.view_chart') : t('actions.view_table')} onClick={() => setAsTable((v) => !v)}>
            {asTable ? <IconChartBar size={16} aria-hidden /> : <IconTable size={16} aria-hidden />}
          </Button>
        </Tooltip>
      )}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="icon-sm" variant="ghost" aria-label={t('actions.export')}>
            <IconDownload size={16} aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem disabled={!table} onSelect={() => table && download(URL.createObjectURL(new Blob([toCsv(table)], { type: 'text/csv;charset=utf-8' })), `${name}.csv`)}>
            {t('actions.export_csv')}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => ref.current && void exportPng(ref.current, name)}>{t('actions.export_png')}</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Button size="icon-sm" variant="ghost" aria-label={t('actions.fullscreen')} onClick={() => setFull(true)}>
        <IconArrowsMaximize size={16} aria-hidden />
      </Button>
    </>
  );

  return (
    <>
      <Card className={cn('flex flex-col', className)}>
        <figure ref={ref} className="m-0 flex flex-1 flex-col">
          <CardHeader
            title={
              <span className="inline-flex items-center gap-1.5">
                <figcaption className="inline">{title}</figcaption>
                {info && (
                  <Tooltip content={info}>
                    <button type="button" aria-label={info} className="text-muted hover:text-foreground">
                      <IconInfoCircle size={16} aria-hidden />
                    </button>
                  </Tooltip>
                )}
              </span>
            }
            description={caption}
            actions={menu}
          />
          <div className="px-3 pb-4 pt-3">{content(height)}</div>
        </figure>
      </Card>
      <Dialog open={full} onOpenChange={setFull} title={title} size="xl">
        {full && content(Math.max(360, Math.round(window.innerHeight * 0.6)))}
      </Dialog>
    </>
  );
}
