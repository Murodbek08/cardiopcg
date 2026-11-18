import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Select } from './select';
import { Input } from './input';
import { Field } from './field';
import { daysAgo, today } from '@/shared/lib/format';

export type PeriodKey = 'today' | '7d' | '30d' | '90d' | 'custom';

export interface Period {
  key: PeriodKey;
  from: string; // YYYY-MM-DD
  to: string;
}

export const PERIOD_KEYS: PeriodKey[] = ['today', '7d', '30d', '90d', 'custom'];

export function resolvePeriod(key: PeriodKey, custom?: { from?: string; to?: string }): Period {
  const to = today();
  switch (key) {
    case 'today':
      return { key, from: to, to };
    case '7d':
      return { key, from: daysAgo(6), to };
    case '90d':
      return { key, from: daysAgo(89), to };
    case 'custom':
      return { key, from: custom?.from ?? daysAgo(29), to: custom?.to ?? to };
    default:
      return { key: '30d', from: daysAgo(29), to };
  }
}

/** Custom range must be 1-365 days and from <= to. */
export function validateRange(from: string, to: string): boolean {
  if (!from || !to || from > to) return false;
  const days = (new Date(to).getTime() - new Date(from).getTime()) / 86_400_000 + 1;
  return days >= 1 && days <= 365;
}

export function PeriodPicker({ value, onChange }: { value: Period; onChange: (p: Period) => void }) {
  const { t } = useTranslation();
  const [custom, setCustom] = useState({ from: value.from, to: value.to });
  const valid = useMemo(() => validateRange(custom.from, custom.to), [custom]);
  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="w-36">
        <Select
          aria-label={t('period.label')}
          value={value.key}
          onValueChange={(k) => onChange(resolvePeriod(k as PeriodKey, custom))}
          options={PERIOD_KEYS.map((k) => ({ value: k, label: t(`period.${k}`) }))}
        />
      </div>
      {value.key === 'custom' && (
        <>
          <Field label={t('period.from')} error={!valid ? t('period.invalid_range') : undefined}>
            <Input type="date" value={custom.from} max={custom.to} onChange={(e) => { const c = { ...custom, from: e.target.value }; setCustom(c); if (validateRange(c.from, c.to)) onChange(resolvePeriod('custom', c)); }} />
          </Field>
          <Field label={t('period.to')}>
            <Input type="date" value={custom.to} min={custom.from} max={today()} onChange={(e) => { const c = { ...custom, to: e.target.value }; setCustom(c); if (validateRange(c.from, c.to)) onChange(resolvePeriod('custom', c)); }} />
          </Field>
        </>
      )}
    </div>
  );
}
