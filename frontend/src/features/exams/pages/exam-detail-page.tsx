import { useRef, useState } from 'react';
import { useParams } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { Alert, AiDisclaimerBadge, AudioWaveform, Card, CardBody, CardHeader, ErrorState, PageHeader, SkeletonRows, SpectrogramView, StatusBadge, formatDateTime, formatDuration, formatNumber, usePermission, type WaveformHandle } from '@/shared';
import { useAuthStore } from '@/shared/store/auth';
import { maskName } from '@/shared/lib/mask';
import { useExam, useSegments } from '../api';

/**
 * Read-only examination view (admin: masked identity, signal + aggregate AI class only).
 * The doctor/nurse WORKSPACE (differential, drugs, conclusion, editing) is implemented by the next agent and
 * should replace this component for those roles in src/features/exams/routes.tsx.
 */
export function ExamDetailPage() {
  const { t } = useTranslation('exams');
  const { id } = useParams({ strict: false }) as { id: string };
  const role = useAuthStore((s) => s.user?.role);
  const masked = !usePermission('patient:read_unmasked');
  const q = useExam(id);
  const exam = q.data;
  const audio = exam?.recordings.filter((r) => r.kind === 'audio') ?? [];
  const [activeIdx, setActiveIdx] = useState(0);
  const active = audio[activeIdx];
  const segs = useSegments(id, !!exam && exam.status !== 'draft' && exam.status !== 'uploaded');
  const [progress, setProgress] = useState(0);
  const handle = useRef<WaveformHandle>(null);

  if (q.isLoading) return <SkeletonRows rows={6} />;
  if (q.isError || !exam) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;

  const patientName = masked ? maskName(exam.patient.full_name) : exam.patient.full_name;
  const segsForActive = (segs.data ?? []).filter((s) => !active || s.recording_id === active.id);

  return (
    <div className="space-y-6">
      <PageHeader
        title={`${t('detail')} ${exam.exam_no}`}
        description={<span className="inline-flex flex-wrap items-center gap-2">{patientName} <StatusBadge kind="exam" value={exam.status} /> <StatusBadge kind="priority" value={exam.priority} /> {formatDateTime(exam.examined_at)}</span>}
        breadcrumbs={[{ label: t('title'), to: '/exams' }, { label: exam.exam_no }]}
      />
      {role === 'admin' && <Alert tone="info">{t('readonly_admin')}</Alert>}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader title={t('recordings')} description={audio.length ? `${audio.length}` : undefined} />
            <CardBody className="space-y-4">
              {audio.length === 0 ? <p className="text-sm text-muted">-</p> : (
                <>
                  <div className="flex flex-wrap gap-2" role="tablist" aria-label={t('recordings')}>
                    {audio.map((r, i) => (
                      <button key={r.id} role="tab" aria-selected={i === activeIdx} onClick={() => setActiveIdx(i)} className={`rounded-full border px-3 py-1 text-sm ${i === activeIdx ? 'border-brand-600 bg-brand-50 text-brand-800 dark:bg-brand-900/40 dark:text-brand-100' : 'border-border'}`}>
                        {r.site ? t(`clinical:site.${r.site}`) : r.original_filename} {r.duration_sec ? `(${formatDuration(r.duration_sec)})` : ''}
                      </button>
                    ))}
                  </div>
                  {active && (
                    <>
                      <AudioWaveform key={active.id} src={active.url} segments={segsForActive} editable={false} handleRef={handle} onTime={(tm, d) => setProgress(d ? tm / d : 0)} />
                      <SpectrogramView src={`/recordings/${active.id}/spectrogram`} progress={progress} />
                    </>
                  )}
                </>
              )}
            </CardBody>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader title={t('vitals.title')} />
            <CardBody>
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div><dt className="text-muted">{t('vitals.hr')}</dt><dd className="font-mono-num font-medium">{formatNumber(exam.heart_rate_bpm)}</dd></div>
                <div><dt className="text-muted">{t('vitals.bp')}</dt><dd className="font-mono-num font-medium">{exam.bp_systolic && exam.bp_diastolic ? `${exam.bp_systolic}/${exam.bp_diastolic}` : '-'}</dd></div>
                <div><dt className="text-muted">{t('vitals.spo2')}</dt><dd className="font-mono-num font-medium">{exam.spo2_pct ? `${exam.spo2_pct}%` : '-'}</dd></div>
                <div><dt className="text-muted">{t('vitals.temp')}</dt><dd className="font-mono-num font-medium">{exam.temperature_c ?? '-'}</dd></div>
              </dl>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title={t('analysis')} actions={exam.analysis ? <AiDisclaimerBadge compact /> : undefined} />
            <CardBody className="flex flex-col items-center gap-3">
              {exam.analysis ? (
                <>
                  <p className="text-display font-bold tabular-nums">{formatNumber(exam.analysis.confidence * 100, 0)}%</p>
                  <p className="-mt-2 text-xs text-muted">{t('confidence')}</p>
                  <div className="flex flex-wrap items-center justify-center gap-2"><StatusBadge kind="pcg" value={exam.analysis.pcg_class} /><StatusBadge kind="severity" value={exam.analysis.severity} /></div>
                  <p className="text-xs text-muted">{exam.analysis.model_version}</p>
                </>
              ) : <p className="text-sm text-muted">-</p>}
            </CardBody>
          </Card>
          {exam.status_history && exam.status_history.length > 0 && (
            <Card>
              <CardHeader title={t('history')} />
              <CardBody>
                <ol className="space-y-2 text-sm">
                  {exam.status_history.map((h, i) => (
                    <li key={i} className="flex items-center justify-between gap-2"><StatusBadge kind="exam" value={h.to} /><span className="text-xs text-muted">{formatDateTime(h.at)}</span></li>
                  ))}
                </ol>
              </CardBody>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
