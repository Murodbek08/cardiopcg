import { useEffect, useRef, useState } from 'react';
import { useNavigate, useRouterState } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { useAuthStore } from '@/shared/store/auth';
import { logout } from '@/shared/api/session';
import { Button, Dialog } from '@/shared/ui';

const IDLE_MS = 15 * 60_000;
const WARN_MS = 60_000;

/**
 * Redirects to /login when the session ends and explains why (session expired / refresh-token reuse / idle).
 * Also enforces a 15 minute inactivity logout with a 1 minute warning (WCAG timing, doc 03 section 11/14).
 */
export function SessionGuards() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const status = useAuthStore((s) => s.status);
  const reason = useAuthStore((s) => s.logoutReason);
  const clearReason = useAuthStore((s) => s.clearReason);
  const pathname = useRouterState({ select: (s) => s.location.pathname + s.location.searchStr });
  const lastPath = useRef(pathname);
  useEffect(() => {
    if (status === 'authenticated') lastPath.current = pathname;
  }, [status, pathname]);

  // ---- idle tracking ----
  const [warn, setWarn] = useState(false);
  const [left, setLeft] = useState(60);
  const lastActivity = useRef(0);
  useEffect(() => {
    if (status !== 'authenticated') {
      lastActivity.current = 0;
      return;
    }
    if (lastActivity.current === 0) lastActivity.current = Date.now();
    const bump = () => {
      if (!warn) lastActivity.current = Date.now();
    };
    const evts = ['mousemove', 'keydown', 'click', 'touchstart', 'scroll'] as const;
    evts.forEach((e) => window.addEventListener(e, bump, { passive: true }));
    const id = setInterval(() => {
      const idle = Date.now() - lastActivity.current;
      if (idle >= IDLE_MS) {
        setWarn(false);
        void logout('idle');
      } else if (idle >= IDLE_MS - WARN_MS) {
        setWarn(true);
        setLeft(Math.max(0, Math.ceil((IDLE_MS - idle) / 1000)));
      }
    }, 1000);
    return () => {
      evts.forEach((e) => window.removeEventListener(e, bump));
      clearInterval(id);
    };
  }, [status, warn]);

  // ---- redirect when anonymous inside the app ----
  useEffect(() => {
    if (status !== 'anonymous') return;
    const here = window.location.pathname;
    if (here.startsWith('/login') || here.startsWith('/reset-password') || here.startsWith('/forgot-password')) return;
    if (reason === null || reason === 'logout') {
      void navigate({ to: '/login', replace: true });
    }
  }, [status, reason, navigate]);

  const expired = status === 'anonymous' && (reason === 'session_expired' || reason === 'token_reuse' || reason === 'idle');

  return (
    <>
      <Dialog
        open={warn && status === 'authenticated'}
        onOpenChange={() => undefined}
        dismissible={false}
        title={t('session.idle_title')}
        description={t('session.idle_body')}
        size="sm"
        footer={
          <>
            <Button variant="outline" onClick={() => void logout('idle')}>
              {t('nav:logout')}
            </Button>
            <Button
              onClick={() => {
                lastActivity.current = Date.now();
                setWarn(false);
              }}
            >
              {t('session.extend')}
            </Button>
          </>
        }
      >
        <p className="text-center text-h1 font-bold tabular-nums" role="timer" aria-live="polite">
          {left}
        </p>
      </Dialog>
      <Dialog
        open={expired}
        onOpenChange={() => undefined}
        dismissible={false}
        title={t('session.expired_title')}
        description={reason === 'token_reuse' ? t('session.reuse_body') : t('session.expired_body')}
        size="sm"
        footer={
          <Button
            onClick={() => {
              clearReason();
              void navigate({ to: '/login', search: { next: lastPath.current } as never, replace: true });
            }}
          >
            {t('session.login_again')}
          </Button>
        }
      />
    </>
  );
}
