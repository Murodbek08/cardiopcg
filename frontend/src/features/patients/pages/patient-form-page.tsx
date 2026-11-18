import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from '@tanstack/react-router';
import { Controller, useFieldArray, useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { IconPlus, IconTrash } from '@tabler/icons-react';
import {
  Alert, Button, Card, CardBody, CardHeader, CheckboxField, Dialog, ErrorState, Field, Input, PageHeader, Select, SkeletonRows, Textarea, ALL,
  del, errorMessage, fieldErrorMap, get, isApiError, post, qk, toast, usePermission,
} from '@/shared';
import { safeStorage } from '@/shared/lib/safe-storage';
import type { PatientDetail } from '@/shared/api/types';
import { bmi, bmiBand, createPatientSchema, emptyPatient, patientSchema, toPatientBody, type PatientFormInput, type PatientFormOutput } from '../schemas';
import { usePatient } from '../api';
import { api } from '@/shared/api/client';

const DRAFT_KEY = 'cardiopcg-patient-draft';
const DRAFT_TTL = 24 * 3600_000;
const BLOOD = ['O+', 'O-', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'unknown'] as const;

function loadDraft(): PatientFormInput | null {
  try {
    const raw = safeStorage.get(DRAFT_KEY);
    if (!raw) return null;
    const { at, values } = JSON.parse(raw) as { at: number; values: PatientFormInput };
    return Date.now() - at < DRAFT_TTL ? values : null;
  } catch {
    return null;
  }
}

function SubRecordLists({ patientId, detail }: { patientId: string; detail: PatientDetail }) {
  const { t } = useTranslation('patients');
  const qc = useQueryClient();
  const inv = () => void qc.invalidateQueries({ queryKey: qk.patients.detail(patientId) });
  const [allergy, setAllergy] = useState({ substance: '', reaction: '', severity: 'moderate' });
  const [med, setMed] = useState({ drug_name: '', dose: '', frequency: '' });
  const [hist, setHist] = useState({ kind: 'chronic', title: '', icd10_code: '' });
  const add = useMutation({ mutationFn: (v: { path: string; body: Record<string, unknown> }) => post(`/patients/${patientId}/${v.path}`, v.body), onSuccess: inv, onError: (e) => toast.error(errorMessage(e, t as never)) });
  const archive = useMutation({ mutationFn: (path: string) => del(`/patients/${patientId}/${path}`), onSuccess: inv, onError: (e) => toast.error(errorMessage(e, t as never)) });
  const row = (key: string, label: string, onRemove: () => void) => (
    <li key={key} className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-1.5 text-sm">{label}<Button size="icon-sm" variant="ghost" aria-label={t('common:actions.delete')} onClick={onRemove}><IconTrash size={14} aria-hidden /></Button></li>
  );
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <Card><CardHeader title={t('form.allergies')} /><CardBody className="space-y-3">
        <ul className="space-y-1">{detail.allergies.filter((a) => a.is_active).map((a) => row(a.id, `${a.substance} (${a.severity})`, () => archive.mutate(`allergies/${a.id}`)))}</ul>
        <Input aria-label={t('form.substance')} placeholder={t('form.substance')} value={allergy.substance} onChange={(e) => setAllergy({ ...allergy, substance: e.target.value })} />
        <Input aria-label={t('form.reaction')} placeholder={t('form.reaction')} value={allergy.reaction} onChange={(e) => setAllergy({ ...allergy, reaction: e.target.value })} />
        <Select value={allergy.severity} onValueChange={(v) => setAllergy({ ...allergy, severity: v })} options={(['mild', 'moderate', 'severe', 'anaphylaxis'] as const).map((s) => ({ value: s, label: t(`form.severity.${s}`) }))} />
        <Button size="sm" disabled={!allergy.substance.trim()} loading={add.isPending} onClick={() => add.mutate({ path: 'allergies', body: { substance: allergy.substance.trim(), reaction: allergy.reaction || null, severity: allergy.severity } }, { onSuccess: () => setAllergy({ substance: '', reaction: '', severity: 'moderate' }) })}><IconPlus size={14} aria-hidden /> {t('form.add')}</Button>
      </CardBody></Card>
      <Card><CardHeader title={t('form.medications')} /><CardBody className="space-y-3">
        <ul className="space-y-1">{detail.current_medications.filter((m) => m.is_active).map((m) => row(m.id, `${m.drug_name} ${m.dose ?? ''}`, () => archive.mutate(`medications/${m.id}`)))}</ul>
        <Input aria-label={t('form.drug')} placeholder={t('form.drug')} value={med.drug_name} onChange={(e) => setMed({ ...med, drug_name: e.target.value })} />
        <Input aria-label={t('form.dose')} placeholder={t('form.dose')} value={med.dose} onChange={(e) => setMed({ ...med, dose: e.target.value })} />
        <Input aria-label={t('form.frequency')} placeholder={t('form.frequency')} value={med.frequency} onChange={(e) => setMed({ ...med, frequency: e.target.value })} />
        <Button size="sm" disabled={!med.drug_name.trim()} loading={add.isPending} onClick={() => add.mutate({ path: 'medications', body: { drug_name: med.drug_name.trim(), dose: med.dose || null, frequency: med.frequency || null } }, { onSuccess: () => setMed({ drug_name: '', dose: '', frequency: '' }) })}><IconPlus size={14} aria-hidden /> {t('form.add')}</Button>
      </CardBody></Card>
      <Card><CardHeader title={t('form.history')} /><CardBody className="space-y-3">
        <ul className="space-y-1">{detail.medical_history.filter((h) => h.is_active).map((h) => row(h.id, h.title, () => archive.mutate(`history/${h.id}`)))}</ul>
        <Select value={hist.kind} onValueChange={(v) => setHist({ ...hist, kind: v })} options={(['cardiac', 'chronic', 'surgical', 'family', 'habit', 'other'] as const).map((k) => ({ value: k, label: t(`form.kind.${k}`) }))} />
        <Input aria-label={t('form.title')} placeholder={t('form.title')} value={hist.title} onChange={(e) => setHist({ ...hist, title: e.target.value })} />
        <Input aria-label="ICD-10" placeholder="ICD-10" value={hist.icd10_code} onChange={(e) => setHist({ ...hist, icd10_code: e.target.value })} />
        <Button size="sm" disabled={!hist.title.trim()} loading={add.isPending} onClick={() => add.mutate({ path: 'history', body: { kind: hist.kind, title: hist.title.trim(), icd10_code: hist.icd10_code || null } }, { onSuccess: () => setHist({ kind: 'chronic', title: '', icd10_code: '' }) })}><IconPlus size={14} aria-hidden /> {t('form.add')}</Button>
      </CardBody></Card>
    </div>
  );
}

/** Create (/patients/new) and edit (/patients/$id/edit) in one component. */
export function PatientFormPage() {
  const { t } = useTranslation('patients');
  const { id } = useParams({ strict: false }) as { id?: string };
  const navigate = useNavigate();
  const qc = useQueryClient();
  const edit = !!id;
  const canWrite = usePermission('patient:write');
  const existing = usePatient(id ?? '');
  const doctors = useQuery({ queryKey: ['users', 'doctors'], queryFn: ({ signal }) => get<{ id: string; full_name: string }[]>('/users/doctors', undefined, signal), staleTime: 300_000 });
  const [dup, setDup] = useState<{ message: string } | null>(null);
  const [serverError, setServerError] = useState<unknown>(null);
  const pendingBody = useRef<PatientFormOutput | null>(null);

  const { register, control, handleSubmit, reset, setError, formState: { errors, isDirty, isSubmitting } } = useForm<PatientFormInput, unknown, PatientFormOutput>({
    resolver: zodResolver(edit ? patientSchema : createPatientSchema),
    defaultValues: !edit ? (loadDraft() ?? emptyPatient) : emptyPatient,
  });
  const al = useFieldArray({ control, name: 'allergies' });
  const md = useFieldArray({ control, name: 'medications' });
  const hs = useFieldArray({ control, name: 'history' });
  const values = useWatch({ control });
  const index = bmi(values.height_cm, values.weight_kg);

  useEffect(() => {
    const p = existing.data;
    if (edit && p) reset({ ...emptyPatient, last_name: p.last_name, first_name: p.first_name, middle_name: p.middle_name ?? '', birth_date: p.birth_date, gender: p.gender, blood_group: p.blood_group, phone: p.phone ?? '', address: p.address ?? '', national_id: '', height_cm: (p.height_cm ?? '') as number, weight_kg: (p.weight_kg ?? '') as number, emergency_contact_name: p.emergency_contact_name ?? '', emergency_contact_phone: p.emergency_contact_phone ?? '', primary_doctor_id: p.primary_doctor?.id ?? '', notes: p.notes ?? '', ai_consent: p.ai_consent });
  }, [edit, existing.data, reset]);

  // local draft (24 h) for the create form + unsaved-changes guard
  useEffect(() => {
    if (edit || !isDirty) return;
    const tm = setTimeout(() => safeStorage.set(DRAFT_KEY, JSON.stringify({ at: Date.now(), values: { ...values, national_id: '' } })), 800);
    return () => clearTimeout(tm);
  }, [values, isDirty, edit]);
  useEffect(() => {
    if (!isDirty) return;
    const on = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener('beforeunload', on);
    return () => window.removeEventListener('beforeunload', on);
  }, [isDirty]);

  const save = async (v: PatientFormOutput, force = false) => {
    setServerError(null);
    try {
      const body = toPatientBody(v);
      if (edit) {
        const { national_id, ai_consent, ...rest } = body;
        await api.patch(`/patients/${id}`, { ...rest, ...(national_id ? { national_id } : {}), ai_consent }, { headers: { 'If-Match': String(existing.data?.version ?? '') } });
        void qc.invalidateQueries({ queryKey: qk.patients.all });
        toast.success(t('form.saved'));
        void navigate({ to: '/patients/$id', params: { id: id! } } as never);
        return;
      }
      const res = await api.post<{ id: string }>(`/patients${force ? '?force=true' : ''}`, body);
      const pid = res.data.id;
      await Promise.all([
        ...v.allergies.map((a) => post(`/patients/${pid}/allergies`, { substance: a.substance, reaction: a.reaction || null, severity: a.severity })),
        ...v.medications.map((m) => post(`/patients/${pid}/medications`, { drug_name: m.drug_name, dose: m.dose || null, frequency: m.frequency || null })),
        ...v.history.map((h) => post(`/patients/${pid}/history`, { kind: h.kind, title: h.title, icd10_code: h.icd10_code || null })),
      ]);
      safeStorage.remove(DRAFT_KEY);
      void qc.invalidateQueries({ queryKey: qk.patients.all });
      toast.success(t('form.created'));
      void navigate({ to: '/patients/$id', params: { id: pid } } as never);
    } catch (e) {
      if (isApiError(e)) {
        if (e.code === 'POSSIBLE_DUPLICATE') { pendingBody.current = v; setDup({ message: e.message }); return; }
        const map = fieldErrorMap(e);
        for (const [k, msg] of Object.entries(map)) setError(k as keyof PatientFormInput, { message: msg });
        if (e.code === 'VERSION_CONFLICT') toast.error(t('form.conflict'));
        if (!Object.keys(map).length) setServerError(e);
      } else setServerError(e);
    }
  };

  if (!canWrite) return <ErrorState error={new Error(t('errors:forbidden'))} />;
  if (edit && existing.isLoading) return <SkeletonRows rows={8} />;
  if (edit && existing.isError) return <ErrorState error={existing.error} onRetry={() => void existing.refetch()} />;
  const e = errors as Record<string, { message?: string } | undefined>;

  return (
    <div className="max-w-4xl">
      <PageHeader title={edit ? t('form.edit_title') : t('new')} breadcrumbs={[{ label: t('title'), to: '/patients' }, { label: edit ? existing.data?.full_name ?? '' : t('new') }]}
        actions={<><Button variant="outline" asChild><Link to={edit ? '/patients/$id' : '/patients'} params={edit ? { id: id! } : undefined as never}>{t('common:actions.cancel')}</Link></Button><Button loading={isSubmitting} onClick={() => void handleSubmit((v) => save(v))()}>{t('common:actions.save')}</Button></>} />
      {serverError ? <Alert tone="danger" className="mb-4">{errorMessage(serverError, t as never)}</Alert> : null}
      <form onSubmit={(ev) => { ev.preventDefault(); void handleSubmit((v) => save(v))(); }} noValidate className="space-y-5">
        <Card><CardHeader title={t('form.personal')} /><CardBody className="grid gap-4 sm:grid-cols-3">
          <Field label={t('form.last_name')} required error={e.last_name?.message}><Input {...register('last_name')} autoComplete="off" /></Field>
          <Field label={t('form.first_name')} required error={e.first_name?.message}><Input {...register('first_name')} autoComplete="off" /></Field>
          <Field label={t('form.middle_name')} error={e.middle_name?.message}><Input {...register('middle_name')} autoComplete="off" /></Field>
          <Field label={t('form.birth_date')} required error={e.birth_date?.message}><Input type="date" max={new Date().toISOString().slice(0, 10)} {...register('birth_date')} /></Field>
          <Field label={t('filters.gender')} required><Controller control={control} name="gender" render={({ field }) => <Select value={field.value} onValueChange={field.onChange} options={[{ value: 'male', label: t('common:gender.male') }, { value: 'female', label: t('common:gender.female') }]} />} /></Field>
          <Field label={t('form.blood')}><Controller control={control} name="blood_group" render={({ field }) => <Select value={field.value} onValueChange={field.onChange} options={BLOOD.map((b) => ({ value: b, label: b === 'unknown' ? t('form.unknown') : b }))} />} /></Field>
          <Field label={t('form.national_id')} error={e.national_id?.message} hint={edit ? t('form.national_id_edit') : undefined}><Input {...register('national_id')} autoComplete="off" /></Field>
        </CardBody></Card>
        <Card><CardHeader title={t('form.contact')} /><CardBody className="grid gap-4 sm:grid-cols-2">
          <Field label={t('cols.phone')} error={e.phone?.message} hint="+998901234567"><Input inputMode="tel" {...register('phone')} /></Field>
          <Field label={t('form.address')} error={e.address?.message}><Input {...register('address')} /></Field>
          <Field label={t('form.emergency_name')}><Input {...register('emergency_contact_name')} /></Field>
          <Field label={t('form.emergency_phone')} error={e.emergency_contact_phone?.message}><Input inputMode="tel" {...register('emergency_contact_phone')} /></Field>
        </CardBody></Card>
        <Card><CardHeader title={t('form.anthropometry')} /><CardBody className="grid gap-4 sm:grid-cols-3">
          <Field label={`${t('form.height')} (cm)`} error={e.height_cm?.message}><Input type="number" step="any" inputMode="decimal" {...register('height_cm')} /></Field>
          <Field label={`${t('form.weight')} (kg)`} error={e.weight_kg?.message}><Input type="number" step="any" inputMode="decimal" {...register('weight_kg')} /></Field>
          <div><p className="mb-1.5 text-sm font-medium">BMI</p><p className="flex h-10 items-center gap-2 rounded-md bg-surface-2 px-3 font-mono-num" aria-live="polite">{index ?? '-'} {index && <span className="text-xs text-muted">{t(`form.bmi.${bmiBand(index)}`)}</span>}</p></div>
        </CardBody></Card>
        <Card><CardHeader title={t('form.doctor_notes')} /><CardBody className="grid gap-4 sm:grid-cols-2">
          <Field label={t('form.primary_doctor')}><Controller control={control} name="primary_doctor_id" render={({ field }) => <Select value={field.value || ALL} onValueChange={(v) => field.onChange(v === ALL ? '' : v)} options={[{ value: ALL, label: t('form.none') }, ...(doctors.data ?? []).map((d) => ({ value: d.id, label: d.full_name }))]} />} /></Field>
          <Field label={t('form.notes')} className="sm:col-span-2"><Textarea rows={3} {...register('notes')} /></Field>
        </CardBody></Card>

        {!edit && (
          <div className="grid gap-5 lg:grid-cols-3">
            <Card><CardHeader title={t('form.allergies')} /><CardBody className="space-y-3">
              {al.fields.map((f, i) => (<div key={f.id} className="space-y-1 rounded-md border border-border p-2"><Input aria-label={t('form.substance')} placeholder={t('form.substance')} {...register(`allergies.${i}.substance`)} /><Input aria-label={t('form.reaction')} placeholder={t('form.reaction')} {...register(`allergies.${i}.reaction`)} /><div className="flex justify-between"><Controller control={control} name={`allergies.${i}.severity`} render={({ field }) => <Select value={field.value} onValueChange={field.onChange} className="w-40" options={(['mild', 'moderate', 'severe', 'anaphylaxis'] as const).map((s) => ({ value: s, label: t(`form.severity.${s}`) }))} />} /><Button type="button" size="icon-sm" variant="ghost" aria-label={t('common:actions.delete')} onClick={() => al.remove(i)}><IconTrash size={14} aria-hidden /></Button></div></div>))}
              <Button type="button" size="sm" variant="outline" onClick={() => al.append({ substance: '', reaction: '', severity: 'moderate' })}><IconPlus size={14} aria-hidden /> {t('form.add')}</Button>
            </CardBody></Card>
            <Card><CardHeader title={t('form.medications')} /><CardBody className="space-y-3">
              {md.fields.map((f, i) => (<div key={f.id} className="space-y-1 rounded-md border border-border p-2"><Input aria-label={t('form.drug')} placeholder={t('form.drug')} {...register(`medications.${i}.drug_name`)} /><Input aria-label={t('form.dose')} placeholder={t('form.dose')} {...register(`medications.${i}.dose`)} /><div className="flex gap-2"><Input aria-label={t('form.frequency')} placeholder={t('form.frequency')} {...register(`medications.${i}.frequency`)} /><Button type="button" size="icon-sm" variant="ghost" aria-label={t('common:actions.delete')} onClick={() => md.remove(i)}><IconTrash size={14} aria-hidden /></Button></div></div>))}
              <Button type="button" size="sm" variant="outline" onClick={() => md.append({ drug_name: '', dose: '', frequency: '' })}><IconPlus size={14} aria-hidden /> {t('form.add')}</Button>
            </CardBody></Card>
            <Card><CardHeader title={t('form.history')} /><CardBody className="space-y-3">
              {hs.fields.map((f, i) => (<div key={f.id} className="space-y-1 rounded-md border border-border p-2"><Controller control={control} name={`history.${i}.kind`} render={({ field }) => <Select value={field.value} onValueChange={field.onChange} options={(['cardiac', 'chronic', 'surgical', 'family', 'habit', 'other'] as const).map((k) => ({ value: k, label: t(`form.kind.${k}`) }))} />} /><Input aria-label={t('form.title')} placeholder={t('form.title')} {...register(`history.${i}.title`)} /><div className="flex gap-2"><Input aria-label="ICD-10" placeholder="ICD-10" {...register(`history.${i}.icd10_code`)} /><Button type="button" size="icon-sm" variant="ghost" aria-label={t('common:actions.delete')} onClick={() => hs.remove(i)}><IconTrash size={14} aria-hidden /></Button></div></div>))}
              <Button type="button" size="sm" variant="outline" onClick={() => hs.append({ kind: 'chronic', title: '', icd10_code: '' })}><IconPlus size={14} aria-hidden /> {t('form.add')}</Button>
            </CardBody></Card>
          </div>
        )}
        {edit && existing.data && <SubRecordLists patientId={id!} detail={existing.data} />}

        <Card><CardBody>
          <Controller control={control} name="ai_consent" render={({ field }) => <CheckboxField label={t('form.consent')} checked={field.value} onCheckedChange={(c) => field.onChange(c === true)} />} />
          {e.ai_consent && <p role="alert" className="mt-1 text-xs font-medium text-danger-500">{e.ai_consent.message}</p>}
        </CardBody></Card>
      </form>

      <Dialog open={!!dup} onOpenChange={(o) => !o && setDup(null)} title={t('form.dup_title')} description={dup?.message}
        footer={<><Button variant="outline" onClick={() => setDup(null)}>{t('common:actions.cancel')}</Button><Button onClick={() => { const v = pendingBody.current; setDup(null); if (v) void save(v, true); }}>{t('form.dup_force')}</Button></>}>
        <p className="text-sm">{t('form.dup_body')}</p>
      </Dialog>
    </div>
  );
}
