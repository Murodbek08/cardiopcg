import { Toaster as Sonner, toast } from 'sonner';
import { useThemeStore, resolveDark } from '@/shared/store/theme';

export function Toaster() {
  const mode = useThemeStore((s) => s.mode);
  return (
    <Sonner
      position="top-right"
      theme={resolveDark(mode) ? 'dark' : 'light'}
      richColors
      closeButton
      toastOptions={{ classNames: { toast: 'font-sans' } }}
    />
  );
}

/** Critical notifications stay on screen until dismissed and are announced assertively. */
export function toastCritical(title: string, description?: string): void {
  toast.error(title, { description, duration: Infinity, closeButton: true });
}

export { toast };
