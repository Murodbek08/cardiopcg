import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { IconAlertTriangle, IconPlus, IconRefresh, IconShieldCheck } from '@tabler/icons-react';
import { Alert, Badge, Button, Card, CardBody, Dialog, Field, Input, StatusBadge, Textarea, AiDisclaimerBadge, errorMessage, toast, cn } from '@/shared';
import type { Prescription, PrescriptionItem } from '@/shared/api/types';
import { usePrescriptionActions } from '../api';
import { acceptRequirement, itemInteractionLevel } from '../logic';

type Warning = { items?: string[]; level?: string; note?: string };

function ItemCard({ item, canEdit, onAccept, onReject, onEdit }: { item: PrescriptionItem; canEdit: boolean; onAccept: () => void; onReject: () => void; onEdit: () => void }) {
  const { t } = useTranslation('exams');
  const req = acceptRequirement(item);
  const lvl = itemInteractionLevel(item);
  const warnings = (item.interaction_warnings ?? []) as Warning[];
  const decided = item.status === 'approved' || item.status === 'rejected';
  return (
    <Card className={cn(item.allergy_warning && 'border-danger-500/60', lvl === 'contraindicated' && 'border-danger-500/60')}>
      <CardBody className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="text-h3 font-semibold">{item.drug_name} {item.source === 'doctor' && <Badge tone="neutral" icon={false}>{t('drugs.manual')}</Badge>}</p>
            <p className="text-sm text-muted">{item.dose} &middot; {item.route} &middot; {item.frequency}{item.duration_days ? ` · ${item.duration_days} ${t('drugs.days')}` : ''}</p>
          </div>
          <span className="inline-flex items-center gap-2">
            <Badge tone={item.status === 'approved' ? 'success' : item.status === 'rejected' ? 'neutral' : 'warning'}>{t(`drugs.status.${item.status}`, { defaultValue: item.status })}</Badge>
            {item.source === 'ai' && <AiDisclaimerBadge compact />}
          </span>
        </div>
        {item.allergy_warning && <Alert tone="danger" title={t('drugs.allergy_title')}>{t('drugs.allergy_body')}</Alert>}
        {warnings.map((w, i) => (
          <Alert key={i} tone={w.level === 'contraindicated' ? 'danger' : w.level === 'major' ? 'warning' : 'info'} title={<span className="inline-flex items-center gap-2"><StatusBadge kind="interaction" value={w.level} /> {(w.items ?? []).join(' + ')}</span>}>{w.note}</Alert>
        ))}
        {item.safety_pending && <Alert tone="warning">{t('drugs.safety_pending')}</Alert>}
        {item.rationale && <p className="text-sm"><span className="font-medium">{t('drugs.rationale')}:</span> {item.rationale}</p>}
        {item.contraindications.length > 0 && <p className="text-sm"><span className="font-medium">{t('drugs.contra')}:</span> {item.contraindications.join(', ')}</p>}
        {item.side_effects.length > 0 && <p className="text-sm"><span className="font-medium">{t('drugs.side')}:</span> {item.side_effects.join(', ')}</p>}
        {item.override_reason && <p className="text-sm text-warning-500">{t('drugs.override_reason')}: {item.override_reason}</p>}
        {canEdit && !decided && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={onAccept} disabled={req === 'blocked'} title={req === 'blocked' ? t('drugs.safety_pending') : undefined}>
              <IconShieldCheck size={16} aria-hidden /> {req === 'reason' ? t('drugs.accept_anyway') : t('drugs.accept')}
            </Button>
            <Button size="sm" variant="outline" onClick={onEdit}>{t('common:actions.edit')}</Button>
            <Button size="sm" variant="outline" onClick={onReject}>{t('drugs.reject')}</Button>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function ReasonDialog({ open, title, body, onClose, onSubmit, busy }: { open: boolean; title: string; body: string; onClose: () => void; onSubmit: (reason: string) => void; busy: boolean }) {
  const { t } = useTranslation('exams');
  const [reason, setReason] = useState('');
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) { setReason(''); onClose(); } }} title={title} description={body} size="sm"
      footer={<><Button variant="outline" onClick={onClose}>{t('common:actions.cancel')}</Button><Button loading={busy} disabled={reason.trim().length < 3} onClick={() => onSubmit(reason.trim())}>{t('common:actions.confirm')}</Button></>}>
      <Field label={t('drugs.reason')} required><Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
    </Dialog>
  );
}

function ItemFormDialog({ open, onClose, initial, onSubmit, busy }: { open: boolean; onClose: () => void; initial?: PrescriptionItem; onSubmit: (v: Record<string, unknown>) => void; busy: boolean }) {
  const { t } = useTranslation('exams');
  const [v, setV] = useState({ drug_name: initial?.drug_name ?? '', dose: initial?.dose ?? '', frequency: initial?.frequency ?? '', route: initial?.route ?? 'oral', duration_days: initial?.duration_days?.toString() ?? '', instructions: initial?.instructions ?? '' });
  const ok = v.drug_name.trim() && v.dose.trim() && v.frequency.trim();
  const set = (k: keyof typeof v) => (e: { target: { value: string } }) => setV((x) => ({ ...x, [k]: e.target.value }));
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()} title={initial ? t('drugs.edit') : t('drugs.add')} size="md"
      footer={<><Button variant="outline" onClick={onClose}>{t('common:actions.cancel')}</Button><Button loading={busy} disabled={!ok} onClick={() => onSubmit({ drug_name: v.drug_name.trim(), dose: v.dose.trim(), frequency: v.frequency.trim(), route: v.route.trim() || 'oral', duration_days: v.duration_days ? Number(v.duration_days) : null, instructions: v.instructions || null })}>{t('common:actions.save')}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t('drugs.name')} required className="sm:col-span-2"><Input value={v.drug_name} onChange={set('drug_name')} disabled={!!initial} /></Field>
        <Field label={t('drugs.dose')} required><Input value={v.dose} onChange={set('dose')} placeholder="50 mg" /></Field>
        <Field label={t('drugs.frequency')} required><Input value={v.frequency} onChange={set('frequency')} /></Field>
        <Field label={t('drugs.route')}><Input value={v.route} onChange={set('route')} /></Field>
        <Field label={t('drugs.duration')}><Input type="number" min={1} value={v.duration_days} onChange={set('duration_days')} /></Field>
        <Field label={t('drugs.instructions')} className="sm:col-span-2"><Textarea rows={2} value={v.instructions} onChange={set('instructions')} /></Field>
      </div>
    </Dialog>
  );
}

/** Drug suggestions: nothing is final until the doctor accepts; unsafe items need a written reason (audited). */
export function DrugRecommendationPanel({ examId, prescription, canEdit, locked }: { examId: string; prescription: Prescription | null; canEdit: boolean; locked: boolean }) {
  const { t } = useTranslation('exams');
  const act = usePrescriptionActions(examId);
  const [accept, setAccept] = useState<PrescriptionItem | null>(null);
  const [reject, setReject] = useState<PrescriptionItem | null>(null);
  const [edit, setEdit] = useState<PrescriptionItem | 'new' | null>(null);
  const editable = canEdit && !locked;
  const fail = (e: unknown) => toast.error(errorMessage(e, t as never));
  const sc = (prescription?.safety_check ?? {}) as { allergy_conflicts?: { allergen?: string; severity?: string }[]; interactions?: unknown[] };

  if (!prescription) {
    return (
      <div className="space-y-3">
        <Alert tone="info">{canEdit ? t('drugs.none_doctor') : t('drugs.none_nurse')}</Alert>
        {editable && <div className="flex gap-2"><Button variant="outline" onClick={() => setEdit('new')}><IconPlus size={16} aria-hidden /> {t('drugs.add')}</Button><Button variant="outline" loading={act.regenerate.isPending} onClick={() => act.regenerate.mutate(undefined, { onError: fail })}><IconRefresh size={16} aria-hidden /> {t('drugs.regenerate')}</Button></div>}
        <ItemFormDialog open={edit === 'new'} onClose={() => setEdit(null)} busy={act.add.isPending} onSubmit={(v) => act.add.mutate(v, { onSuccess: () => setEdit(null), onError: fail })} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <AiDisclaimerBadge />
        <p className="text-xs text-muted">{prescription.disclaimer}</p>
      </div>
      {(sc.allergy_conflicts?.length ?? 0) > 0 && (
        <Alert tone="danger" title={t('drugs.allergy_excluded')}>
          <ul className="list-disc pl-5">{sc.allergy_conflicts!.map((a, i) => <li key={i}><IconAlertTriangle size={14} className="mr-1 inline" aria-hidden />{a.allergen} {a.severity ? `(${a.severity})` : ''}</li>)}</ul>
        </Alert>
      )}
      {prescription.items.length === 0 && <p className="text-sm text-muted">{t('drugs.empty')}</p>}
      {prescription.items.map((it) => (
        <ItemCard key={it.id} item={it} canEdit={editable} onAccept={() => (acceptRequirement(it) === 'reason' ? setAccept(it) : act.approve.mutate({ id: it.id }, { onError: fail }))} onReject={() => setReject(it)} onEdit={() => setEdit(it)} />
      ))}
      {editable && (
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setEdit('new')}><IconPlus size={16} aria-hidden /> {t('drugs.add')}</Button>
          <Button variant="outline" loading={act.safety.isPending} onClick={() => act.safety.mutate(undefined, { onSuccess: () => toast.success(t('drugs.safety_done')), onError: fail })}>{t('drugs.safety_check')}</Button>
          <Button variant="outline" loading={act.regenerate.isPending} onClick={() => act.regenerate.mutate(undefined, { onError: fail })}><IconRefresh size={16} aria-hidden /> {t('drugs.regenerate')}</Button>
        </div>
      )}
      <ReasonDialog open={!!accept} title={t('drugs.accept_anyway')} body={t('drugs.accept_reason_body')} busy={act.approve.isPending} onClose={() => setAccept(null)}
        onSubmit={(reason) => accept && act.approve.mutate({ id: accept.id, override_reason: reason }, { onSuccess: () => setAccept(null), onError: fail })} />
      <ReasonDialog open={!!reject} title={t('drugs.reject')} body={t('drugs.reject_body')} busy={act.reject.isPending} onClose={() => setReject(null)}
        onSubmit={(reason) => reject && act.reject.mutate({ id: reject.id, reason }, { onSuccess: () => setReject(null), onError: fail })} />
      {edit && (
        <ItemFormDialog key={edit === 'new' ? 'new' : edit.id} open onClose={() => setEdit(null)} initial={edit === 'new' ? undefined : edit} busy={act.add.isPending || act.edit.isPending}
          onSubmit={(v) => (edit === 'new' ? act.add.mutate(v, { onSuccess: () => setEdit(null), onError: fail }) : act.edit.mutate({ id: edit.id, body: v }, { onSuccess: () => setEdit(null), onError: fail }))} />
      )}
    </div>
  );
}
