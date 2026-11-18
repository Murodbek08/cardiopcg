import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, Outlet, useNavigate, useRouterState } from '@tanstack/react-router';
import { useTranslation } from 'react-i18next';
import {
  IconHeartbeat, IconMenu2, IconSearch, IconSun, IconMoon, IconDeviceDesktop, IconUser, IconLock, IconLogout,
  IconChevronsLeft, IconChevronsRight, IconWifiOff, IconPlus, IconX, type Icon as IconType,
} from '@tabler/icons-react';
import {
  Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
  ErrorBoundary, Dialog, Input, cn, useMediaQuery, useOnline, Tooltip,
} from '@/shared';
import { useAuthStore } from '@/shared/store/auth';
import { useThemeStore, type ThemeMode } from '@/shared/store/theme';
import { useUiStore } from '@/shared/store/ui';
import { logout } from '@/shared/api/session';
import type { Role } from '@/shared/api/types';
import { NotificationBell } from '@/features/notifications';
import { NAV, homeFor, type NavItem } from '../nav';

const THEME_ICON: Record<ThemeMode, typeof IconSun> = { light: IconSun, dark: IconMoon, system: IconDeviceDesktop };

function isActive(item: NavItem, path: string): boolean {
  return item.exact ? path === item.to : path === item.to || path.startsWith(`${item.to}/`);
}

function Logo({ collapsed }: { collapsed?: boolean }) {
  return (
    <Link to="/" className="flex items-center gap-2 rounded-md px-1 py-1 focus-visible:outline-2 focus-visible:outline-ring">
      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 text-white">
        <IconHeartbeat size={22} aria-hidden />
      </span>
      {!collapsed && <span className="text-h3 font-bold tracking-tight">CardioPCG AI</span>}
    </Link>
  );
}

function UserMenu() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const mode = useThemeStore((s) => s.mode);
  const setMode = useThemeStore((s) => s.setMode);
  if (!user) return null;
  const initials = user.full_name.split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase()).join('');
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="gap-2 px-2" aria-label={t('nav:user_menu')}>
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-100 text-xs font-bold text-brand-800">{initials}</span>
          <span className="hidden max-w-36 truncate text-sm md:inline">{user.full_name}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>
          {user.full_name}
          <span className="block font-normal">{t(`role.${user.role}`)}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void navigate({ to: '/profile' })}>
          <IconUser size={16} aria-hidden /> {t('nav:profile')}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => void navigate({ to: '/change-password' })}>
          <IconLock size={16} aria-hidden /> {t('nav:change_password')}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>{t('theme.label')}</DropdownMenuLabel>
        {(['light', 'dark', 'system'] as ThemeMode[]).map((m) => {
          const I = THEME_ICON[m];
          return (
            <DropdownMenuItem key={m} onSelect={() => setMode(m)} className={cn(mode === m && 'font-semibold')} aria-current={mode === m}>
              <I size={16} aria-hidden /> {t(`theme.${m}`)}
            </DropdownMenuItem>
          );
        })}
        <DropdownMenuSeparator />
        <DropdownMenuItem danger onSelect={() => void logout()}>
          <IconLogout size={16} aria-hidden /> {t('nav:logout')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function CommandPalette({ role }: { role: Role }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const open = useUiStore((s) => s.commandOpen);
  const setOpen = useUiStore((s) => s.setCommandOpen);
  const [q, setQ] = useState('');
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen(!useUiStore.getState().commandOpen);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setOpen]);
  const items = useMemo(
    () => NAV[role].filter((i) => t(`nav:${i.labelKey}`).toLowerCase().includes(q.trim().toLowerCase())),
    [role, q, t],
  );
  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) setQ(''); }} title={t('nav:command_palette')} size="sm">
      <Input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('nav:search_placeholder')} aria-label={t('nav:go_to')} />
      <ul className="mt-3 space-y-1">
        {items.length === 0 && <li className="px-2 py-3 text-sm text-muted">{t('nav:no_commands')}</li>}
        {items.map((i) => (
          <li key={i.to}>
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-ring"
              onClick={() => { setOpen(false); setQ(''); void navigate({ to: i.to }); }}
            >
              <i.icon size={18} aria-hidden /> {t(`nav:${i.labelKey}`)}
            </button>
          </li>
        ))}
      </ul>
    </Dialog>
  );
}

function SidebarNav({ role, collapsed, onNavigate }: { role: Role; collapsed?: boolean; onNavigate?: () => void }) {
  const { t } = useTranslation('nav');
  const path = useRouterState({ select: (s) => s.location.pathname });
  return (
    <nav aria-label={t('main_navigation')} className="flex flex-col gap-1 p-3">
      {NAV[role].map((item) => {
        const active = isActive(item, path);
        const link = (
          <Link
            key={item.to}
            to={item.to}
            onClick={onNavigate}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'flex h-11 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-ring',
              active ? 'bg-brand-50 text-brand-800 dark:bg-brand-900/40 dark:text-brand-100' : 'text-muted hover:bg-surface-2 hover:text-foreground',
              collapsed && 'justify-center px-0',
            )}
          >
            <item.icon size={20} aria-hidden />
            {collapsed ? <span className="sr-only">{t(item.labelKey)}</span> : <span className="truncate">{t(item.labelKey)}</span>}
          </Link>
        );
        return collapsed ? (
          <Tooltip key={item.to} content={t(item.labelKey)} side="right">
            {link}
          </Tooltip>
        ) : (
          link
        );
      })}
    </nav>
  );
}

/** Nurse tablet bottom navigation: 4 large buttons (min 56 px), centre FAB = new examination. */
function BottomNav() {
  const { t } = useTranslation('nav');
  const path = useRouterState({ select: (s) => s.location.pathname });
  const cell = (to: string, label: string, Icon: IconType, exact?: boolean, fab?: boolean) => {
    const active = exact ? path === to : path === to || path.startsWith(`${to}/`);
    return (
      <Link
        to={to}
        aria-current={active ? 'page' : undefined}
        className={cn('relative flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-xs font-medium focus-visible:outline-2 focus-visible:outline-ring', active ? 'text-brand-700 dark:text-brand-200' : 'text-muted')}
      >
        {fab ? (
          <span className="-mt-7 flex h-14 w-14 items-center justify-center rounded-full bg-brand-600 text-white shadow-pop">
            <Icon size={28} aria-hidden />
          </span>
        ) : (
          <Icon size={24} aria-hidden />
        )}
        <span>{label}</span>
      </Link>
    );
  };
  return (
    <nav aria-label={t('main_navigation')} className="no-print fixed inset-x-0 bottom-0 z-40 flex border-t border-border bg-surface pb-[env(safe-area-inset-bottom)] shadow-pop">
      {cell('/nurse', t('home'), NAV.nurse[0]!.icon, true)}
      {cell('/patients', t('patients'), NAV.nurse[1]!.icon)}
      {cell('/exams/new', t('new_exam'), IconPlus, false, true)}
      {cell('/notifications', t('notifications'), NAV.nurse[3]!.icon)}
    </nav>
  );
}

export function AppShell({ role, children }: { role: Role; children?: ReactNode }) {
  const { t } = useTranslation();
  const online = useOnline();
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  const toggle = useUiStore((s) => s.toggleSidebar);
  const mobileOpen = useUiStore((s) => s.mobileNavOpen);
  const setMobile = useUiStore((s) => s.setMobileNav);
  const setCommand = useUiStore((s) => s.setCommandOpen);
  const wide = useMediaQuery('(min-width: 1024px)');
  const nurseTablet = role === 'nurse' && !wide;
  const path = useRouterState({ select: (s) => s.location.pathname });

  useEffect(() => setMobile(false), [path, setMobile]);
  useEffect(() => {
    document.documentElement.classList.toggle('touch-ui', role === 'nurse');
    return () => document.documentElement.classList.remove('touch-ui');
  }, [role]);

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-[100] focus:rounded-md focus:bg-brand-600 focus:px-3 focus:py-2 focus:text-white">
        {t('app.skip_to_content')}
      </a>
      {!online && (
        <div role="status" className="no-print flex items-center justify-center gap-2 bg-warning-50 px-4 py-2 text-sm font-medium text-warning-500">
          <IconWifiOff size={16} aria-hidden /> {t('state.offline')}
        </div>
      )}
      <header className="no-print sticky top-0 z-30 flex h-16 items-center gap-2 border-b border-border bg-surface/95 px-3 backdrop-blur md:px-4">
        {!nurseTablet && (
          <Button variant="ghost" size="icon" className="lg:hidden" aria-label={t('nav:open_menu')} onClick={() => setMobile(true)}>
            <IconMenu2 size={22} aria-hidden />
          </Button>
        )}
        <Logo />
        <button
          type="button"
          onClick={() => setCommand(true)}
          className="ml-4 hidden h-10 max-w-sm flex-1 items-center gap-2 rounded-md border border-border bg-surface-2 px-3 text-sm text-muted hover:bg-border md:flex"
          aria-label={t('nav:command_palette')}
        >
          <IconSearch size={16} aria-hidden /> {t('nav:search_placeholder')}
        </button>
        <div className="ml-auto flex items-center gap-1">
          <Button variant="ghost" size="icon" className="md:hidden" aria-label={t('nav:command_palette')} onClick={() => setCommand(true)}>
            <IconSearch size={20} aria-hidden />
          </Button>
          <NotificationBell />
          <UserMenu />
        </div>
      </header>

      <div className="flex">
        {!nurseTablet && (
          <aside
            className={cn('no-print sticky top-16 hidden h-[calc(100dvh-4rem)] shrink-0 flex-col border-r border-border bg-surface transition-[width] lg:flex', collapsed ? 'w-[72px]' : 'w-[264px]')}
          >
            <div className="flex-1 overflow-y-auto">
              <SidebarNav role={role} collapsed={collapsed} />
            </div>
            <div className="border-t border-border p-3">
              <Button variant="ghost" className={cn('w-full', collapsed ? 'px-0' : 'justify-start')} onClick={toggle} aria-label={collapsed ? t('nav:expand') : t('nav:collapse')}>
                {collapsed ? <IconChevronsRight size={18} aria-hidden /> : <IconChevronsLeft size={18} aria-hidden />}
                {!collapsed && <span>{t('nav:collapse')}</span>}
              </Button>
            </div>
          </aside>
        )}
        <main id="main" tabIndex={-1} className={cn('mx-auto w-full max-w-[1440px] min-w-0 flex-1 p-4 outline-none md:p-6', nurseTablet && 'pb-28')}>
          <ErrorBoundary key={path}>{children ?? <Outlet />}</ErrorBoundary>
          <p className="no-print mt-10 border-t border-border pt-4 text-center text-xs text-muted">{t('app.disclaimer')}</p>
        </main>
      </div>

      {nurseTablet && <BottomNav />}

      {/* mobile drawer for admin/doctor < 1024px */}
      {!nurseTablet && mobileOpen && (
        <div className="no-print fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label={t('nav:main_navigation')}>
          <button type="button" aria-label={t('actions.close')} className="absolute inset-0 bg-black/50" onClick={() => setMobile(false)} />
          <div className="absolute inset-y-0 left-0 w-72 bg-surface shadow-pop">
            <div className="flex h-16 items-center justify-between border-b border-border px-3">
              <Logo />
              <Button variant="ghost" size="icon" aria-label={t('actions.close')} onClick={() => setMobile(false)}>
                <IconX size={20} aria-hidden />
              </Button>
            </div>
            <SidebarNav role={role} onNavigate={() => setMobile(false)} />
          </div>
        </div>
      )}
      <CommandPalette role={role} />
    </div>
  );
}

/** Picks the shell for the signed-in role (AdminShell / DoctorShell / NurseShell share one implementation). */
export const AdminShell = () => <AppShell role="admin" />;
export const DoctorShell = () => <AppShell role="doctor" />;
export const NurseShell = () => <AppShell role="nurse" />;

export function RoleShell() {
  const role = useAuthStore((s) => s.user?.role);
  if (!role) return null;
  return <AppShell role={role} />;
}

export { homeFor };
