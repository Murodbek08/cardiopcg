import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { IconCheck, IconCopy } from '@tabler/icons-react';
import { Button } from './button';

/** Read-only value with a copy button (one-time temporary passwords, request ids). */
export function CopyField({ value, label }: { value: string; label?: string }) {
  const { t } = useTranslation();
  const [done, setDone] = useState(false);
  return (
    <div>
      {label && <p className="mb-1 text-sm font-medium">{label}</p>}
      <div className="flex items-center gap-2 rounded-md border border-border bg-surface-2 px-3 py-2">
        <code className="min-w-0 flex-1 select-all break-all font-mono text-sm">{value}</code>
        <Button
          size="sm"
          variant="outline"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(value);
              setDone(true);
              setTimeout(() => setDone(false), 2000);
            } catch {
              /* clipboard blocked */
            }
          }}
        >
          {done ? <IconCheck size={16} aria-hidden /> : <IconCopy size={16} aria-hidden />}
          {done ? t('actions.copied') : t('actions.copy')}
        </Button>
      </div>
    </div>
  );
}
