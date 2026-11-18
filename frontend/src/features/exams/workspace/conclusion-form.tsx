import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { IconDeviceFloppy, IconSignature } from '@tabler/icons-react';
import { Alert, Button, Card, CardBody, CardHeader, ConfirmDialog, Field, Input, Select, StatusBadge, Textarea, errorMessage, formatDateTime, toast, today } from '@/shared';
import type { AnalysisResult, Conclusion, ConclusionInput, ExamStatus, PrescriptionItem } from '@/shared/api/types';
import { useConclusionActions } from '../api';
import { conclusionLocked, signBlockers, suggestAgreement } from '../logic';

const CLASSES = ['normal', 'murmur', 'extra_heart_sound', 'artifact', 'undetermined'] as const;
const SEVERITIES = ['none', 'mild', 'moderate', 'severe', 'critical'] as const;
const ICD = /^[A-Z]\d{2}(\.\d{1,2})?$/;

interface Form {
  diagnosis_text: string;
  recommendations: string;
  icd: string;
  final_pcg_class: string;
  final_severity: string;
  agreement_with_ai: 'agree' | 'partial' | 'disagree';
  disagreement_reason: string;
  follow_up_date: string;
  referred_to: string;
}

function initial(c: Conclusion | null, a: AnalysisResult | null): Form {
  return {
    diagnosis_text: c?.diagnosis_text ?? '',
    recommendations: c?.recommendations ?? '',
    icd: (c?.icd10_codes ?? []).join(', '),
    final_pcg_class: c?.final_pcg_class ?? a?.pcg_class ?? 'normal',
    final_severity: c?.final_severity ?? a?.severity ?? 'none',
    agreement_with_ai: c?.agreement_with_ai ?? 'agree',
    disagreement_reason: c?.disagreement_reason ?? '',
    follow_up_date: c?.follow_up_date ?? '',
    referred_to: c?.referred_to ?? '',
  };
}

export const parseIcd = (s: string) => s.split(/[,;\s]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);

function toInput(f: Form): ConclusionInput {
  return {
    diagnosis_text: f.diagnosis_text,
    icd10_codes: parseIcd(f.icd),
    final_pcg_class: f.final_pcg_class as ConclusionInput['final_pcg_class'],
    final_severity: f.final_severity as ConclusionInput['final_severity'],
    agreement_with_ai: f.agreement_with_ai,
    disagreement_reason: f.disagreement_reason.trim() || null,
    recommendations: f.recommendations,
    follow_up_date: f.follow_up_date || null,
    referred_to: f.referred_to.trim() || null,
  };
}

/** Doctor conclusion: draft autosave (10 s), sign (locks), amend (new version with a reason). */
export function ConclusionForm({ examId, status, conclusion, analysis, items }: { examId: string; status: ExamStatus; conclusion: Conclusion | null; analysis: AnalysisResult | null; items: Pick<PrescriptionItem, 'status'>[] }) {
  const { t } = useTranslation('exams');
  const act = useConclusionActions(examId);
  const locked = conclusionLocked(conclusion, status);
  const [f, setF] = useState<Form>(() => initial(conclusion, analysis));
  const [dirty, setDirty] = useState(false);
  const [amending, setAmending] = useState(false);
  const [confirmSign, setConfirmSign] = useState(false);
  const [amendReason, setAmendReason] = useState('');
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const last = useRef(f);
  useEffect(() => {
    last.current = f;
  });

  useEffect(() => {
    if (!dirty && conclusion) setF(initial(conclusion, analysis));
  }, [conclusion, analysis, dirty]);

  const upd = <K extends keyof Form>(k: K, v: Form[K]) => {
    setF((x) => ({ ...x, [k]: v }));
    setDirty(true);
  };

  const readOnly = locked && !amending;
  const badIcd = parseIcd(f.icd).filter((c) => !ICD.test(c));
  const blockers = useMemo(
    () => signBlockers({ diagnosis_text: f.diagnosis_text, recommendations: f.recommendations, icd10_codes: parseIcd(f.icd), agreement_with_ai: f.agreement_with_ai, disagreement_reason: f.disagreement_reason, follow_up_date: f.follow_up_date || null }, items, !!analysis, today()),
    [f, items, analysis],
  );
  const canDraft = f.diagnosis_text.trim().length > 0 && badIcd.length === 0 && !readOnly;

  const saveDraft = async (quiet = false) => {
    try {
      await act.save.mutateAsync(toInput(last.current));
      setDirty(false);
      setSavedAt(new Date());
      if (!quiet) toast.success(t('conclusion.saved'));
    } catch (e) {
      if (!quiet) toast.error(errorMessage(e, t as never));
    }
  };

  // autosave every 10 s while dirty
  useEffect(() => {
    if (!dirty || readOnly || !canDraft) return;
    const id = setTimeout(() => void saveDraft(true), 10_000);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f, dirty, readOnly, canDraft]);

  // Ctrl+S saves the draft
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's' && canDraft) {
        e.preventDefault();
        void saveDraft();
      }
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canDraft]);

  const sign = async () => {
    try {
      await act.save.mutateAsync(toInput(f));
      await act.sign.mutateAsync();
      setDirty(false);
      setConfirmSign(false);
      toast.success(t('conclusion.signed'));
    } catch (e) {
      setConfirmSign(false);
      toast.error(errorMessage(e, t as never));
    }
  };
  const amend = async () => {
    try {
      await act.amend.mutateAsync({ ...toInput(f), amend_reason: amendReason.trim() });
      setAmending(false);
      setAmendReason('');
      setDirty(false);
      toast.success(t('conclusion.amended'));
    } catch (e) {
      toast.error(errorMessage(e, t as never));
    }
  };

  return (
    <Card>
      <CardHeader title={t('conclusion.title')} description={conclusion?.signed_at ? `${t('conclusion.signed_at')}: ${formatDateTime(conclusion.signed_at)} (v${conclusion.version})` : savedAt ? `${t('conclusion.autosaved')} ${formatDateTime(savedAt)}` : undefined}
        actions={conclusion ? <StatusBadge kind="job" value={conclusion.status === 'draft' ? 'pending' : 'succeeded'} /> : undefined} />
      <CardBody className="space-y-4">
        {readOnly && <Alert tone="success">{t('conclusion.locked')}</Alert>}
        <Field label={t('conclusion.diagnosis')} required hint={`${f.diagnosis_text.trim().length}/20`}><Textarea rows={4} value={f.diagnosis_text} disabled={readOnly} onChange={(e) => upd('diagnosis_text', e.target.value)} /></Field>
        <div className="grid gap-4 md:grid-cols-3">
          <Field label={t('conclusion.final_class')}>
            <Select value={f.final_pcg_class} disabled={readOnly} onValueChange={(v) => { upd('final_pcg_class', v); if (analysis) upd('agreement_with_ai', suggestAgreement(analysis.pcg_class, v)); }} options={CLASSES.map((c) => ({ value: c, label: t(`clinical:pcg_class.${c}`) }))} />
          </Field>
          <Field label={t('conclusion.final_severity')}>
            <Select value={f.final_severity} disabled={readOnly} onValueChange={(v) => upd('final_severity', v)} options={SEVERITIES.map((c) => ({ value: c, label: t(`clinical:severity.${c}`) }))} />
          </Field>
          <Field label={t('conclusion.agreement')} hint={t('conclusion.agreement_hint')}>
            <Select value={f.agreement_with_ai} disabled={readOnly} onValueChange={(v) => upd('agreement_with_ai', v as Form['agreement_with_ai'])} options={(['agree', 'partial', 'disagree'] as const).map((c) => ({ value: c, label: t(`conclusion.agreement_${c}`) }))} />
          </Field>
        </div>
        {f.agreement_with_ai !== 'agree' && <Field label={t('conclusion.disagreement_reason')} required><Textarea rows={2} value={f.disagreement_reason} disabled={readOnly} onChange={(e) => upd('disagreement_reason', e.target.value)} /></Field>}
        <div className="grid gap-4 md:grid-cols-2">
          <Field label={t('conclusion.icd')} required hint="I34.0, I10" error={badIcd.length ? t('conclusion.icd_bad', { codes: badIcd.join(', ') }) : undefined}><Input value={f.icd} disabled={readOnly} onChange={(e) => upd('icd', e.target.value)} /></Field>
          <Field label={t('conclusion.follow_up')} error={blockers.includes('followup_past') ? t('conclusion.followup_past') : undefined}><Input type="date" min={today()} value={f.follow_up_date} disabled={readOnly} onChange={(e) => upd('follow_up_date', e.target.value)} /></Field>
        </div>
        <Field label={t('conclusion.recommendations')} required><Textarea rows={3} value={f.recommendations} disabled={readOnly} onChange={(e) => upd('recommendations', e.target.value)} /></Field>
        <Field label={t('conclusion.referred_to')}><Input value={f.referred_to} disabled={readOnly} onChange={(e) => upd('referred_to', e.target.value)} /></Field>

        {!readOnly && blockers.length > 0 && (
          <Alert tone="warning" title={t('conclusion.cannot_sign')}>
            <ul className="list-disc pl-5">{blockers.map((b) => <li key={b}>{t(`conclusion.blockers.${b}`)}</li>)}</ul>
          </Alert>
        )}
        {amending && <Field label={t('conclusion.amend_reason')} required><Textarea rows={2} value={amendReason} onChange={(e) => setAmendReason(e.target.value)} /></Field>}

        <div className="flex flex-wrap justify-end gap-2">
          {readOnly && <Button variant="outline" onClick={() => setAmending(true)}>{t('conclusion.amend')}</Button>}
          {amending && <><Button variant="outline" onClick={() => { setAmending(false); setDirty(false); }}>{t('common:actions.cancel')}</Button><Button loading={act.amend.isPending} disabled={amendReason.trim().length < 3 || blockers.filter((b) => b !== 'pending_items').length > 0} onClick={() => void amend()}>{t('conclusion.amend_submit')}</Button></>}
          {!locked && (
            <>
              <Button variant="outline" disabled={!canDraft || !dirty} loading={act.save.isPending} onClick={() => void saveDraft()}><IconDeviceFloppy size={18} aria-hidden /> {t('conclusion.save_draft')}</Button>
              <Button disabled={blockers.length > 0 || badIcd.length > 0} loading={act.sign.isPending} onClick={() => setConfirmSign(true)}><IconSignature size={18} aria-hidden /> {t('conclusion.sign')}</Button>
            </>
          )}
        </div>
      </CardBody>
      <ConfirmDialog open={confirmSign} onOpenChange={setConfirmSign} title={t('conclusion.sign')} description={t('conclusion.sign_body')} loading={act.sign.isPending || act.save.isPending} onConfirm={sign} />
    </Card>
  );
}
