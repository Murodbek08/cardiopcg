import { useTranslation } from 'react-i18next';
import { IconAlertOctagon, IconAlertTriangle, IconCircleCheck, IconShieldHalf } from '@tabler/icons-react';
import { cn } from '@/shared/lib/cn';
import { Badge } from '@/shared/ui/badge';

export type RiskZone = 'low' | 'moderate' | 'high' | 'critical';

export interface RiskThresholds {
  moderate: number; // low < moderate
  high: number;
  critical: number;
}
export const DEFAULT_THRESHOLDS: RiskThresholds = { moderate: 30, high: 60, critical: 85 };

export function riskZone(score: number, th: RiskThresholds = DEFAULT_THRESHOLDS): RiskZone {
  if (score >= th.critical) return 'critical';
  if (score >= th.high) return 'high';
  if (score >= th.moderate) return 'moderate';
  return 'low';
}

const zoneColor: Record<RiskZone, string> = {
  low: 'var(--color-risk-low)',
  moderate: 'var(--color-risk-moderate)',
  high: 'var(--color-risk-high)',
  critical: 'var(--color-risk-critical)',
};
const zoneTone = { low: 'success', moderate: 'warning', high: 'high', critical: 'danger' } as const;
const zoneIcon = { low: IconCircleCheck, moderate: IconAlertTriangle, high: IconAlertTriangle, critical: IconAlertOctagon } as const;

export function RiskBadge({ score, zone, thresholds }: { score?: number; zone?: RiskZone; thresholds?: RiskThresholds }) {
  const { t } = useTranslation('clinical');
  const z = zone ?? riskZone(score ?? 0, thresholds);
  return (
    <Badge tone={zoneTone[z]} icon={zoneIcon[z]}>
      {t(`risk.${z}`)}
      {score !== undefined && <span className="font-mono-num"> {Math.round(score)}</span>}
    </Badge>
  );
}

/**
 * Half-circle gauge 0-100 with four labelled zones. Zone name is always printed as text (not colour-only).
 * Pure SVG (no chart lib) so it stays light and prints well.
 */
export function RiskGauge({ value, thresholds = DEFAULT_THRESHOLDS, size = 220, caption, className }: { value: number | null | undefined; thresholds?: RiskThresholds; size?: number; caption?: string; className?: string }) {
  const { t } = useTranslation('clinical');
  const v = value === null || value === undefined ? null : Math.max(0, Math.min(100, value));
  const cx = 100;
  const cy = 100;
  const r = 80;
  const pt = (pct: number, rad = r) => {
    const a = Math.PI * (1 - pct / 100);
    return [cx + rad * Math.cos(a), cy - rad * Math.sin(a)] as const;
  };
  const arc = (from: number, to: number) => {
    const [x1, y1] = pt(from);
    const [x2, y2] = pt(to);
    return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 0 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
  };
  const zones: [RiskZone, number, number][] = [
    ['low', 0, thresholds.moderate],
    ['moderate', thresholds.moderate, thresholds.high],
    ['high', thresholds.high, thresholds.critical],
    ['critical', thresholds.critical, 100],
  ];
  const zone = v === null ? null : riskZone(v, thresholds);
  const [nx, ny] = pt(v ?? 0, r - 14);
  return (
    <div className={cn('flex flex-col items-center', className)} style={{ width: size }}>
      <svg viewBox="0 0 200 118" width={size} role="img" aria-label={v === null ? t('risk.unknown') : `${t('risk.label')}: ${Math.round(v)} (${t(`risk.${zone}`)})`}>
        {zones.map(([z, a, b]) => (
          <path key={z} d={arc(a, b)} fill="none" stroke={zoneColor[z]} strokeWidth={16} opacity={zone === z ? 1 : 0.35} strokeLinecap="butt" />
        ))}
        {v !== null && (
          <>
            <line x1={cx} y1={cy} x2={nx} y2={ny} stroke="var(--text)" strokeWidth={3} strokeLinecap="round" style={{ transition: 'all .4s ease' }} />
            <circle cx={cx} cy={cy} r={6} fill="var(--text)" />
          </>
        )}
      </svg>
      <div className="-mt-1 text-center">
        <p className="text-display font-bold leading-none tabular-nums">{v === null ? '-' : Math.round(v)}</p>
        <p className="mt-1 flex items-center justify-center gap-1 text-sm font-medium" style={{ color: zone ? zoneColor[zone] : undefined }}>
          <IconShieldHalf size={16} aria-hidden />
          {zone ? t(`risk.${zone}`) : t('risk.unknown')}
        </p>
        {caption && <p className="mt-0.5 text-xs text-muted">{caption}</p>}
      </div>
    </div>
  );
}
