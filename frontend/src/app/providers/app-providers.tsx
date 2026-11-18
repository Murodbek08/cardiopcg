import { useEffect, type ReactNode } from 'react';
import { QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { I18nextProvider } from 'react-i18next';
import i18n from '@/i18n';
import { makeQueryClient } from '@/shared/api/query';
import { TooltipProvider, Toaster, toast, toastCritical } from '@/shared/ui';
import { applyTheme, useThemeStore } from '@/shared/store/theme';
import { useAuthStore } from '@/shared/store/auth';
import { realtime } from '@/shared/api/realtime';
import type { NotificationItem } from '@/shared/api/types';

const queryClient = makeQueryClient();

function ThemeSync() {
  const mode = useThemeStore((s) => s.mode);
  useEffect(() => {
    applyTheme(mode);
    if (mode !== 'system') return;
    const m = window.matchMedia('(prefers-color-scheme: dark)');
    const on = () => applyTheme('system');
    m.addEventListener('change', on);
    return () => m.removeEventListener('change', on);
  }, [mode]);
  return null;
}

/** Keeps a WebSocket open while signed in and bridges server events into the query cache + toasts. */
function RealtimeBridge() {
  const qc = useQueryClient();
  const authed = useAuthStore((s) => s.status === 'authenticated');
  useEffect(() => {
    if (!authed) return;
    const off = realtime.on((ev) => {
      switch (ev.type) {
        case 'notification.new': {
          void qc.invalidateQueries({ queryKey: ['notifications'] });
          const n = ev.data as unknown as NotificationItem;
          if (n.type === 'critical_finding') toastCritical(n.title, n.body ?? undefined);
          else toast.info(n.title, { description: n.body ?? undefined });
          break;
        }
        case 'exam.status_changed':
        case 'analysis.completed':
        case 'analysis.failed':
        case 'conclusion.signed':
        case 'exam.created':
        case 'exam.assigned':
          void qc.invalidateQueries({ queryKey: ['exams'] });
          void qc.invalidateQueries({ queryKey: ['analytics'] });
          break;
        default:
          break;
      }
    });
    realtime.start();
    return () => {
      off();
      realtime.stop();
    };
  }, [authed, qc]);
  return null;
}

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider delayDuration={200}>
          <ThemeSync />
          <RealtimeBridge />
          {children}
          <Toaster />
        </TooltipProvider>
      </QueryClientProvider>
    </I18nextProvider>
  );
}

export { queryClient };
