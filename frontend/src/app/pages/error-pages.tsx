import { Link, useNavigate } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import { IconLock, IconMapOff, IconAlertOctagon, type Icon } from '@tabler/icons-react';
import { Button, ErrorState } from '@/shared';
import { useAuthStore } from '@/shared/store/auth';
import { homeFor } from '../nav';

function Shell({ icon: I, title, body }: { icon: Icon; title: string; body: string }) {
  const { t } = useTranslation('errors');
  const role = useAuthStore((s) => s.user?.role);
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-3 bg-background p-6 text-center text-foreground">
      <span className="flex h-14 w-14 items-center justify-center rounded-full bg-surface-2 text-muted"><I size={28} aria-hidden /></span>
      <h1 className="text-h1 font-semibold">{title}</h1>
      <p className="max-w-sm text-sm text-muted">{body}</p>
      <Button asChild><Link to={role ? homeFor(role) : '/login'}>{t('go_home')}</Link></Button>
    </main>
  );
}

export function ForbiddenPage() {
  const { t } = useTranslation('errors');
  return <Shell icon={IconLock} title={t('forbidden')} body={t('forbidden_body')} />;
}
export function NotFoundPage() {
  const { t } = useTranslation('errors');
  return <Shell icon={IconMapOff} title={t('not_found')} body={t('not_found_body')} />;
}
export function ServerErrorPage() {
  const { t } = useTranslation('errors');
  return <Shell icon={IconAlertOctagon} title={t('server')} body={t('server_body')} />;
}

/** Route-level errorComponent. */
export function RouteError({ error, reset }: { error: Error; reset: () => void }) {
  const navigate = useNavigate();
  return (
    <div className="mx-auto max-w-md py-16">
      <ErrorState error={error} onRetry={() => { reset(); void navigate({ to: '.' }); }} />
    </div>
  );
}
