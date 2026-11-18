import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from '@tanstack/react-router';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { IconCheck, IconCircle, IconLoader2, IconAlertOctagon } from '@tabler/icons-react';
import { Alert, Button, Card, CardBody, ConfirmDialog, ErrorState, PageHeader, StatusBadge, cn, connectSse, errorMessage, toast, type RealtimeEvent } from '@/shared';
import { PROGRESS_STAGES, stageIndex } from '../logic';
import { useAnalyze, useCancelExam, useExam, useExamStatus } from '../api';

interface LogLine { id: string; text: string }

/**
 * Live AI progress. SSE (`/examinations/{id}/events`) is primary; when it cannot be (re)established we fall back to
 * polling `/status` every 2 s. State is always recoverable from the server after a page refresh.
 */
export function ExamProgressPage() {
  const { t } = useTranslation('exams');
  const { id } = useParams({ strict: false }) as { id: string };
  const navigate = useNavigate();
  const qc = useQueryClient();
  const exam = useExam(id);
  const [sseDown, setSseDown] = useState(false);
  const [live, setLive] = useState<{ stage?: string; pct?: number } | null>(null);
  const [log, setLog] = useState<LogLine[]>([]);
  const [failed, setFailed] = useState<{ code?: string; message?: string; canRetry?: boolean } | null>(null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const done = useRef(false);

  const examStatus = exam.data?.status;
  const active = examStatus === 'queued' || examStatus === 'processing' || examStatus === 'uploaded';
  const status = useExamStatus(id, true, sseDown || active ? 2000 : false);
  const cancel = useCancelExam(id);
  const retry = useAnalyze(id);

  const push = (text: string) => setLog((l) => [...l.slice(-5), { id: `${Date.now()}-${l.length}`, text }]);

  useEffect(() => {
    const off = connectSse({
      path: `/examinations/${id}/events`,
      onFallback: () => setSseDown(true),
      onOpen: () => setSseDown(false),
      onEvent: (ev: RealtimeEvent) => {
        const d = ev.data as { stage?: string; progress_pct?: number; message?: string; error_code?: string };
        if (ev.type === 'analysis.progress') {
          setLive({ stage: d.stage, pct: d.progress_pct });
          if (d.stage) push(t(`progress.stage.${d.stage}`, { defaultValue: d.stage }));
        } else if (ev.type === 'analysis.failed') {
          setFailed({ code: d.error_code, message: d.message, canRetry: (ev.data as { can_retry?: boolean }).can_retry });
        } else if (ev.type === 'analysis.completed' || ev.type === 'exam.status_changed') {
          void qc.invalidateQueries({ queryKey: ['exams'] });
        }
      },
    });
    return off;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // fold polled status into the live view
  const job = status.data?.job;
  const stage = live?.stage ?? job?.stage;
  const pct = live?.pct ?? job?.progress_pct ?? (examStatus === 'ai_ready' || examStatus === 'in_review' || examStatus === 'completed' ? 100 : 0);
  const current = status.data?.status ?? examStatus;

  useEffect(() => {
    if (current === 'ai_ready' || current === 'in_review' || current === 'completed') {
      if (done.current) return;
      done.current = true;
      const tm = setTimeout(() => void navigate({ to: '/exams/$id', params: { id } } as never), 1500);
      return () => clearTimeout(tm);
    }
  }, [current, id, navigate]);

  if (exam.isError) return <ErrorState error={exam.error} onRetry={() => void exam.refetch()} />;
  const idx = stageIndex(stage);
  const isFailed = current === 'failed' || !!failed;
  const finished = current === 'ai_ready' || current === 'in_review' || current === 'completed';
  const llmSkipped = finished && exam.data?.report == null;

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title={`${t('progress.title')}: ${exam.data?.exam_no ?? ''}`} description={exam.data ? exam.data.patient.full_name : undefined} actions={current ? <StatusBadge kind="exam" value={current} /> : undefined} />
      {sseDown && <Alert tone="info" className="mb-4">{t('progress.polling')}</Alert>}
      <Card><CardBody className="space-y-5">
        <ol className="space-y-2">
          {PROGRESS_STAGES.map((s, i) => {
            const state = finished || i < idx ? 'done' : i === idx && !isFailed ? 'run' : isFailed && i === idx ? 'fail' : 'wait';
            return (
              <li key={s} className={cn('flex items-center gap-3 rounded-md px-3 py-2 text-sm', state === 'run' && 'bg-brand-50 font-medium dark:bg-brand-900/30')}>
                {state === 'done' ? <IconCheck size={18} className="text-success-500" aria-hidden /> : state === 'run' ? <IconLoader2 size={18} className="animate-spin text-brand-600" aria-hidden /> : state === 'fail' ? <IconAlertOctagon size={18} className="text-danger-500" aria-hidden /> : <IconCircle size={18} className="text-muted" aria-hidden />}
                <span>{t(`progress.stage.${s}`)}</span>
                <span className="sr-only">{t(`progress.state.${state}`)}</span>
              </li>
            );
          })}
        </ol>
        <div>
          <div className="mb-1 flex justify-between text-sm"><span>{t('progress.total')}</span><span className="font-mono-num">{pct}%</span></div>
          <div role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} className="h-2.5 overflow-hidden rounded-full bg-border"><div className="h-full bg-brand-600 transition-all" style={{ width: `${pct}%` }} /></div>
        </div>
        <ul aria-live="polite" className="min-h-10 space-y-0.5 text-xs text-muted">{log.map((l) => <li key={l.id}>{l.text}</li>)}</ul>

        {isFailed && (
          <Alert tone="danger" title={t('progress.failed')}>
            {failed?.message ?? exam.data?.failure_reason ?? job?.error_code ?? ''}
            <div className="mt-2 flex gap-2">
              <Button size="sm" loading={retry.isPending} onClick={() => retry.mutateAsync({ rerun: true }).then(() => { setFailed(null); done.current = false; }).catch((e) => toast.error(errorMessage(e, t as never)))}>{t('progress.retry')}</Button>
            </div>
          </Alert>
        )}
        {llmSkipped && <Alert tone="warning">{t('progress.llm_skipped')}</Alert>}
        {finished && <p className="text-sm text-success-500" role="status">{t('progress.done')}</p>}

        <div className="flex justify-between">
          <Button variant="ghost" onClick={() => void navigate({ to: '/exams' })}>{t('progress.background')}</Button>
          {active && <Button variant="danger" onClick={() => setConfirmCancel(true)}>{t('progress.cancel')}</Button>}
        </div>
      </CardBody></Card>
      <ConfirmDialog open={confirmCancel} onOpenChange={setConfirmCancel} title={t('progress.cancel')} description={t('progress.cancel_body')} danger loading={cancel.isPending}
        requireReason={{ label: t('progress.cancel_reason') }}
        onConfirm={async (reason) => { try { await cancel.mutateAsync(reason ?? 'cancelled'); setConfirmCancel(false); void navigate({ to: '/exams' }); } catch (e) { toast.error(errorMessage(e, t as never)); } }} />
    </div>
  );
}
