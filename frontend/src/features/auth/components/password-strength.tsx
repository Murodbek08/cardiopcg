import { useTranslation } from 'react-i18next';
import { IconCheck, IconCircle } from '@tabler/icons-react';
import { cn } from '@/shared/lib/cn';
import { checkPassword, passwordScore, PASSWORD_MIN_LENGTH } from '@/shared/lib/password';

const barColor = ['bg-danger-500', 'bg-danger-500', 'bg-warning-500', 'bg-success-500', 'bg-success-500'];

/** Strength meter + live requirement checklist (icon + text, not colour-only). */
export function PasswordStrength({ value }: { value: string }) {
  const { t } = useTranslation('validation');
  const score = passwordScore(value);
  const c = checkPassword(value);
  const rules: [boolean, string][] = [
    [c.length, t('password_rules.length', { count: PASSWORD_MIN_LENGTH })],
    [c.case, t('password_rules.case')],
    [c.digit, t('password_rules.digit')],
    [c.special, t('password_rules.special')],
  ];
  return (
    <div className="space-y-2" aria-live="polite">
      <div className="flex items-center gap-2">
        <div className="flex flex-1 gap-1" aria-hidden>
          {[1, 2, 3, 4].map((i) => (
            <span key={i} className={cn('h-1.5 flex-1 rounded-full bg-border', value && score >= i && barColor[score])} />
          ))}
        </div>
        <span className="w-20 text-right text-xs text-muted">{value ? t(`password_strength.${score}`) : ''}</span>
      </div>
      <ul className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        {rules.map(([ok, label]) => (
          <li key={label} className={cn('flex items-center gap-1', ok ? 'text-success-500' : 'text-muted')}>
            {ok ? <IconCheck size={14} aria-hidden /> : <IconCircle size={14} aria-hidden />}
            <span>{label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
