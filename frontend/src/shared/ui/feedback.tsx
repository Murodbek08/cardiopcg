import { useEffect, useState, type HTMLAttributes, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
  IconAlertTriangle, IconAlertOctagon, IconInfoCircle, IconCircleCheck, IconInbox, IconRefresh, IconCopy,
  type Icon,
} from '@tabler/icons-react';
import { toast } from 'sonner';
import { cn } from '@/shared/lib/cn';
import { Button } from './button';
import { ApiError } from '@/shared/api/errors';

// ---------------- Skeleton ----------------
export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden className={cn('skeleton-shimmer rounded-md', className)} {...props} />;
}

/** Delays rendering of skeletons by 200 ms to avoid flashes on fast responses (doc 03, section 5). */
export function DelayedSkeleton({ children, delay = 200 }: { children: ReactNode; delay?: number }) {
  const [show, setShow] = useState(delay === 0);
  useEffect(() => {
    const id = setTimeout(() => setShow(true), delay);
    return () => clearTimeout(id);
  }, [delay]);
  return <div aria-busy="true" aria-live="polite">{show ? children : null}</div>;
}

export function SkeletonRows({ rows = 6, className }: { rows?: number; className?: string }) {
  return (
    <DelayedSkeleton>
      <div className={cn('space-y-2', className)}>
        {Array.from({ length: rows }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    </DelayedSkeleton>
  );
}

// ---------------- EmptyState ----------------
export function EmptyState({
  icon: I = IconInbox,
  title,
  description,
  action,
  className,
}: {
  icon?: Icon;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-2 px-6 py-12 text-center', className)}>
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-2 text-muted">
        <I size={24} aria-hidden />
      </span>
      <p className="text-h3 font-semibold">{title}</p>
      {description && <p className="max-w-md text-sm text-muted">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

// ---------------- ErrorState ----------------
export function errorMessage(e: unknown, t: (k: string, o?: Record<string, unknown>) => string): string {
  if (e instanceof ApiError) {
    if (e.isNetwork) return t('errors:network');
    const byCode = t(`errors:codes.${e.code}`, { defaultValue: '' });
    if (byCode) return byCode;
    if (e.status === 403) return t('errors:forbidden');
    if (e.status === 404) return t('errors:not_found');
    if (e.status === 429) return e.retryAfter ? t('errors:rate_limited', { seconds: e.retryAfter }) : t('errors:rate_limited_generic');
    if (e.status >= 500) return t('errors:server');
    return e.message || t('errors:unknown');
  }
  return e instanceof Error ? e.message : t('errors:unknown');
}

export function ErrorState({ error, onRetry, className, compact }: { error?: unknown; onRetry?: () => void; className?: string; compact?: boolean }) {
  const { t } = useTranslation();
  const requestId = error instanceof ApiError ? error.requestId : undefined;
  return (
    <div role="alert" className={cn('flex flex-col items-center justify-center gap-2 text-center', compact ? 'px-4 py-6' : 'px-6 py-10', className)}>
      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-danger-50 text-danger-500">
        <IconAlertOctagon size={22} aria-hidden />
      </span>
      <p className="font-medium">{errorMessage(error, t as never)}</p>
      <div className="flex flex-wrap items-center justify-center gap-2">
        {onRetry && (
          <Button size="sm" variant="outline" onClick={onRetry}>
            <IconRefresh size={16} aria-hidden /> {t('actions.retry')}
          </Button>
        )}
        {requestId && (
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded px-2 py-1 font-mono-num text-xs text-muted hover:bg-surface-2"
            onClick={() => {
              void navigator.clipboard?.writeText(requestId);
              toast.success(t('actions.copied'));
            }}
            title={t('actions.copy')}
          >
            {t('state.request_id')}: {requestId.slice(0, 12)} <IconCopy size={12} aria-hidden />
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------- Alert ----------------
type AlertTone = 'info' | 'success' | 'warning' | 'danger';
const alertCfg: Record<AlertTone, { cls: string; icon: Icon; role: 'status' | 'alert' }> = {
  info: { cls: 'border-info-500/40 bg-info-50 text-info-500', icon: IconInfoCircle, role: 'status' },
  success: { cls: 'border-success-500/40 bg-success-50 text-success-500', icon: IconCircleCheck, role: 'status' },
  warning: { cls: 'border-warning-500/40 bg-warning-50 text-warning-500', icon: IconAlertTriangle, role: 'alert' },
  danger: { cls: 'border-danger-500/40 bg-danger-50 text-danger-500', icon: IconAlertOctagon, role: 'alert' },
};
export function Alert({ tone = 'info', title, children, className, action }: { tone?: AlertTone; title?: ReactNode; children?: ReactNode; className?: string; action?: ReactNode }) {
  const c = alertCfg[tone];
  const I = c.icon;
  return (
    <div role={c.role} className={cn('flex items-start gap-3 rounded-md border px-4 py-3', c.cls, className)}>
      <I size={20} className="mt-0.5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 text-sm">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={cn(title && 'mt-0.5', 'text-foreground')}>{children}</div>}
      </div>
      {action}
    </div>
  );
}
