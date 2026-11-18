import {
  IconLayoutDashboard, IconUsers, IconShieldLock, IconPill, IconFileAnalytics, IconSettings, IconBell, IconUsersGroup,
  IconStethoscope, IconChecklist, IconBrain, IconHome, IconPlus, type Icon,
} from '@tabler/icons-react';
import type { Role } from '@/shared/api/types';

export interface NavItem {
  to: string;
  labelKey: string; // nav namespace key
  icon: Icon;
  /** Exact match for active state (dashboards). */
  exact?: boolean;
  badge?: 'review';
}

export const NAV: Record<Role, NavItem[]> = {
  admin: [
    { to: '/admin', labelKey: 'dashboard', icon: IconLayoutDashboard, exact: true },
    { to: '/admin/users', labelKey: 'users', icon: IconUsers },
    { to: '/patients', labelKey: 'patients', icon: IconUsersGroup },
    { to: '/exams', labelKey: 'exams', icon: IconStethoscope },
    { to: '/admin/audit', labelKey: 'audit', icon: IconShieldLock },
    { to: '/admin/drugs', labelKey: 'drugs', icon: IconPill },
    { to: '/admin/reports', labelKey: 'reports', icon: IconFileAnalytics },
    { to: '/admin/settings', labelKey: 'settings', icon: IconSettings },
    { to: '/notifications', labelKey: 'notifications', icon: IconBell },
  ],
  doctor: [
    { to: '/doctor', labelKey: 'dashboard', icon: IconLayoutDashboard, exact: true },
    { to: '/patients', labelKey: 'patients', icon: IconUsersGroup },
    { to: '/exams', labelKey: 'exams', icon: IconStethoscope },
    { to: '/doctor/review-queue', labelKey: 'review_queue', icon: IconChecklist, badge: 'review' },
    { to: '/doctor/analyses', labelKey: 'analyses', icon: IconBrain },
    { to: '/reports', labelKey: 'reports', icon: IconFileAnalytics },
    { to: '/notifications', labelKey: 'notifications', icon: IconBell },
  ],
  nurse: [
    { to: '/nurse', labelKey: 'home', icon: IconHome, exact: true },
    { to: '/patients', labelKey: 'patients', icon: IconUsersGroup },
    { to: '/exams/new', labelKey: 'new_exam', icon: IconPlus },
    { to: '/notifications', labelKey: 'notifications', icon: IconBell },
  ],
};

export function homeFor(role: Role): string {
  return role === 'admin' ? '/admin' : role === 'doctor' ? '/doctor' : '/nurse';
}
