import { useTranslation } from 'react-i18next';
import { IconRobot } from '@tabler/icons-react';
import { cn } from '@/shared/lib/cn';

/** Must sit next to every AI result and drug suggestion (project medical-safety rule). */
export function AiDisclaimerBadge({ className, compact }: { className?: string; compact?: boolean }) {
  const { t } = useTranslation('clinical');
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border border-info-500/40 bg-info-50 px-2.5 py-0.5 text-xs font-medium text-info-500',
        className,
      )}
    >
      <IconRobot size={14} aria-hidden />
      {compact ? t('ai.badge_short') : t('ai.disclaimer')}
    </span>
  );
}
