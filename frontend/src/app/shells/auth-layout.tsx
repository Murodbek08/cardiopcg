import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { IconHeartbeat, IconShieldCheck, IconWaveSine, IconStethoscope } from '@tabler/icons-react';

/** Split layout for login / password flows. Brand panel is shown from 1024 px. */
export function AuthLayout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="grid min-h-dvh bg-background text-foreground lg:grid-cols-2">
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-brand-800 p-12 text-white lg:flex">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/15">
            <IconHeartbeat size={26} aria-hidden />
          </span>
          <span className="text-h2 font-bold">{t('app.name')}</span>
        </div>
        <div className="max-w-md">
          <h2 className="text-display font-bold leading-tight">{t('auth:login.brand_title')}</h2>
          <p className="mt-4 text-base text-white/80">{t('auth:login.brand_body')}</p>
          <ul className="mt-8 space-y-3 text-sm text-white/85">
            <li className="flex items-center gap-3"><IconWaveSine size={20} aria-hidden /> S1 / S2, HR, shovqin</li>
            <li className="flex items-center gap-3"><IconStethoscope size={20} aria-hidden /> {t('auth:login.brand_title')}</li>
            <li className="flex items-center gap-3"><IconShieldCheck size={20} aria-hidden /> Audit + RBAC</li>
          </ul>
        </div>
        <p className="text-xs text-white/60">{t('app.disclaimer')}</p>
      </aside>
      <main id="main" className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2 lg:hidden">
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-600 text-white">
              <IconHeartbeat size={24} aria-hidden />
            </span>
            <span className="text-h2 font-bold">{t('app.name')}</span>
          </div>
          {children}
          <p className="mt-8 text-center text-xs text-muted lg:hidden">{t('app.disclaimer')}</p>
        </div>
      </main>
    </div>
  );
}
