import type { ReactNode } from 'react';
import {
  IconAlertOctagon,
  IconAlertTriangle,
  IconCircleCheck,
  IconInfoCircle,
  IconCircleDashed,
  type Icon,
} from '@tabler/icons-react';
import { cn } from '@/shared/lib/cn';

export type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'brand' | 'high';

const toneClass: Record<Tone, string> = {
  neutral: 'bg-surface-2 text-foreground',
  success: 'bg-success-50 text-success-500',
  warning: 'bg-warning-50 text-warning-500',
  danger: 'bg-danger-50 text-danger-500',
  info: 'bg-info-50 text-info-500',
  brand: 'bg-brand-50 text-brand-700 dark:bg-brand-900/40 dark:text-brand-200',
  high: 'bg-orange-100 text-risk-high dark:bg-orange-950/50',
};

export const toneIcon: Record<Tone, Icon> = {
  neutral: IconCircleDashed,
  success: IconCircleCheck,
  warning: IconAlertTriangle,
  danger: IconAlertOctagon,
  info: IconInfoCircle,
  brand: IconInfoCircle,
  high: IconAlertTriangle,
};

/**
 * Status is NEVER conveyed by colour alone: every badge carries an icon and a text label.
 */
export function Badge({ tone = 'neutral', icon = true, children, className }: { tone?: Tone; icon?: boolean | Icon; children: ReactNode; className?: string }) {
  const I = typeof icon === 'function' || typeof icon === 'object' ? (icon as Icon) : toneIcon[tone];
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', toneClass[tone], className)}>
      {icon !== false && <I size={13} aria-hidden />}
      {children}
    </span>
  );
}
