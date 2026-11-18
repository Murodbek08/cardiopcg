import { useState } from 'react';
import { z } from 'zod';
import { useNavigate } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { IconBellOff, IconChecks } from '@tabler/icons-react';
import { Button, Card, EmptyState, ErrorState, PageHeader, SkeletonRows, Tabs, TabsList, TabsTrigger, cn, formatDateTime } from '@/shared';
import { useUrlState } from '@/shared/hooks/url-state';
import { notificationTarget, useMarkAllRead, useMarkRead, useNotifications } from '../api';
import { notificationIcon } from '../components';

const schema = z.object({ filter: z.enum(['all', 'unread', 'critical']).catch('all') });

export function NotificationsPage() {
  const { t } = useTranslation('notifications');
  const navigate = useNavigate();
  const [{ filter }, setUrl] = useUrlState(schema);
  const [cursors, setCursors] = useState<string[]>([]);
  const cursor = cursors[cursors.length - 1];
  const q = useNotifications({
    limit: 20,
    cursor,
    is_read: filter === 'unread' ? false : undefined,
    type: filter === 'critical' ? 'critical_finding' : undefined,
  });
  const mark = useMarkRead();
  const markAll = useMarkAllRead();

  return (
    <div>
      <PageHeader
        title={t('title')}
        actions={
          <Button variant="outline" onClick={() => markAll.mutate()} loading={markAll.isPending}>
            <IconChecks size={18} aria-hidden /> {t('mark_all')}
          </Button>
        }
      />
      <Tabs value={filter} onValueChange={(v) => { setCursors([]); setUrl({ filter: v as 'all' }); }}>
        <TabsList>
          <TabsTrigger value="all">{t('filter.all')}</TabsTrigger>
          <TabsTrigger value="unread">{t('filter.unread')}</TabsTrigger>
          <TabsTrigger value="critical">{t('filter.critical')}</TabsTrigger>
        </TabsList>
      </Tabs>
      <Card className="mt-4">
        {q.isLoading ? (
          <div className="p-4"><SkeletonRows rows={6} /></div>
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : !q.data?.items.length ? (
          <EmptyState icon={IconBellOff} title={t('empty')} />
        ) : (
          <ul>
            {q.data.items.map((n) => {
              const I = notificationIcon(n);
              const to = notificationTarget(n);
              return (
                <li key={n.id} className={cn('flex items-start gap-3 border-b border-border px-4 py-3 last:border-0', !n.is_read && 'bg-brand-50/60 dark:bg-brand-900/20')}>
                  <I size={20} className={cn('mt-0.5 shrink-0', n.type === 'critical_finding' ? 'text-danger-500' : 'text-muted')} aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className={cn('text-sm', !n.is_read && 'font-semibold')}>{n.title}</p>
                    {n.body && <p className="text-sm text-muted">{n.body}</p>}
                    <p className="mt-0.5 text-xs text-muted">{formatDateTime(n.created_at)}</p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    {!n.is_read && (
                      <Button size="sm" variant="ghost" onClick={() => mark.mutate(n.id)}>
                        {t('mark_read')}
                      </Button>
                    )}
                    {to && (
                      <Button size="sm" variant="outline" onClick={() => { if (!n.is_read) mark.mutate(n.id); void navigate({ to }); }}>
                        {t('open')}
                      </Button>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        <div className="flex justify-between border-t border-border px-4 py-3">
          <Button size="sm" variant="outline" disabled={!cursors.length} onClick={() => setCursors((c) => c.slice(0, -1))}>
            {t('pagination.prev', { ns: 'common' })}
          </Button>
          <Button size="sm" variant="outline" disabled={!q.data?.page?.next_cursor} onClick={() => q.data?.page?.next_cursor && setCursors((c) => [...c, q.data!.page!.next_cursor!])}>
            {t('pagination.next', { ns: 'common' })}
          </Button>
        </div>
      </Card>
    </div>
  );
}
