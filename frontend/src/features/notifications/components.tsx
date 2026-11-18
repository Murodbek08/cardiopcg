import { useEffect } from 'react';
import { Link, useNavigate } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { IconBell, IconAlertOctagon, IconInfoCircle, IconStethoscope } from '@tabler/icons-react';
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger, Button, Skeleton, cn, formatDateTime } from '@/shared';
import type { NotificationItem } from '@/shared/api/types';
import { notificationTarget, useMarkRead, useNotifications, useUnreadCount } from './api';

export function notificationIcon(n: NotificationItem) {
  if (n.type === 'critical_finding' || n.type === 'analysis_failed') return IconAlertOctagon;
  if (n.type === 'system') return IconInfoCircle;
  return IconStethoscope;
}

/** Bell in the top bar: unread badge, last 8 notifications, tab-title counter `(3) CardioPCG AI`. */
export function NotificationBell() {
  const { t } = useTranslation('notifications');
  const navigate = useNavigate();
  const unread = useUnreadCount();
  const list = useNotifications({ limit: 8 });
  const mark = useMarkRead();
  const count = unread.data ?? 0;

  useEffect(() => {
    document.title = count > 0 ? `(${count}) CardioPCG AI` : 'CardioPCG AI';
    return () => {
      document.title = 'CardioPCG AI';
    };
  }, [count]);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="relative" aria-label={t('bell', { count })}>
          <IconBell size={20} aria-hidden />
          {count > 0 && (
            <span className="absolute right-1 top-1 flex min-w-4 items-center justify-center rounded-full bg-danger-500 px-1 text-[10px] font-bold leading-4 text-white">
              {count > 99 ? '99+' : count}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-80 p-0">
        <div className="flex items-center justify-between border-b border-border px-3 py-2">
          <p className="text-sm font-semibold">{t('title')}</p>
          <Link to="/notifications" className="text-xs text-brand-600 hover:underline dark:text-brand-300">
            {t('view_all')}
          </Link>
        </div>
        <div className="max-h-96 overflow-y-auto">
          {list.isLoading ? (
            <div className="space-y-2 p-3">
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
            </div>
          ) : !list.data?.items.length ? (
            <p className="px-3 py-6 text-center text-sm text-muted">{t('empty')}</p>
          ) : (
            list.data.items.map((n) => {
              const I = notificationIcon(n);
              return (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => {
                    if (!n.is_read) mark.mutate(n.id);
                    const to = notificationTarget(n);
                    if (to) void navigate({ to });
                  }}
                  className={cn('flex w-full items-start gap-2 border-b border-border px-3 py-2.5 text-left last:border-0 hover:bg-surface-2', !n.is_read && 'bg-brand-50/60 dark:bg-brand-900/20')}
                >
                  <I size={18} className={cn('mt-0.5 shrink-0', n.type === 'critical_finding' ? 'text-danger-500' : 'text-muted')} aria-hidden />
                  <span className="min-w-0">
                    <span className={cn('block truncate text-sm', !n.is_read && 'font-semibold')}>{n.title}</span>
                    <span className="block text-xs text-muted">{formatDateTime(n.created_at)}</span>
                  </span>
                </button>
              );
            })
          )}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
