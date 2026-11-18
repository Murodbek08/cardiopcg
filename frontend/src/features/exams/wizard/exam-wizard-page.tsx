import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslation } from 'react-i18next';
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import { IconAlertTriangle, IconCheck, IconTrash, IconUpload } from '@tabler/icons-react';
import {
  Alert, AudioWaveform, Badge, Button, Card, CardBody, CheckboxField, ErrorState, Field, FileDropzone, Input, PageHeader, RadioGroup, RadioItem, Select, Skeleton, Textarea,
  ALL, ApiError, cn, errorMessage, formatBytes, formatDuration, get, toast, useDebounce, usePermission,
} from '@/shared';
import type { ExamDetail, PatientListItem, Paged, Recording } from '@/shared/api/types';
import {
  deleteRecording, uploadRecording, useAnalyze, useCreateExam, useDoctors, useExam, usePublicSettings, useUpdateExam,
} from '../api';
import { AUDIO_EXT, IMAGE_EXT, checkAudioDuration, evaluateQuality, vitalWarnings, vitalsSchema, type VitalsValues } from '../logic';

// ------------------------------------------------------------------ wizard store (only ids/step: never files or PHI)
interface WizardState {
  step: number;
  examId: string | null;
  patientId: string | null;
  set: (p: Partial<Pick<WizardState, 'step' | 'examId' | 'patientId'>>) => void;
  reset: () => void;
}
export const useExamWizardStore = create<WizardState>()(
  persist(
    (set) => ({ step: 0, examId: null, patientId: null, set: (p) => set(p), reset: () => set({ step: 0, examId: null, patientId: null }) }),
    { name: 'cardiopcg-exam-wizard', storage: createJSONStorage(() => sessionStorage) },
  ),
);

export const SYMPTOMS = ['dyspnea', 'chest_pain', 'palpitations', 'syncope', 'edema', 'fatigue', 'dizziness', 'cough', 'fever', 'orthopnea'] as const;
export const SITES = ['aortic', 'pulmonic', 'tricuspid', 'mitral', 'erb', 'apex'] as const;

function useDurationProbe() {
  return (file: File) =>
    new Promise<number | null>((resolve) => {
      const url = URL.createObjectURL(file);
      const a = new Audio();
      a.preload = 'metadata';
      const giveUp = setTimeout(() => {
        URL.revokeObjectURL(url);
        resolve(null);
      }, 3000);
      a.onloadedmetadata = () => {
        clearTimeout(giveUp);
        URL.revokeObjectURL(url);
        resolve(Number.isFinite(a.duration) ? a.duration : null);
      };
      a.onerror = () => {
        clearTimeout(giveUp);
        URL.revokeObjectURL(url);
        resolve(null);
      };
      a.src = url;
    });
}

// ------------------------------------------------------------------ step 1: patient
function PatientStep({ onNext }: { onNext: () => void }) {
  const { t } = useTranslation('exams');
  const st = useExamWizardStore();
  const [q, setQ] = useState('');
  const dq = useDebounce(q, 300);
  const search = useQuery({
    queryKey: ['wizard', 'patients', dq],
    queryFn: ({ signal }) => get<Paged<PatientListItem>>('/patients', { q: dq, limit: 6 }, signal),
    enabled: dq.trim().length >= 2,
  });
  const selected = useQuery({
    queryKey: ['wizard', 'patient', st.patientId],
    queryFn: ({ signal }) => get<{ id: string; full_name: string; mrn: string; age: number; allergies: { id: string; substance: string; is_active: boolean }[] }>(`/patients/${st.patientId}`, undefined, signal),
    enabled: !!st.patientId,
  });
  const [complaints, setComplaints] = useState('');
  const [symptoms, setSymptoms] = useState<string[]>([]);
  const [priority, setPriority] = useState<'routine' | 'urgent' | 'emergency'>('routine');
  const [doctorId, setDoctorId] = useState<string>(ALL);
  const doctors = useDoctors();
  const create = useCreateExam();
  const update = useUpdateExam(st.examId ?? '');
  const busy = create.isPending || update.isPending;

  const go = async () => {
    if (!st.patientId) return;
    try {
      const body = { patient_id: st.patientId, complaints: complaints || null, symptoms, priority, assigned_doctor_id: doctorId === ALL ? null : doctorId };
      if (st.examId) await update.mutateAsync({ complaints: body.complaints, symptoms, priority, assigned_doctor_id: body.assigned_doctor_id });
      else {
        const exam = await create.mutateAsync(body);
        st.set({ examId: exam.id });
      }
      onNext();
    } catch (e) {
      toast.error(errorMessage(e, t as never));
    }
  };

  return (
    <div className="space-y-5">
      {selected.data ? (
        <Card>
          <CardBody className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-h3 font-semibold">{selected.data.full_name}</p>
              <p className="text-sm text-muted">{selected.data.mrn} &middot; {selected.data.age}</p>
              {selected.data.allergies.some((a) => a.is_active) && (
                <p className="mt-2 flex flex-wrap gap-1">{selected.data.allergies.filter((a) => a.is_active).map((a) => <Badge key={a.id} tone="warning" icon={IconAlertTriangle}>{a.substance}</Badge>)}</p>
              )}
            </div>
            {!st.examId && <Button variant="outline" onClick={() => st.set({ patientId: null })}>{t('wizard.change_patient')}</Button>}
          </CardBody>
        </Card>
      ) : (
        <div>
          <Field label={t('wizard.search_patient')}><Input touch value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('wizard.search_placeholder')} autoFocus /></Field>
          {search.isFetching && <Skeleton className="mt-2 h-12" />}
          {search.data && (
            <ul className="mt-2 divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
              {search.data.items.length === 0 && <li className="px-4 py-3 text-sm text-muted">{t('empty_filtered')}</li>}
              {search.data.items.map((p) => (
                <li key={p.id}>
                  <button type="button" className="flex min-h-14 w-full items-center justify-between px-4 text-left hover:bg-surface-2" onClick={() => st.set({ patientId: p.id })}>
                    <span className="font-medium">{p.full_name}</span>
                    <span className="text-xs text-muted">{p.mrn} &middot; {p.age}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <fieldset>
        <legend className="mb-2 text-sm font-medium">{t('wizard.symptoms')}</legend>
        <div className="flex flex-wrap gap-2">
          {SYMPTOMS.map((s) => {
            const on = symptoms.includes(s);
            return (
              <button key={s} type="button" aria-pressed={on} onClick={() => setSymptoms((x) => (on ? x.filter((y) => y !== s) : [...x, s]))}
                className={cn('min-h-11 rounded-full border px-4 text-sm', on ? 'border-brand-600 bg-brand-50 font-medium text-brand-800 dark:bg-brand-900/40 dark:text-brand-100' : 'border-border')}>
                {on && <IconCheck size={14} className="mr-1 inline" aria-hidden />}{t(`symptom.${s}`)}
              </button>
            );
          })}
        </div>
      </fieldset>
      <Field label={t('complaints')}><Textarea rows={3} value={complaints} onChange={(e) => setComplaints(e.target.value)} maxLength={5000} /></Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('wizard.priority')}>
          <Select touch value={priority} onValueChange={(v) => setPriority(v as typeof priority)} options={(['routine', 'urgent', 'emergency'] as const).map((p) => ({ value: p, label: t(`priority.${p}`) }))} />
        </Field>
        <Field label={t('wizard.assign_doctor')}>
          <Select touch value={doctorId} onValueChange={setDoctorId} options={[{ value: ALL, label: t('wizard.any_doctor') }, ...(doctors.data ?? []).map((d) => ({ value: d.id, label: d.full_name }))]} />
        </Field>
      </div>
      <div className="flex justify-end"><Button size="touch" onClick={() => void go()} disabled={!st.patientId} loading={busy}>{t('wizard.actions.next')}</Button></div>
    </div>
  );
}

// ------------------------------------------------------------------ step 2: vitals
function VitalsStep({ exam, onBack, onNext }: { exam: ExamDetail; onBack: () => void; onNext: () => void }) {
  const { t } = useTranslation('exams');
  const update = useUpdateExam(exam.id);
  const { register, handleSubmit, watch, formState: { errors } } = useForm<Record<string, unknown>, unknown, VitalsValues>({
    resolver: zodResolver(vitalsSchema),
    defaultValues: { heart_rate_bpm: exam.heart_rate_bpm ?? '', bp_systolic: exam.bp_systolic ?? '', bp_diastolic: exam.bp_diastolic ?? '', spo2_pct: exam.spo2_pct ?? '', temperature_c: exam.temperature_c ?? '', weight_kg_at_exam: exam.weight_kg_at_exam ?? '' },
  });
  const values = watch();
  const warn = vitalWarnings(Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v === '' || v == null ? undefined : Number(v)])));
  const fields: [keyof VitalsValues, string, string][] = [
    ['bp_systolic', t('wizard.vitals.sys'), 'mmHg'], ['bp_diastolic', t('wizard.vitals.dia'), 'mmHg'], ['heart_rate_bpm', t('vitals.hr'), 'bpm'],
    ['spo2_pct', t('vitals.spo2'), '%'], ['temperature_c', t('vitals.temp'), 'C'], ['weight_kg_at_exam', t('wizard.vitals.weight'), 'kg'],
  ];
  const submit = handleSubmit(async (v) => {
    try {
      const body = Object.fromEntries(Object.entries(v).filter(([, x]) => x !== undefined));
      if (Object.keys(body).length) await update.mutateAsync(body);
      onNext();
    } catch (e) {
      toast.error(errorMessage(e, t as never));
    }
  });
  return (
    <form onSubmit={submit} noValidate className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {fields.map(([k, label, unit]) => (
          <Field key={k} label={`${label} (${unit})`} error={errors[k]?.message ? (k === 'bp_systolic' && errors[k]?.message === 'bp' ? t('wizard.vitals.bp_order') : t('wizard.vitals.out_of_bounds')) : undefined}
            >
            <Input touch type="number" step="any" inputMode="decimal" {...register(k)} />
          </Field>
        ))}
      </div>
      {warn.length > 0 && <Alert tone="warning" title={t('wizard.vitals.confirm_title')}>{t('wizard.vitals.confirm_body', { fields: warn.map((w) => t(`wizard.vitals.names.${w}`)).join(', ') })}</Alert>}
      <div className="flex justify-between"><Button size="touch" variant="outline" onClick={onBack}>{t('wizard.actions.back')}</Button><Button type="submit" size="touch" loading={update.isPending}>{t('wizard.actions.next')}</Button></div>
    </form>
  );
}

// ------------------------------------------------------------------ step 3: recordings
interface Pending { file: File; url: string; duration: number | null; progress: number; error?: string }

export function QualityPanel({ rec, minSnr }: { rec: Recording; minSnr?: number }) {
  const { t } = useTranslation('exams');
  const q = evaluateQuality(rec, minSnr);
  const tone = q.level === 'good' ? 'success' : q.level === 'low' ? 'warning' : 'danger';
  return (
    <Alert tone={tone} title={t(`wizard.quality.${q.level}`)}>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
        <div><dt className="text-muted">{t('wizard.quality.duration')}</dt><dd className="font-mono-num">{formatDuration(rec.duration_sec)}</dd></div>
        <div><dt className="text-muted">SNR</dt><dd className="font-mono-num">{rec.snr_db != null ? `${rec.snr_db} dB` : '-'}</dd></div>
        <div><dt className="text-muted">{t('wizard.quality.score')}</dt><dd className="font-mono-num">{rec.quality_score != null ? rec.quality_score : '-'}</dd></div>
        <div><dt className="text-muted">{t('wizard.quality.size')}</dt><dd className="font-mono-num">{formatBytes(rec.size_bytes)}</dd></div>
      </dl>
      {q.reasons.length > 0 && <p className="mt-1 text-sm">{q.reasons.map((r) => t(`wizard.quality.reason.${r}`, { defaultValue: r })).join('; ')}</p>}
      {q.level !== 'good' && <p className="mt-1 text-sm font-medium">{t('wizard.quality.rerecord')}</p>}
    </Alert>
  );
}

function RecordingStep({ exam, onBack, onNext }: { exam: ExamDetail; onBack: () => void; onNext: () => void }) {
  const { t } = useTranslation('exams');
  const settings = usePublicSettings();
  const maxMb = Number(settings.data?.['upload.max_audio_mb'] ?? 25);
  const minDur = Number(settings.data?.['audio.min_duration_sec'] ?? 5);
  const maxDur = Number(settings.data?.['audio.max_duration_sec'] ?? 120);
  const probe = useDurationProbe();
  const qc = useExam(exam.id);
  const [site, setSite] = useState<string>('mitral');
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [override, setOverride] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const audio = exam.recordings.filter((r) => r.kind === 'audio');
  const images = exam.recordings.filter((r) => r.kind === 'other_image');
  const siteTaken = audio.some((r) => r.site === site);

  useEffect(() => () => { if (pending) URL.revokeObjectURL(pending.url); }, [pending]);

  const choose = async (files: File[]) => {
    const f = files[0];
    if (!f) return;
    const duration = await probe(f);
    const problem = duration != null ? checkAudioDuration(duration, minDur, maxDur) : null;
    setPending({ file: f, url: URL.createObjectURL(f), duration, progress: 0, error: problem ? t(`wizard.audio_${problem}`, { min: minDur, max: maxDur }) : undefined });
  };

  const upload = async () => {
    if (!pending) return;
    setBusy(true);
    abort.current = new AbortController();
    try {
      await uploadRecording(exam.id, pending.file, { site, replace: siteTaken, signal: abort.current.signal, onProgress: (p) => setPending((x) => (x ? { ...x, progress: p } : x)) });
      toast.success(t('wizard.uploaded'));
      setPending(null);
      await qc.refetch();
    } catch (e) {
      setPending((x) => (x ? { ...x, error: errorMessage(e, t as never) } : x));
    } finally {
      setBusy(false);
    }
  };

  const uploadImage = async (files: File[]) => {
    try {
      for (const f of files) await uploadRecording(exam.id, f, { kind: 'other_image' });
      await qc.refetch();
    } catch (e) {
      toast.error(errorMessage(e, t as never));
    }
  };
  const remove = async (rid: string) => {
    try {
      await deleteRecording(rid);
      await qc.refetch();
    } catch (e) {
      toast.error(errorMessage(e, t as never));
    }
  };

  const levels = audio.map((r) => evaluateQuality(r).level);
  const usable = audio.length > 0 && !levels.every((l) => l === 'unusable');
  const hasLow = levels.includes('low');
  const canNext = usable && (!hasLow || override);

  return (
    <div className="space-y-5">
      <fieldset>
        <legend className="mb-2 text-sm font-medium">{t('wizard.site')}</legend>
        <RadioGroup value={site} onValueChange={setSite} aria-label={t('wizard.site')}>
          {SITES.map((s) => <RadioItem key={s} value={s} label={t(`clinical:site.${s}`)} />)}
        </RadioGroup>
        {siteTaken && <p className="mt-1 text-xs text-warning-500">{t('wizard.site_taken')}</p>}
      </fieldset>

      {!pending ? (
        <FileDropzone accept={[...AUDIO_EXT]} maxSizeBytes={maxMb * 1024 * 1024} onFiles={(f) => void choose(f)} onReject={(r) => toast.error(r[0]?.reason === 'size' ? t('wizard.too_large', { mb: maxMb }) : t('wizard.bad_format'))} hint={t('wizard.audio_hint', { min: minDur, max: maxDur })} />
      ) : (
        <Card>
          <CardBody className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-medium">{pending.file.name} <span className="text-sm text-muted">{formatBytes(pending.file.size)}</span></p>
              <Button size="sm" variant="ghost" onClick={() => { abort.current?.abort(); setPending(null); }}><IconTrash size={16} aria-hidden /> {t('wizard.cancel_file')}</Button>
            </div>
            <AudioWaveform objectUrl={pending.url} height={96} />
            {pending.error && <Alert tone="danger">{pending.error}</Alert>}
            {busy && <div role="progressbar" aria-valuenow={pending.progress} aria-valuemin={0} aria-valuemax={100} className="h-2 overflow-hidden rounded-full bg-border"><div className="h-full bg-brand-600 transition-all" style={{ width: `${pending.progress}%` }} /></div>}
            <div className="flex justify-end"><Button size="touch" onClick={() => void upload()} loading={busy} disabled={!!pending.error}><IconUpload size={18} aria-hidden /> {t('wizard.upload')}</Button></div>
          </CardBody>
        </Card>
      )}

      {audio.map((r) => (
        <div key={r.id} className="space-y-2 rounded-lg border border-border p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="font-medium">{r.site ? t(`clinical:site.${r.site}`) : r.original_filename} <span className="text-sm text-muted">{r.original_filename}</span></p>
            <Button size="icon-sm" variant="ghost" aria-label={t('common:actions.delete')} onClick={() => void remove(r.id)}><IconTrash size={16} aria-hidden /></Button>
          </div>
          <QualityPanel rec={r} />
        </div>
      ))}

      <details className="rounded-lg border border-border p-3">
        <summary className="cursor-pointer text-sm font-medium">{t('wizard.images')} ({images.length})</summary>
        <div className="mt-3 space-y-2">
          <FileDropzone multiple accept={[...IMAGE_EXT]} maxSizeBytes={10 * 1024 * 1024} onFiles={(f) => void uploadImage(f)} onReject={() => toast.error(t('wizard.bad_format'))} />
          {images.map((r) => <p key={r.id} className="flex items-center justify-between text-sm">{r.original_filename}<Button size="icon-sm" variant="ghost" aria-label={t('common:actions.delete')} onClick={() => void remove(r.id)}><IconTrash size={14} aria-hidden /></Button></p>)}
        </div>
      </details>

      {hasLow && usable && <CheckboxField label={t('wizard.send_anyway')} checked={override} onCheckedChange={(c) => setOverride(c === true)} />}
      {audio.length > 0 && !usable && <Alert tone="danger">{t('wizard.unusable_block')}</Alert>}
      <div className="flex justify-between"><Button size="touch" variant="outline" onClick={onBack}>{t('wizard.actions.back')}</Button><Button size="touch" disabled={!canNext} onClick={onNext}>{t('wizard.actions.next')}</Button></div>
    </div>
  );
}

// ------------------------------------------------------------------ step 4: confirm
function ConfirmStep({ exam, onBack }: { exam: ExamDetail; onBack: () => void }) {
  const { t } = useTranslation('exams');
  const navigate = useNavigate();
  const analyze = useAnalyze(exam.id);
  const st = useExamWizardStore();
  const [consent, setConsent] = useState(false);
  const go = async () => {
    try {
      await analyze.mutateAsync(undefined);
    } catch (e) {
      // 409: the backend already started (or finished) the analysis automatically after the audio upload
      // (analysis.auto_start). That is not an error for the nurse - just continue to the progress page.
      if (!(e instanceof ApiError && e.status === 409)) {
        toast.error(errorMessage(e, t as never));
        return;
      }
    }
    st.reset();
    void navigate({ to: '/exams/$id/progress', params: { id: exam.id } } as never);
  };
  return (
    <div className="space-y-5">
      <Card><CardBody>
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <div><dt className="text-muted">{t('columns.patient')}</dt><dd className="font-medium">{exam.patient.full_name} ({exam.patient.mrn})</dd></div>
          <div><dt className="text-muted">{t('columns.recordings')}</dt><dd className="font-medium">{exam.recordings.filter((r) => r.kind === 'audio').length}</dd></div>
          <div><dt className="text-muted">{t('vitals.bp')}</dt><dd className="font-mono-num">{exam.bp_systolic && exam.bp_diastolic ? `${exam.bp_systolic}/${exam.bp_diastolic}` : '-'}</dd></div>
          <div><dt className="text-muted">{t('vitals.hr')}</dt><dd className="font-mono-num">{exam.heart_rate_bpm ?? '-'}</dd></div>
        </dl>
      </CardBody></Card>
      <CheckboxField label={t('wizard.consent')} checked={consent} onCheckedChange={(c) => setConsent(c === true)} />
      <div className="flex justify-between"><Button size="touch" variant="outline" onClick={onBack}>{t('wizard.actions.back')}</Button><Button size="touch" disabled={!consent} loading={analyze.isPending} onClick={() => void go()}>{t('wizard.actions.start_analysis')}</Button></div>
    </div>
  );
}

export function ExamWizardPage() {
  const { t } = useTranslation('exams');
  const st = useExamWizardStore();
  const search = useSearch({ strict: false }) as { patientId?: string };
  const canCreate = usePermission('exam:create');
  const exam = useExam(st.examId ?? '');
  const examQ = st.examId ? exam : null;
  useEffect(() => {
    if (search.patientId && search.patientId !== st.patientId && !st.examId) st.set({ patientId: search.patientId });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search.patientId]);

  const steps = useMemo(() => ['patient', 'vitals', 'recording', 'confirm'] as const, []);
  if (!canCreate) return <ErrorState error={new Error(t('errors:forbidden'))} />;
  const cur = st.step;
  const e = examQ?.data;

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title={t('wizard.title')} actions={st.examId ? <Button variant="ghost" size="sm" onClick={() => st.reset()}>{t('wizard.restart')}</Button> : undefined} />
      <ol className="mb-6 flex items-center gap-2" aria-label={t('wizard.title')}>
        {steps.map((s, i) => (
          <li key={s} aria-current={i === cur ? 'step' : undefined} className={cn('flex flex-1 items-center gap-2 rounded-lg border px-3 py-2 text-sm', i === cur ? 'border-brand-600 bg-brand-50 font-semibold dark:bg-brand-900/30' : i < cur ? 'border-success-500/40 text-success-500' : 'border-border text-muted')}>
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-surface-2 text-xs font-bold text-foreground">{i < cur ? <IconCheck size={14} aria-hidden /> : i + 1}</span>
            <span className="hidden sm:inline">{t(`wizard.steps.${s}`)}</span>
          </li>
        ))}
      </ol>
      <Card><CardBody>
        {cur === 0 && <PatientStep onNext={() => st.set({ step: 1 })} />}
        {cur > 0 && examQ?.isLoading && <Skeleton className="h-40" />}
        {cur > 0 && examQ?.isError && <ErrorState error={examQ.error} onRetry={() => void examQ.refetch()} />}
        {cur > 0 && !st.examId && <Alert tone="warning">{t('wizard.no_exam')}</Alert>}
        {cur === 1 && e && <VitalsStep exam={e} onBack={() => st.set({ step: 0 })} onNext={() => st.set({ step: 2 })} />}
        {cur === 2 && e && <RecordingStep exam={e} onBack={() => st.set({ step: 1 })} onNext={() => st.set({ step: 3 })} />}
        {cur === 3 && e && <ConfirmStep exam={e} onBack={() => st.set({ step: 2 })} />}
      </CardBody></Card>
    </div>
  );
}
