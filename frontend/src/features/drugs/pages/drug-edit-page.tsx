import { useEffect, useState } from 'react';
import { useNavigate, useParams } from '@tanstack/react-router';
import { Controller, useFieldArray, useForm, useWatch, type Control, type FieldErrors, type UseFormRegister } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslation } from 'react-i18next';
import { IconPlus, IconTrash } from '@tabler/icons-react';
import {
  Alert, Button, Card, CardBody, CheckboxField, ConfirmDialog, ErrorState, Field, Input, PageHeader, Select, SkeletonRows, StatusBadge, Tabs, TabsContent, TabsList, TabsTrigger, Textarea,
  errorMessage, toast, useDebounce,
} from '@/shared';
import type { InteractionLevel } from '@/shared/api/types';
import { publishBlockers, useDrug, useDrugLifecycle, useDrugs, useDrugVersions, useSaveDrug } from '../api';
import { drugSchema, toFormValues, toPayload, type DrugFormOutput, type DrugFormValues } from '../schemas';

type F = { register: UseFormRegister<DrugFormValues>; control: Control<DrugFormValues, unknown, DrugFormOutput>; errors: FieldErrors<DrugFormValues> };

function RowShell({ children, onRemove, label }: { children: React.ReactNode; onRemove: () => void; label: string }) {
  return (
    <div className="grid items-start gap-3 rounded-md border border-border p-3 sm:grid-cols-[1fr_auto]">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{children}</div>
      <Button type="button" variant="ghost" size="icon" aria-label={label} onClick={onRemove}><IconTrash size={18} aria-hidden /></Button>
    </div>
  );
}

function DoseTab({ register, control, errors }: F) {
  const { t } = useTranslation('drugs');
  const { fields, append, remove } = useFieldArray({ control, name: 'dose_rules' });
  const er = errors.dose_rules as Record<number, Record<string, { message?: string }>> | undefined;
  return (
    <div className="space-y-3">
      {fields.map((f, i) => (
        <RowShell key={f.id} onRemove={() => remove(i)} label={t('common:actions.delete')}>
          <Field label={t('dose.population')} error={er?.[i]?.population?.message}><Input {...register(`dose_rules.${i}.population`)} placeholder="Kattalar" /></Field>
          <Field label={t('dose.min')} error={er?.[i]?.min_dose?.message}><Input type="number" step="any" inputMode="decimal" {...register(`dose_rules.${i}.min_dose`)} /></Field>
          <Field label={t('dose.max')} error={er?.[i]?.max_dose?.message}><Input type="number" step="any" inputMode="decimal" {...register(`dose_rules.${i}.max_dose`)} /></Field>
          <Field label={t('dose.unit')} error={er?.[i]?.unit?.message}><Input {...register(`dose_rules.${i}.unit`)} placeholder="mg" /></Field>
          <Field label={t('dose.max_daily')} error={er?.[i]?.max_daily?.message}><Input type="number" step="any" {...register(`dose_rules.${i}.max_daily`)} /></Field>
          <Field label={t('dose.note')}><Input {...register(`dose_rules.${i}.note`)} /></Field>
        </RowShell>
      ))}
      <Button type="button" variant="outline" onClick={() => append({ population: '', min_dose: '' as unknown as number, max_dose: '' as unknown as number, unit: 'mg', max_daily: '', note: '' })}><IconPlus size={16} aria-hidden /> {t('dose.add')}</Button>
    </div>
  );
}

function ListTab({ register, control, errors, name, withFlag }: F & { name: 'contraindications' | 'side_effects'; withFlag?: boolean }) {
  const { t } = useTranslation('drugs');
  const { fields, append, remove } = useFieldArray({ control, name });
  const er = errors[name] as Record<number, Record<string, { message?: string }>> | undefined;
  return (
    <div className="space-y-3">
      {fields.map((f, i) => (
        <RowShell key={f.id} onRemove={() => remove(i)} label={t('common:actions.delete')}>
          <Field label={t('text')} error={er?.[i]?.text?.message} className="sm:col-span-2"><Input {...register(`${name}.${i}.text` as const)} /></Field>
          {withFlag ? (
            <Controller control={control} name={`contraindications.${i}.absolute`} render={({ field }) => <CheckboxField className="mt-7" label={t('absolute')} checked={!!field.value} onCheckedChange={(c) => field.onChange(c === true)} />} />
          ) : (
            <Field label={t('frequency.label')}>
              <Controller control={control} name={`side_effects.${i}.frequency`} render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange} options={(['common', 'uncommon', 'rare'] as const).map((x) => ({ value: x, label: t(`frequency.${x}`) }))} />
              )} />
            </Field>
          )}
        </RowShell>
      ))}
      <Button type="button" variant="outline" onClick={() => (name === 'contraindications' ? append({ text: '', absolute: true } as never) : append({ text: '', frequency: 'common' } as never))}><IconPlus size={16} aria-hidden /> {t('add')}</Button>
    </div>
  );
}

function DrugPicker({ excludeId, onPick }: { excludeId?: string; onPick: (d: { id: string; inn: string }) => void }) {
  const { t } = useTranslation('drugs');
  const [q, setQ] = useState('');
  const dq = useDebounce(q, 300);
  const res = useDrugs({ q: dq, page: 1, page_size: 8 }, dq.length >= 2);
  const items = (res.data?.items ?? []).filter((d) => d.id !== excludeId);
  return (
    <div>
      <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('interactions.search')} aria-label={t('interactions.search')} />
      {dq.length >= 2 && (
        <ul className="mt-1 max-h-40 overflow-auto rounded-md border border-border bg-surface">
          {items.length === 0 && <li className="px-3 py-2 text-sm text-muted">{t('common:state.no_results')}</li>}
          {items.map((d) => (
            <li key={d.id}><button type="button" className="w-full px-3 py-2 text-left text-sm hover:bg-surface-2" onClick={() => { onPick({ id: d.id, inn: d.inn }); setQ(''); }}>{d.inn} <span className="text-xs text-muted">{d.group}</span></button></li>
          ))}
        </ul>
      )}
    </div>
  );
}

function InteractionsTab({ register, control, errors, selfId }: F & { selfId?: string }) {
  const { t } = useTranslation('drugs');
  const { fields, append, remove } = useFieldArray({ control, name: 'interactions' });
  const er = errors.interactions as Record<number, Record<string, { message?: string }>> | undefined;
  const current = useWatch({ control, name: 'interactions' }) ?? [];
  return (
    <div className="space-y-3">
      <Alert tone="info">{t('interactions.symmetric')}</Alert>
      {fields.map((f, i) => (
        <RowShell key={f.id} onRemove={() => remove(i)} label={t('common:actions.delete')}>
          <div className="sm:col-span-1"><p className="mb-1.5 text-sm font-medium">{t('interactions.drug')}</p><p className="rounded-md bg-surface-2 px-3 py-2 text-sm">{current[i]?.drug_name ?? current[i]?.drug_id}</p></div>
          <Field label={t('interactions.level')}>
            <Controller control={control} name={`interactions.${i}.level`} render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange} options={(['minor', 'moderate', 'major', 'contraindicated'] as InteractionLevel[]).map((x) => ({ value: x, label: t(`clinical:interaction.${x}`) }))} />
            )} />
          </Field>
          <Field label={t('interactions.mechanism')} error={er?.[i]?.mechanism?.message}><Input {...register(`interactions.${i}.mechanism`)} /></Field>
          <Field label={t('interactions.recommendation')} error={er?.[i]?.recommendation?.message} className="sm:col-span-2 lg:col-span-3"><Input {...register(`interactions.${i}.recommendation`)} /></Field>
        </RowShell>
      ))}
      <DrugPicker
        excludeId={selfId}
        onPick={(d) => {
          if (current.some((x) => x.drug_id === d.id)) return toast.info(t('interactions.duplicate'));
          append({ drug_id: d.id, drug_name: d.inn, level: 'moderate', mechanism: '', recommendation: '' });
        }}
      />
    </div>
  );
}

function SourcesTab({ register, control, errors }: F) {
  const { t } = useTranslation('drugs');
  const { fields, append, remove } = useFieldArray({ control, name: 'sources' });
  const er = errors.sources as Record<number, Record<string, { message?: string }>> | undefined;
  return (
    <div className="space-y-3">
      {fields.map((f, i) => (
        <RowShell key={f.id} onRemove={() => remove(i)} label={t('common:actions.delete')}>
          <Field label={t('sources.title')} error={er?.[i]?.title?.message}><Input {...register(`sources.${i}.title`)} /></Field>
          <Field label="URL" error={er?.[i]?.url?.message} className="sm:col-span-2"><Input type="url" {...register(`sources.${i}.url`)} placeholder="https://" /></Field>
        </RowShell>
      ))}
      <Button type="button" variant="outline" onClick={() => append({ title: '', url: '' })}><IconPlus size={16} aria-hidden /> {t('sources.add')}</Button>
    </div>
  );
}

function HistoryTab({ id }: { id?: string }) {
  const { t } = useTranslation('drugs');
  const q = useDrugVersions(id);
  if (!id) return <p className="text-sm text-muted">{t('versions.none')}</p>;
  if (q.isLoading) return <SkeletonRows rows={3} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  return (
    <ul className="space-y-2 text-sm">
      {(q.data?.items ?? []).map((v) => (
        <li key={`${v.version}-${v.created_at}`} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border px-3 py-2">
          <span><span className="font-medium">v{v.version}</span> {v.change ?? ''}</span>
          <span className="text-xs text-muted">{v.status} &middot; {new Date(v.created_at).toLocaleString('uz-UZ', { timeZone: 'Asia/Tashkent' })}</span>
        </li>
      ))}
    </ul>
  );
}

export function DrugEditPage() {
  const { t } = useTranslation('drugs');
  const params = useParams({ strict: false }) as { id?: string };
  const id = params.id && params.id !== 'new' ? params.id : undefined;
  const navigate = useNavigate();
  const q = useDrug(id);
  const save = useSaveDrug(id);
  const lifecycle = useDrugLifecycle(id ?? '');
  const [confirm, setConfirm] = useState<'publish' | 'archive' | null>(null);
  const [tab, setTab] = useState('main');

  const { register, control, handleSubmit, reset, formState: { errors, isDirty } } = useForm<DrugFormValues, unknown, DrugFormOutput>({
    resolver: zodResolver(drugSchema),
    defaultValues: toFormValues(),
  });
  useEffect(() => { if (q.data) reset(toFormValues(q.data)); }, [q.data, reset]);
  const inn = useWatch({ control, name: 'inn' });

  if (id && q.isLoading) return <SkeletonRows rows={8} />;
  if (id && q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;

  const drug = q.data;
  const blockers = drug ? publishBlockers(drug) : [];
  const readOnly = drug?.status === 'archived';

  const onSave = handleSubmit(
    async (v) => {
      try {
        const res = await save.mutateAsync(toPayload(v) as never);
        toast.success(t('saved'));
        if (!id) void navigate({ to: '/admin/drugs/$id', params: { id: res.id } } as never);
      } catch (e) {
        toast.error(errorMessage(e, t as never));
      }
    },
    () => toast.error(t('fix_errors')),
  );
  const run = async (a: 'publish' | 'archive') => {
    try {
      await lifecycle.mutateAsync(a);
      toast.success(t(`${a}_done`));
    } catch (e) {
      toast.error(errorMessage(e, t as never));
    }
    setConfirm(null);
  };
  const f: F = { register, control, errors };
  const tabErr = (keys: string[]) => keys.some((k) => (errors as Record<string, unknown>)[k]);

  return (
    <div className="max-w-5xl">
      <PageHeader
        title={id ? (inn || drug?.inn || '') : t('new')}
        description={drug ? <span className="inline-flex items-center gap-2"><StatusBadge kind="drug" value={drug.status} /> v{drug.version}</span> : t('new_hint')}
        breadcrumbs={[{ label: t('title'), to: '/admin/drugs' }, { label: id ? (drug?.inn ?? '') : t('new') }]}
        actions={
          <>
            {drug && drug.status !== 'published' && drug.status !== 'archived' && <Button variant="outline" disabled={blockers.length > 0 || isDirty} onClick={() => setConfirm('publish')} title={blockers.length ? t('publish_blocked', { items: blockers.map((b) => t(`blockers.${b}`)).join(', ') }) : undefined}>{t('common:actions.publish')}</Button>}
            {drug && drug.status !== 'archived' && <Button variant="outline" onClick={() => setConfirm('archive')}>{t('common:actions.archive')}</Button>}
            <Button onClick={() => void onSave()} loading={save.isPending} disabled={readOnly}>{t('common:actions.save')}</Button>
          </>
        }
      />
      {drug?.status === 'published' && <Alert tone="info" className="mb-4">{t('published_note')}</Alert>}
      {readOnly && <Alert tone="warning" className="mb-4">{t('archived_note')}</Alert>}
      {drug && drug.status === 'draft' && blockers.length > 0 && <Alert tone="warning" className="mb-4" title={t('publish_blocked_title')}>{blockers.map((b) => t(`blockers.${b}`)).join(', ')}</Alert>}
      <form onSubmit={(e) => { e.preventDefault(); void onSave(); }} noValidate>
        <fieldset disabled={readOnly} className="contents">
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList>
              <TabsTrigger value="main">{t('tabs.main')}{tabErr(['inn', 'group', 'atc_code']) && <span className="ml-1 text-danger-500" aria-label="error">!</span>}</TabsTrigger>
              <TabsTrigger value="dose">{t('tabs.dose')}{tabErr(['dose_rules']) && <span className="ml-1 text-danger-500" aria-label="error">!</span>}</TabsTrigger>
              <TabsTrigger value="contra">{t('tabs.contra')}</TabsTrigger>
              <TabsTrigger value="side">{t('tabs.side')}</TabsTrigger>
              <TabsTrigger value="inter">{t('tabs.interactions')}</TabsTrigger>
              <TabsTrigger value="sources">{t('tabs.sources')}{tabErr(['sources']) && <span className="ml-1 text-danger-500" aria-label="error">!</span>}</TabsTrigger>
              <TabsTrigger value="history">{t('tabs.history')}</TabsTrigger>
            </TabsList>
            <Card className="mt-4">
              <CardBody>
                <TabsContent value="main" className="grid gap-4 pt-0 sm:grid-cols-2">
                  <Field label={t('cols.inn')} error={errors.inn?.message} required><Input {...register('inn')} /></Field>
                  <Field label={t('cols.group')} error={errors.group?.message} required><Input {...register('group')} /></Field>
                  <Field label={t('cols.trade')} hint={t('comma_hint')}><Input {...register('trade_names')} /></Field>
                  <Field label="ATC" error={errors.atc_code?.message} hint="C07AB02"><Input {...register('atc_code')} /></Field>
                  <Field label={t('forms')} hint={t('comma_hint')}><Input {...register('forms')} /></Field>
                  <Field label={t('indications')} hint="I10, I50"><Textarea rows={2} {...register('indications_icd10')} /></Field>
                </TabsContent>
                <TabsContent value="dose" className="pt-0"><DoseTab {...f} /></TabsContent>
                <TabsContent value="contra" className="pt-0"><ListTab {...f} name="contraindications" withFlag /></TabsContent>
                <TabsContent value="side" className="pt-0"><ListTab {...f} name="side_effects" /></TabsContent>
                <TabsContent value="inter" className="pt-0"><InteractionsTab {...f} selfId={id} /></TabsContent>
                <TabsContent value="sources" className="pt-0"><SourcesTab {...f} /></TabsContent>
                <TabsContent value="history" className="pt-0"><HistoryTab id={id} /></TabsContent>
              </CardBody>
            </Card>
          </Tabs>
        </fieldset>
      </form>
      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(o) => !o && setConfirm(null)}
        title={confirm ? t(`confirm.${confirm}.title`) : ''}
        description={confirm ? t(`confirm.${confirm}.body`) : undefined}
        danger={confirm === 'archive'}
        loading={lifecycle.isPending}
        onConfirm={() => (confirm ? run(confirm) : undefined)}
      />
    </div>
  );
}
