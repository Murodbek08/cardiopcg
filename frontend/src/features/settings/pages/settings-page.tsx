import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { IconBrain, IconRefresh } from '@tabler/icons-react';
import {
  Alert, Badge, Button, Card, CardBody, CardHeader, ConfirmDialog, ErrorState, Field, Input, PageHeader, Select, SkeletonRows, Switch, Tabs, TabsContent, TabsList, TabsTrigger, Textarea,
  errorMessage, get, patch, qk, toast, cn,
} from '@/shared';
import type { HealthDeep, SettingItem } from '@/shared/api/types';
import { coerceForSave, metaFor, normalizeSettings, validateSetting, type Draft, type SettingGroup } from '../registry';

const GROUPS: SettingGroup[] = ['ai', 'limits', 'security', 'retention', 'clinic', 'other'];

function useSettings() {
  return useQuery({ queryKey: qk.settings, queryFn: async ({ signal }) => normalizeSettings(await get<unknown>('/settings', undefined, signal)) });
}

function AiStatus() {
  const { t } = useTranslation('admin');
  const q = useQuery({ queryKey: qk.health, queryFn: ({ signal }) => get<HealthDeep>('/system/health/deep', undefined, signal), retry: 0 });
  const key = q.data?.checks?.deepseek_key;
  const rest = Object.entries(q.data?.checks ?? {}).filter(([k]) => k !== 'deepseek_key');
  return (
    <Card>
      <CardHeader
        title={<span className="inline-flex items-center gap-2"><IconBrain size={20} aria-hidden /> {t('settings.ai_status')}</span>}
        actions={<Button size="sm" variant="outline" loading={q.isFetching} onClick={() => void q.refetch()}><IconRefresh size={16} aria-hidden /> {t('settings.recheck')}</Button>}
      />
      <CardBody className="space-y-3">
        {q.isLoading ? (
          <SkeletonRows rows={2} />
        ) : q.isError ? (
          <Alert tone="danger" title={t('settings.ai_down')}>{errorMessage(q.error, t as never)}</Alert>
        ) : (
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <Badge tone={key === 'configured' ? 'success' : key ? 'danger' : 'neutral'}>{key ? (key === 'configured' ? t('settings.ai_up') : t('settings.ai_down')) : t('settings.ai_unknown')}</Badge>
            {rest.map(([k, v]) => <span key={k} className="text-muted">{k}: {v}</span>)}
          </div>
        )}
        <p className="text-xs text-muted">{t('settings.key_note')}</p>
      </CardBody>
    </Card>
  );
}

function SettingField({ item, value, error, onChange }: { item: SettingItem; value: unknown; error?: string; onChange: (v: unknown) => void }) {
  const { t } = useTranslation('admin');
  const m = metaFor(item);
  const label = (
    <span>
      <span className="font-mono text-xs">{item.key}</span>
      {m.unit && <span className="ml-1 text-xs text-muted">({m.unit})</span>}
    </span>
  );
  const hint = t(`settings.desc.${item.key.replace(/\./g, '_')}`, { defaultValue: item.description ?? '' }) || undefined;
  if (m.type === 'bool') {
    return (
      <div className="flex items-center justify-between gap-4 rounded-md border border-border px-3 py-2.5">
        <div className="min-w-0">
          <p className="font-mono text-xs">{item.key}</p>
          {hint && <p className="text-xs text-muted">{hint}</p>}
        </div>
        <Switch checked={!!value} onCheckedChange={onChange} aria-label={item.key} />
      </div>
    );
  }
  return (
    <Field label={label} error={error} hint={hint}>
      {m.options ? (
        <Select value={String(value ?? '')} onValueChange={onChange} options={m.options.map((o) => ({ value: o, label: o }))} />
      ) : m.type === 'json' ? (
        <Textarea rows={4} className="font-mono text-xs" value={typeof value === 'string' ? value : JSON.stringify(value, null, 2)} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <Input
          type={m.type === 'int' || m.type === 'float' ? 'number' : 'text'}
          inputMode={m.type === 'float' ? 'decimal' : m.type === 'int' ? 'numeric' : undefined}
          step={m.type === 'float' ? '0.01' : undefined}
          min={m.min}
          max={m.max}
          value={(value as string | number | undefined) ?? ''}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </Field>
  );
}

export function SettingsPage() {
  const { t } = useTranslation('admin');
  const qc = useQueryClient();
  const q = useSettings();
  const [draft, setDraft] = useState<Draft>({});
  const [confirm, setConfirm] = useState(false);

  const items = useMemo(() => q.data ?? [], [q.data]);
  const byGroup = useMemo(() => {
    const g: Record<SettingGroup, SettingItem[]> = { ai: [], limits: [], security: [], retention: [], clinic: [], other: [] };
    for (const it of items) g[metaFor(it).group].push(it);
    for (const k of GROUPS) g[k].sort((a, b) => a.key.localeCompare(b.key));
    return g;
  }, [items]);

  const current = (it: SettingItem) => (it.key in draft ? draft[it.key] : it.value);
  const allValues = useMemo(() => Object.fromEntries(items.map((i) => [i.key, i.key in draft ? draft[i.key] : i.value])), [items, draft]);
  const errors = useMemo(() => {
    const out: Record<string, string> = {};
    for (const it of items) {
      if (!(it.key in draft)) continue;
      const e = validateSetting(it, draft[it.key], allValues);
      if (e) out[it.key] = t(`settings.errors.${e.code}`, { min: e.min, max: e.max });
    }
    // cross-field error must also surface on the sibling field
    return out;
  }, [items, draft, allValues, t]);

  const dirtyKeys = Object.keys(draft).filter((k) => {
    const it = items.find((i) => i.key === k);
    return it && JSON.stringify(draft[k]) !== JSON.stringify(it.value) && String(draft[k]) !== String(it.value);
  });
  const hasRisky = dirtyKeys.some((k) => { const it = items.find((i) => i.key === k); return it && metaFor(it).risky; });
  const hasErrors = Object.keys(errors).length > 0;

  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {};
      for (const k of dirtyKeys) {
        const it = items.find((i) => i.key === k)!;
        body[k] = coerceForSave(it, draft[k]);
      }
      return patch('/settings', body);
    },
    onSuccess: () => {
      setDraft({});
      setConfirm(false);
      void qc.invalidateQueries({ queryKey: qk.settings });
      toast.success(t('settings.saved'));
    },
    onError: (e) => { setConfirm(false); toast.error(errorMessage(e, t as never)); },
  });

  return (
    <div>
      <PageHeader
        title={t('settings.title')}
        actions={
          <>
            {dirtyKeys.length > 0 && <Badge tone="warning">{t('settings.unsaved', { count: dirtyKeys.length })}</Badge>}
            <Button variant="outline" disabled={!dirtyKeys.length} onClick={() => setDraft({})}>{t('actions.reset')}</Button>
            <Button disabled={!dirtyKeys.length || hasErrors} loading={save.isPending} onClick={() => (hasRisky ? setConfirm(true) : save.mutate())}>{t('actions.save')}</Button>
          </>
        }
      />
      {q.isLoading ? (
        <SkeletonRows rows={8} />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : (
        <Tabs defaultValue="ai">
          <TabsList>
            {GROUPS.filter((g) => byGroup[g].length || g === 'ai').map((g) => (
              <TabsTrigger key={g} value={g}>
                {t(`settings.groups.${g}`)}
                {byGroup[g].some((i) => dirtyKeys.includes(i.key)) && <span aria-label={t('settings.changed')} className="ml-1 inline-block h-2 w-2 rounded-full bg-warning-500" />}
              </TabsTrigger>
            ))}
          </TabsList>
          {GROUPS.filter((g) => byGroup[g].length || g === 'ai').map((g) => (
            <TabsContent key={g} value={g} className="space-y-4">
              {g === 'ai' && <AiStatus />}
              <Card>
                <CardBody className={cn('grid gap-4', g !== 'clinic' && 'md:grid-cols-2')}>
                  {byGroup[g].length === 0 && <p className="text-sm text-muted">{t('common:state.empty')}</p>}
                  {byGroup[g].map((it) => (
                    <SettingField key={it.key} item={it} value={current(it)} error={errors[it.key]} onChange={(v) => setDraft((d) => ({ ...d, [it.key]: v }))} />
                  ))}
                </CardBody>
              </Card>
            </TabsContent>
          ))}
        </Tabs>
      )}
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={t('settings.confirm_title')}
        description={t('settings.confirm_body', { keys: dirtyKeys.join(', ') })}
        danger
        loading={save.isPending}
        onConfirm={() => save.mutateAsync()}
      />
    </div>
  );
}
