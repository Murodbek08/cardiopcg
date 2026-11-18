import { forwardRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { IconEye, IconEyeOff, IconAlertTriangle } from '@tabler/icons-react';
import { Input, type InputProps } from './input';

export const PasswordInput = forwardRef<HTMLInputElement, InputProps & { capsWarning?: boolean }>(function PasswordInput(
  { capsWarning = false, onKeyUp, ...props },
  ref,
) {
  const { t } = useTranslation('auth');
  const [show, setShow] = useState(false);
  const [caps, setCaps] = useState(false);
  const handleKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (capsWarning) setCaps(e.getModifierState?.('CapsLock') ?? false);
    onKeyUp?.(e);
  };
  return (
    <div>
      <div className="relative">
        <Input ref={ref} type={show ? 'text' : 'password'} className="pr-11" onKeyUp={handleKey} {...props} />
        <button
          type="button"
          onClick={() => setShow((s) => !s)}
          className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
          aria-label={show ? t('login.hide_password') : t('login.show_password')}
          aria-pressed={show}
        >
          {show ? <IconEyeOff size={18} aria-hidden /> : <IconEye size={18} aria-hidden />}
        </button>
      </div>
      {caps && (
        <p className="mt-1 flex items-center gap-1 text-xs text-warning-500" role="status">
          <IconAlertTriangle size={14} aria-hidden /> {t('login.caps_lock')}
        </p>
      )}
    </div>
  );
});
