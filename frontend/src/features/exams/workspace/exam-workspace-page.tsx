import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { IconAlertTriangle, IconFileTypePdf, IconPrinter, IconRefresh } from '@tabler/icons-react';
import {
  AiDisclaimerBadge, Alert, AudioWaveform, Badge, Button, Card, CardBody, CardHeader, ErrorState, PageHeader, RiskGauge, SkeletonRows, SpectrogramView, StatusBadge, Tabs, TabsContent, TabsList, TabsTrigger,
  downloadFile, errorMessage, formatDateTime, formatDuration, formatNumber, get, toast, usePermission, cn,
} from '@/shared';
import { useAuthStore } from '@/shared/store/auth';
import type { AiReport, ExamDetail, PcgSegment } from '@/shared/api/types';
import { ExamDetailPage } from '../pages/exam-detail-page';
import { useAnalyze, useConclusionHistory, useExam, useRegenerateReport, useSegments } from '../api';
import { abnormalProbability, conclusionLocked, featureRows } from '../logic';
import { ConclusionForm } from './conclusion-form';
import { DrugRecommendationPanel } from './drug-panel';

const isFullReport = (r: ExamDetail['report']): r is AiReport => !!r && 'differential_diagnoses' in r && Array.isArray((r as AiReport).differential_diagnoses);

function FeatureTable({ exam, onPick }: { exam: ExamDetail; onPick?: (key: string) => void }) {
  const { t } = useTranslation('exams');
  if (!exam.analysis) return <p className="text-sm text-muted">{t('workspace.no_analysis')}</p>;
  const rows = featureRows(exam.analysis);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead><tr className="border-b border-border text-left text-xs uppercase text-muted"><th className="py-2 pr-3">{t('workspace.feature')}</th><th className="py-2 pr-3">{t('workspace.value')}</th><th className="py-2 pr-3">{t('workspace.range')}</th><th className="py-2">{t('columns.status')}</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="cursor-pointer border-b border-border last:border-0 hover:bg-surface-2" onClick={() => onPick?.(r.key)}>
              <td className="py-2 pr-3">{t(`features.${r.key}`)}</td>
              <td className="py-2 pr-3 font-mono-num">{r.value === null ? '-' : typeof r.value === 'number' ? formatNumber(r.value, 1) : r.value}{r.unit ? ` ${r.unit}` : ''}</td>
              <td className="py-2 pr-3 font-mono-num text-muted">{r.range ? `${r.range[0]}-${r.range[1]}` : '-'}</td>
              <td className="py-2">{r.value === null ? <span className="text-muted">-</span> : r.abnormal ? <Badge tone="warning" icon={IconAlertTriangle}>{t('workspace.abnormal')}</Badge> : <Badge tone="success">{t('workspace.normal')}</Badge>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const LIKELIHOOD: Record<string, number> = { high: 3, medium: 2, low: 1 };

function Differential({ report, canRegen, examId }: { report: ExamDetail['report']; canRegen: boolean; examId: string }) {
  const { t } = useTranslation('exams');
  const regen = useRegenerateReport(examId);
  const [open, setOpen] = useState<number | null>(null);
  if (!report || report.status === 'failed' || !isFullReport(report)) {
    return (
      <Alert tone="warning" title={t('workspace.llm_unavailable')}>
        {t('workspace.llm_unavailable_body')}
        {canRegen && <div className="mt-2"><Button size="sm" loading={regen.isPending} onClick={() => regen.mutate(undefined, { onError: (e) => toast.error(errorMessage(e, t as never)) })}><IconRefresh size={16} aria-hidden /> {t('common:actions.retry')}</Button></div>}
      </Alert>
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-sm">{report.summary}</p>
      {report.red_flags.length > 0 && <Alert tone="danger" title={t('workspace.red_flags')}><ul className="list-disc pl-5">{report.red_flags.map((r) => <li key={r}>{r}</li>)}</ul></Alert>}
      {report.differential_diagnoses.map((d, i) => {
        const dd = d as { name?: string; icd10?: string; likelihood?: string; rationale?: string };
        const n = LIKELIHOOD[dd.likelihood ?? ''] ?? 1;
        return (
          <Card key={i}><CardBody className="space-y-2">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <p className="font-semibold">{dd.name} {dd.icd10 && <span className="font-mono-num text-xs text-muted">{dd.icd10}</span>}</p>
              <AiDisclaimerBadge compact />
            </div>
            <div className="flex items-center gap-2" aria-label={`${t('workspace.likelihood')}: ${t(`workspace.likelihood_${dd.likelihood ?? 'low'}`)}`}>
              <span className="flex gap-1" aria-hidden>{[1, 2, 3].map((k) => <span key={k} className={cn('h-2 w-8 rounded-full', k <= n ? 'bg-brand-600' : 'bg-border')} />)}</span>
              <span className="text-sm">{t(`workspace.likelihood_${dd.likelihood ?? 'low'}`, { defaultValue: dd.likelihood })}</span>
            </div>
            {dd.rationale && (open === i ? <p className="text-sm text-muted">{dd.rationale}</p> : <Button size="sm" variant="link" onClick={() => setOpen(i)}>{t('common:actions.show_more')}</Button>)}
          </CardBody></Card>
        );
      })}
      {report.recommended_tests.length > 0 && <p className="text-sm"><span className="font-medium">{t('workspace.recommended_tests')}:</span> {report.recommended_tests.join(', ')}</p>}
      {canRegen && <Button size="sm" variant="outline" loading={regen.isPending} onClick={() => regen.mutate(undefined, { onError: (e) => toast.error(errorMessage(e, t as never)) })}><IconRefresh size={16} aria-hidden /> {t('workspace.regenerate')}</Button>}
    </div>
  );
}

function HistoryTab({ exam, doctor }: { exam: ExamDetail; doctor: boolean }) {
  const { t } = useTranslation('exams');
  const hist = useConclusionHistory(exam.id, doctor);
  return (
    <div className="space-y-4">
      <ol className="space-y-2 text-sm">{exam.status_history.map((h, i) => <li key={i} className="flex items-center justify-between gap-2"><StatusBadge kind="exam" value={h.to} /><span className="text-xs text-muted">{h.by_name ?? ''} {formatDateTime(h.at)}</span></li>)}</ol>
      {doctor && (hist.data?.length ?? 0) > 0 && (
        <div>
          <h4 className="mb-2 text-sm font-semibold">{t('conclusion.versions')}</h4>
          <ul className="space-y-2 text-sm">{hist.data!.map((c) => <li key={c.id} className="rounded-md border border-border p-2"><span className="font-medium">v{c.version}</span> <Badge tone={c.status === 'draft' ? 'neutral' : 'success'}>{t(`conclusion.status.${c.status}`, { defaultValue: c.status })}</Badge> <span className="text-xs text-muted">{formatDateTime(c.signed_at ?? c.updated_at)}</span>{c.amend_reason && <p className="text-xs text-muted">{c.amend_reason}</p>}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

export function ExamWorkspacePage() {
  const { t } = useTranslation('exams');
  const { id } = useParams({ strict: false }) as { id: string };
  const navigate = useNavigate();
  const role = useAuthStore((s) => s.user?.role);
  const isDoctor = usePermission('exam:edit_conclusion');
  const q = useExam(id);
  const exam = q.data;
  const audio = useMemo(() => exam?.recordings.filter((r) => r.kind === 'audio') ?? [], [exam]);
  const [idx, setIdx] = useState(0);
  const active = audio[idx];
  const hasAnalysis = !!exam?.analysis;
  const segs = useSegments(id, hasAnalysis);
  const [progress, setProgress] = useState(0);
  const reanalyze = useAnalyze(id);
  const [tab, setTab] = useState('features');
  const opened = useRef(false);
  const patientDetail = useQuery({ queryKey: ['patients', 'allergies', exam?.patient.id], queryFn: ({ signal }) => get<{ allergies: { id: string; substance: string; is_active: boolean }[] }>(`/patients/${exam!.patient.id}`, undefined, signal), enabled: !!exam && role !== 'admin' });

  // Doctor first open: GET conclusion moves ai_ready -> in_review on the server (404 = no draft yet, expected)
  useEffect(() => {
    if (isDoctor && exam?.status === 'ai_ready' && !opened.current) {
      opened.current = true;
      void get(`/examinations/${id}/conclusion`).catch(() => undefined).finally(() => void q.refetch());
    }
  }, [isDoctor, exam?.status, id, q]);

  // not analysed yet -> progress page (when analysis is running)
  useEffect(() => {
    if (exam && (exam.status === 'queued' || exam.status === 'processing')) void navigate({ to: '/exams/$id/progress', params: { id } } as never);
  }, [exam, id, navigate]);

  if (role === 'admin') return <ExamDetailPage />;
  if (q.isLoading) return <SkeletonRows rows={8} />;
  if (q.isError || !exam) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;

  const locked = conclusionLocked(exam.conclusion, exam.status);
  const prob = abnormalProbability(exam.analysis);
  const segsFor: PcgSegment[] = (segs.data ?? []).filter((s) => !active || s.recording_id === active.id);
  const allergies = patientDetail.data?.allergies.filter((a) => a.is_active) ?? [];
  const nurseHidden = !isDoctor && !exam.prescription;
  const failedAnalysis = exam.status === 'failed';

  return (
    <div className="space-y-5">
      <PageHeader
        title={<span className="inline-flex flex-wrap items-center gap-3">{exam.patient.full_name}<span className="font-mono-num text-sm font-normal text-muted">{exam.exam_no}</span></span>}
        description={<span className="inline-flex flex-wrap items-center gap-2"><StatusBadge kind="exam" value={exam.status} /><StatusBadge kind="priority" value={exam.priority} />{formatDateTime(exam.examined_at)}{!isDoctor && <Badge tone="info" icon={false}>{t('workspace.read_only')}</Badge>}</span>}
        breadcrumbs={[{ label: t('title'), to: '/exams' }, { label: exam.exam_no }]}
        actions={
          <>
            {exam.status === 'completed' && <><Button variant="outline" asChild><Link to="/exams/$id/report" params={{ id }}><IconPrinter size={18} aria-hidden /> {t('workspace.report')}</Link></Button><Button variant="outline" onClick={() => void downloadFile(`/examinations/${id}/export/pdf`, undefined, `${exam.exam_no}.pdf`).catch((e) => toast.error(errorMessage(e, t as never)))}><IconFileTypePdf size={18} aria-hidden /> PDF</Button></>}
            {isDoctor && !locked && (exam.status === 'ai_ready' || exam.status === 'in_review' || failedAnalysis) && <Button variant="outline" loading={reanalyze.isPending} onClick={() => reanalyze.mutate({ rerun: true }, { onSuccess: () => void navigate({ to: '/exams/$id/progress', params: { id } } as never), onError: (e) => toast.error(errorMessage(e, t as never)) })}><IconRefresh size={18} aria-hidden /> {t('workspace.reanalyze')}</Button>}
          </>
        }
      />

      {allergies.length > 0 && <Alert tone="warning" title={t('workspace.allergies')}><span className="flex flex-wrap gap-2">{allergies.map((a) => <Badge key={a.id} tone="warning" icon={IconAlertTriangle}>{a.substance}</Badge>)}</span></Alert>}
      {failedAnalysis && <Alert tone="danger" title={t('progress.failed')}>{exam.failure_reason}</Alert>}
      {exam.analysis && !exam.analysis.quality_ok && <Alert tone="warning">{exam.analysis.quality_notes ?? t('workspace.low_quality')}</Alert>}

      <div className="grid gap-5 xl:grid-cols-5">
        <div className="space-y-5 xl:col-span-3">
          <Card>
            <CardHeader title={t('workspace.signal')} description={`${t('vitals.hr')}: ${exam.heart_rate_bpm ?? '-'} · ${t('vitals.bp')}: ${exam.bp_systolic && exam.bp_diastolic ? `${exam.bp_systolic}/${exam.bp_diastolic}` : '-'} · SpO2: ${exam.spo2_pct ?? '-'}`} />
            <CardBody className="space-y-4">
              {audio.length === 0 ? <p className="text-sm text-muted">{t('workspace.no_audio')}</p> : (
                <>
                  <div className="flex flex-wrap gap-2" role="tablist" aria-label={t('recordings')}>
                    {audio.map((r, i) => <button key={r.id} role="tab" aria-selected={i === idx} onClick={() => setIdx(i)} className={cn('min-h-10 rounded-full border px-3 text-sm', i === idx ? 'border-brand-600 bg-brand-50 font-medium dark:bg-brand-900/40' : 'border-border')}>{r.site ? t(`clinical:site.${r.site}`) : r.original_filename} ({formatDuration(r.duration_sec)})</button>)}
                  </div>
                  {active && (
                    <>
                      <AudioWaveform key={active.id} src={active.url} segments={segsFor} editable={false} onTime={(tm, d) => setProgress(d ? tm / d : 0)} />
                      {hasAnalysis && <SpectrogramView src={`/recordings/${active.id}/spectrogram`} progress={progress} />}
                      <details className="text-sm">
                        <summary className="cursor-pointer font-medium">{t('workspace.segments_table')} ({segsFor.length})</summary>
                        <div className="mt-2 max-h-56 overflow-auto"><table className="w-full text-xs"><thead><tr className="text-left text-muted"><th>#</th><th>{t('workspace.seg_type')}</th><th>{t('workspace.seg_start')}</th><th>{t('workspace.seg_end')}</th></tr></thead><tbody>{segsFor.filter((s) => s.type !== 'systole' && s.type !== 'diastole').map((s) => <tr key={s.id}><td>{s.seq}</td><td>{s.type}</td><td className="font-mono-num">{s.start_ms}</td><td className="font-mono-num">{s.end_ms}</td></tr>)}</tbody></table></div>
                      </details>
                    </>
                  )}
                </>
              )}
            </CardBody>
          </Card>
          {isDoctor && hasAnalysis && <ConclusionForm examId={id} status={exam.status} conclusion={exam.conclusion} analysis={exam.analysis} items={exam.prescription?.items ?? []} />}
          {!isDoctor && exam.conclusion && (
            <Card><CardHeader title={t('conclusion.title')} /><CardBody className="space-y-2 text-sm"><p>{exam.conclusion.diagnosis_text}</p><p className="text-muted">{exam.conclusion.recommendations}</p></CardBody></Card>
          )}
        </div>

        <div className="xl:col-span-2">
          <Card>
            <CardBody className="space-y-4">
              {exam.analysis ? (
                <div className="flex flex-wrap items-center justify-around gap-3">
                  <RiskGauge value={prob} size={190} caption={t('workspace.abnormal_probability')} />
                  <div className="space-y-2 text-center"><StatusBadge kind="pcg" value={exam.analysis.pcg_class} /><br /><StatusBadge kind="severity" value={exam.analysis.severity} /><p className="text-xs text-muted">{t('confidence')}: {formatNumber(exam.analysis.confidence * 100, 0)}%</p><AiDisclaimerBadge compact /></div>
                </div>
              ) : <p className="text-sm text-muted">{t('workspace.no_analysis')}</p>}
              <Tabs value={tab} onValueChange={setTab}>
                <TabsList>
                  <TabsTrigger value="features">{t('workspace.tabs.features')}</TabsTrigger>
                  <TabsTrigger value="diff">{t('workspace.tabs.diff')}</TabsTrigger>
                  <TabsTrigger value="drugs">{t('workspace.tabs.drugs')}</TabsTrigger>
                  <TabsTrigger value="history">{t('workspace.tabs.history')}</TabsTrigger>
                </TabsList>
                <TabsContent value="features"><FeatureTable exam={exam} /></TabsContent>
                <TabsContent value="diff">
                  {!isDoctor && !isFullReport(exam.report) ? (exam.report ? <div className="space-y-2 text-sm"><p>{exam.report.summary}</p>{exam.report.red_flags.length > 0 && <Alert tone="danger">{exam.report.red_flags.join('; ')}</Alert>}<AiDisclaimerBadge /><p className="text-xs text-muted">{t('workspace.nurse_hidden')}</p></div> : <p className="text-sm text-muted">{t('workspace.nurse_hidden')}</p>) : <Differential report={exam.report} canRegen={isDoctor && !locked} examId={id} />}
                </TabsContent>
                <TabsContent value="drugs">
                  {nurseHidden ? <Alert tone="info">{t('workspace.drugs_pending_doctor')}</Alert> : <DrugRecommendationPanel examId={id} prescription={exam.prescription} canEdit={isDoctor} locked={locked} />}
                </TabsContent>
                <TabsContent value="history"><HistoryTab exam={exam} doctor={isDoctor} /></TabsContent>
              </Tabs>
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}
