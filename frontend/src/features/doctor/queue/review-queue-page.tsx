import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { IconCircleCheck } from '@tabler/icons-react';
import { Alert, Button, Card, CardBody, CardHeader, EmptyState, ErrorState, PageHeader, SkeletonRows, StatusBadge, cn, formatNumber } from '@/shared';
import { useDoctorQueue, type QueueItem } from '../api';

/** Sequential review: priority-ordered queue (critical first) with a one-key "next" (N). */
export function ReviewQueuePage() {
  const { t } = useTranslation('doctor');
  const navigate = useNavigate();
  const q = useDoctorQueue();
  const items: QueueItem[] = useMemo(() => q.data?.items ?? [], [q.data]);
  const [sel, setSel] = useState<string | null>(null);
  const current = items.find((i) => i.exam_id === sel) ?? items[0];

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || e.ctrlKey || e.metaKey) return;
      if (e.key.toLowerCase() === 'n' && items.length) {
        const i = items.findIndex((x) => x.exam_id === current?.exam_id);
        setSel(items[(i + 1) % items.length]!.exam_id);
      }
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [items, current?.exam_id]);

  return (
    <div>
      <PageHeader title={t('queue.title')} description={t('queue.hint')} actions={current ? <Button onClick={() => void navigate({ to: '/exams/$id', params: { id: current.exam_id } } as never)}>{t('queue.open_next')}</Button> : undefined} />
      {q.isLoading ? <SkeletonRows rows={6} /> : q.isError ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : items.length === 0 ? <Card><EmptyState icon={IconCircleCheck} title={t('dashboard.queue_empty')} /></Card> : (
        <div className="grid gap-4 lg:grid-cols-5">
          <Card className="lg:col-span-3"><ul className="divide-y divide-border" aria-label={t('queue.title')}>
            {items.map((i) => (
              <li key={i.exam_id}>
                <button type="button" onClick={() => setSel(i.exam_id)} aria-current={current?.exam_id === i.exam_id} className={cn('flex w-full flex-wrap items-center justify-between gap-2 px-4 py-3 text-left hover:bg-surface-2', current?.exam_id === i.exam_id && 'bg-brand-50 dark:bg-brand-900/30')}>
                  <span><span className="font-medium">{i.patient.full_name}</span><br /><span className="text-xs text-muted">{i.exam_no} &middot; {i.waiting_min != null ? `${formatNumber(i.waiting_min)} ${t('kpi.min')}` : ''}</span></span>
                  <span className="flex items-center gap-2"><StatusBadge kind="priority" value={i.priority} /><StatusBadge kind="severity" value={i.severity} /></span>
                </button>
              </li>
            ))}
          </ul></Card>
          {current && (
            <Card className="lg:col-span-2 lg:sticky lg:top-24 lg:self-start">
              <CardHeader title={current.patient.full_name} description={`${current.patient.mrn} - ${current.patient.age} / ${t(`common:gender.${current.patient.gender}`)}`} />
              <CardBody className="space-y-3">
                <div className="flex flex-wrap gap-2"><StatusBadge kind="priority" value={current.priority} /><StatusBadge kind="pcg" value={current.ai_class} /><StatusBadge kind="severity" value={current.severity} /></div>
                {(current.priority === 'emergency' || current.severity === 'critical') && <Alert tone="danger">{t('queue.critical')}</Alert>}
                <Button asChild className="w-full"><Link to="/exams/$id" params={{ id: current.exam_id }}>{t('queue.open')}</Link></Button>
                <p className="text-xs text-muted">{t('queue.key_hint')}</p>
              </CardBody>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
