import { useTranslation } from 'react-i18next';
import { MIN_SAMPLE } from '@/shared/lib/constants';
import { formatNumber } from '@/shared/lib/format';

/**
 * Percentage gauge (0-100), single sequential hue, with a text value (not colour-only).
 * Shows "not enough data" when n < MIN_SAMPLE (doc 03, section 4).
 */
export function PercentGauge({ value, n, label }: { value: number | null | undefined; n?: number; label: string }) {
  const { t } = useTranslation();
  if (value === null || value === undefined || (n !== undefined && n < MIN_SAMPLE)) {
    return (
      <div className="flex h-full items-center justify-center text-center text-sm text-muted">
        {n !== undefined ? t('state.not_enough_data', { n }) : t('state.empty_period')}
      </div>
    );
  }
  const v = Math.max(0, Math.min(100, value));
  const r = 80;
  const a = Math.PI * (1 - v / 100);
  const ex = 100 + r * Math.cos(a);
  const ey = 100 - r * Math.sin(a);
  return (
    <div className="flex h-full flex-col items-center justify-center">
      <svg viewBox="0 0 200 112" className="w-full max-w-64" role="img" aria-label={`${label}: ${formatNumber(v, 1)}%`}>
        <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="var(--border)" strokeWidth={16} strokeLinecap="round" />
        {v > 0 && <path d={`M 20 100 A 80 80 0 0 1 ${ex.toFixed(2)} ${ey.toFixed(2)}`} fill="none" stroke="var(--color-brand-600)" strokeWidth={16} strokeLinecap="round" />}
      </svg>
      <p className="-mt-8 text-display font-bold tabular-nums">{formatNumber(v, 1)}%</p>
      <p className="mt-1 text-xs text-muted">{label}{n !== undefined ? ` (n=${n})` : ''}</p>
    </div>
  );
}
