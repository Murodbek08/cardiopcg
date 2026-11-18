import type { ReactNode } from 'react';
import { Link } from '@tanstack/react-router';
import { IconChevronRight, IconArrowUpRight, IconArrowDownRight, IconMinus, type Icon } from '@tabler/icons-react';
import { cn } from '@/shared/lib/cn';
import { Skeleton, ErrorState } from './feedback';
import { Card } from './card';
import { formatNumber } from '@/shared/lib/format';

export interface Crumb {
  label: string;
  to?: string;
}

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-2 text-sm text-muted">
      <ol className="flex flex-wrap items-center gap-1">
        {items.map((c, i) => (
          <li key={i} className="flex items-center gap-1">
            {c.to && i < items.length - 1 ? (
              <Link to={c.to} className="rounded hover:text-foreground hover:underline focus-visible:outline-2 focus-visible:outline-ring">
                {c.label}
              </Link>
            ) : (
              <span aria-current={i === items.length - 1 ? 'page' : undefined} className={i === items.length - 1 ? 'text-foreground' : undefined}>
                {c.label}
              </span>
            )}
            {i < items.length - 1 && <IconChevronRight size={14} aria-hidden />}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function PageHeader({ title, description, actions, breadcrumbs }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; breadcrumbs?: Crumb[] }) {
  return (
    <header className="mb-6">
      {breadcrumbs && <Breadcrumbs items={breadcrumbs} />}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-h1 font-semibold tracking-tight">{title}</h1>
          {description && <p className="mt-1 text-sm text-muted">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

export interface KpiCardProps {
  label: string;
  value: ReactNode;
  unit?: string;
  /** Change vs previous equal period, in percent. */
  deltaPct?: number | null;
  /** When true a rising value is bad (e.g. error rate); colours the delta accordingly. */
  invertDelta?: boolean;
  icon?: Icon;
  hint?: string;
  isLoading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  sparkline?: ReactNode;
  onClick?: () => void;
  className?: string;
}

export function KpiCard({ label, value, unit, deltaPct, invertDelta, icon: I, hint, isLoading, error, onRetry, sparkline, onClick, className }: KpiCardProps) {
  const body = (
    <>
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-muted">{label}</p>
        {I && (
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-brand-50 text-brand-700 dark:bg-brand-900/40 dark:text-brand-200">
            <I size={18} aria-hidden />
          </span>
        )}
      </div>
      {isLoading ? (
        <Skeleton className="mt-3 h-8 w-24" />
      ) : error ? (
        <ErrorState compact error={error} onRetry={onRetry} />
      ) : (
        <>
          <p className="mt-2 flex items-baseline gap-1 text-display font-bold">
            <span>{value}</span>
            {unit && <span className="text-sm font-medium text-muted">{unit}</span>}
          </p>
          <div className="mt-1 flex items-center justify-between gap-2">
            <DeltaBadge value={deltaPct} invert={invertDelta} />
            {hint && <span className="truncate text-xs text-muted">{hint}</span>}
          </div>
          {sparkline && <div className="mt-2 h-10">{sparkline}</div>}
        </>
      )}
    </>
  );
  const cls = cn('block w-full p-4 text-left', onClick && 'cursor-pointer transition-shadow hover:shadow-pop focus-visible:outline-2 focus-visible:outline-ring', className);
  return (
    <Card>
      {onClick ? (
        <button type="button" onClick={onClick} className={cls}>
          {body}
        </button>
      ) : (
        <div className={cls}>{body}</div>
      )}
    </Card>
  );
}

export function DeltaBadge({ value, invert }: { value?: number | null; invert?: boolean }) {
  if (value === null || value === undefined) return <span className="text-xs text-muted">&nbsp;</span>;
  const up = value > 0;
  const flat = Math.abs(value) < 0.05;
  const good = flat ? null : invert ? !up : up;
  const I = flat ? IconMinus : up ? IconArrowUpRight : IconArrowDownRight;
  return (
    <span
      className={cn('inline-flex items-center gap-0.5 text-xs font-medium', good === null ? 'text-muted' : good ? 'text-success-500' : 'text-danger-500')}
      aria-label={`${up ? '+' : ''}${formatNumber(value, 1)}%`}
    >
      <I size={14} aria-hidden />
      {up ? '+' : ''}
      {formatNumber(value, 1)}%
    </span>
  );
}
