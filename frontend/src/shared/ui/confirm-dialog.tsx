import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog } from './dialog';
import { Button } from './button';
import { Textarea } from './input';
import { Field } from './field';

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  loading?: boolean;
  /** When set, the user must type a reason (audit trail). Passed to onConfirm. */
  requireReason?: { label: string; minLength?: number };
  onConfirm: (reason?: string) => void | Promise<void>;
}

export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel, danger, loading, requireReason, onConfirm }: ConfirmDialogProps) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const min = requireReason?.minLength ?? 3;
  const reasonOk = !requireReason || reason.trim().length >= min;
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) setReason('');
        onOpenChange(o);
      }}
      title={title}
      description={description}
      size="sm"
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
            {t('actions.cancel')}
          </Button>
          <Button
            variant={danger ? 'danger' : 'primary'}
            loading={loading}
            disabled={!reasonOk}
            onClick={async () => {
              await onConfirm(requireReason ? reason.trim() : undefined);
              setReason('');
            }}
          >
            {confirmLabel ?? t('actions.confirm')}
          </Button>
        </>
      }
    >
      {requireReason && (
        <Field label={requireReason.label} required>
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} />
        </Field>
      )}
    </Dialog>
  );
}
