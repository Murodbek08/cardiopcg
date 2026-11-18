import type { ComponentType } from 'react';
import {
  Outlet, RouterProvider, createRootRoute, createRoute, createRouter, lazyRouteComponent, redirect,
} from '@tanstack/react-router';
import { useAuthStore } from '@/shared/store/auth';
import type { Role } from '@/shared/api/types';
import { AuthLayout } from './shells/auth-layout';
import { SessionGuards } from './providers/session-guards';
import { ForbiddenPage, NotFoundPage, RouteError, ServerErrorPage } from './pages/error-pages';
import { homeFor } from './nav';

// ---------------------------------------------------------------- guards
function requireAuth({ location }: { location: { href: string; pathname: string } }) {
  const s = useAuthStore.getState();
  if (s.status !== 'authenticated' || !s.user) {
    throw redirect({ to: '/login', search: { next: location.href } as never, replace: true });
  }
  if (s.user.must_change_password && location.pathname !== '/change-password') {
    throw redirect({ to: '/change-password', replace: true });
  }
}
function requireRole(roles: Role[]) {
  return () => {
    const role = useAuthStore.getState().user?.role;
    if (!role || !roles.includes(role)) throw redirect({ to: '/403', replace: true });
  };
}
function redirectIfAuthed() {
  const s = useAuthStore.getState();
  if (s.status === 'authenticated' && s.user) throw redirect({ to: homeFor(s.user.role), replace: true });
}

// ---------------------------------------------------------------- routes
const rootRoute = createRootRoute({
  component: () => (
    <>
      <Outlet />
      <SessionGuards />
    </>
  ),
  notFoundComponent: NotFoundPage,
  errorComponent: ({ error, reset }) => <RouteError error={error as Error} reset={reset} />,
});

const withAuthLayout = (Page: ComponentType) => function WithLayout() {
  return (
    <AuthLayout>
      <Page />
    </AuthLayout>
  );
};
const lazy = <T extends string>(importer: () => Promise<Record<T, ComponentType>>, name: T) => lazyRouteComponent(importer as never, name as never) as ComponentType;

const authImport = () => import('@/features/auth');
const publicRoute = (path: string, name: 'LoginPage' | 'ForgotPasswordPage' | 'ResetPasswordPage', guard = true) =>
  createRoute({
    getParentRoute: () => rootRoute,
    path,
    beforeLoad: guard ? redirectIfAuthed : undefined,
    component: withAuthLayout(lazy(authImport as never, name)) as never,
  });

const loginRoute = publicRoute('/login', 'LoginPage');
const forgotRoute = publicRoute('/forgot-password', 'ForgotPasswordPage');
const resetRoute = publicRoute('/reset-password', 'ResetPasswordPage', false);
const forbiddenRoute = createRoute({ getParentRoute: () => rootRoute, path: '/403', component: ForbiddenPage });
const notFoundRoute = createRoute({ getParentRoute: () => rootRoute, path: '/404', component: NotFoundPage });
const serverErrorRoute = createRoute({ getParentRoute: () => rootRoute, path: '/500', component: ServerErrorPage });

const gateRoute = createRoute({ getParentRoute: () => rootRoute, id: 'gate', beforeLoad: requireAuth, component: Outlet });
const changePasswordRoute = createRoute({
  getParentRoute: () => gateRoute,
  path: '/change-password',
  component: lazy(authImport as never, 'ChangePasswordPage') as never,
});
const shellRoute = createRoute({ getParentRoute: () => gateRoute, id: 'shell', component: lazy(() => import('./shells/app-shell') as never, 'RoleShell') as never });

const indexRoute = createRoute({
  getParentRoute: () => shellRoute,
  path: '/',
  beforeLoad: () => {
    const role = useAuthStore.getState().user?.role;
    throw redirect({ to: role ? homeFor(role) : '/login', replace: true });
  },
});

const ALL_ROLES: Role[] = ['admin', 'doctor', 'nurse'];
const shellChild = (path: string, component: ComponentType, roles: Role[] = ALL_ROLES) =>
  createRoute({ getParentRoute: () => shellRoute, path, beforeLoad: requireRole(roles), component: component as never });

const profileRoute = shellChild('/profile', lazy(authImport as never, 'ProfilePage'));
const notificationsRoute = shellChild('/notifications', lazy(() => import('@/features/notifications') as never, 'NotificationsPage'));

// ---- admin
const usersImport = () => import('@/features/users');
const drugsImport = () => import('@/features/drugs');
const adminRoutes = [
  shellChild('/admin', lazy(() => import('@/features/dashboard/admin') as never, 'AdminDashboardPage'), ['admin']),
  shellChild('/admin/users', lazy(usersImport as never, 'UsersListPage'), ['admin']),
  shellChild('/admin/users/new', lazy(usersImport as never, 'UserCreatePage'), ['admin']),
  shellChild('/admin/users/$id', lazy(usersImport as never, 'UserDetailPage'), ['admin']),
  shellChild('/admin/audit', lazy(() => import('@/features/audit') as never, 'AuditPage'), ['admin']),
  shellChild('/admin/settings', lazy(() => import('@/features/settings') as never, 'SettingsPage'), ['admin']),
  shellChild('/admin/drugs', lazy(drugsImport as never, 'DrugsListPage'), ['admin']),
  shellChild('/admin/drugs/new', lazy(drugsImport as never, 'DrugEditPage'), ['admin']),
  shellChild('/admin/drugs/$id', lazy(drugsImport as never, 'DrugEditPage'), ['admin']),
  shellChild('/admin/reports', lazy(() => import('@/features/reports') as never, 'ReportsPage'), ['admin']),
];

// ---- shared (admin read-only, doctor, nurse). Doctor/nurse specific screens are registered below from feature route lists.
const patientsImport = () => import('@/features/patients');
const examsImport = () => import('@/features/exams');
const doctorImport = () => import('@/features/doctor');
const nurseImport = () => import('@/features/nurse');
const patientsImportB = patientsImport;
const clinical: Role[] = ['doctor', 'nurse'];
const sharedRoutes = [
  shellChild('/patients', lazy(patientsImport as never, 'PatientsListPage')),
  shellChild('/patients/new', lazy(patientsImportB as never, 'PatientFormPage'), clinical),
  shellChild('/patients/$id', lazy(patientsImport as never, 'PatientDetailPage')),
  shellChild('/patients/$id/edit', lazy(patientsImportB as never, 'PatientFormPage'), clinical),
  shellChild('/patients/$id/timeline', lazy(patientsImportB as never, 'PatientTrendsPage'), clinical),
  shellChild('/exams', lazy(examsImport as never, 'ExamsListPage')),
  shellChild('/exams/new', lazy(examsImport as never, 'ExamWizardPage'), clinical),
  shellChild('/exams/$id', lazy(examsImport as never, 'ExamWorkspacePage')),
  shellChild('/exams/$id/progress', lazy(examsImport as never, 'ExamProgressPage'), clinical),
  shellChild('/exams/$id/report', lazy(examsImport as never, 'ExamReportPage'), clinical),
  shellChild('/reports', lazy(() => import('@/features/reports') as never, 'ReportsPage'), ['doctor']),
];

// ---- doctor / nurse dashboards and doctor tools
const roleRoutes = [
  shellChild('/doctor', lazy(doctorImport as never, 'DoctorDashboardPage'), ['doctor']),
  shellChild('/doctor/review-queue', lazy(doctorImport as never, 'ReviewQueuePage'), ['doctor']),
  shellChild('/doctor/analyses', lazy(doctorImport as never, 'AnalysesPage'), ['doctor']),
  shellChild('/nurse', lazy(nurseImport as never, 'NurseDashboardPage'), ['nurse']),
];

const routeTree = rootRoute.addChildren([
  loginRoute,
  forgotRoute,
  resetRoute,
  forbiddenRoute,
  notFoundRoute,
  serverErrorRoute,
  gateRoute.addChildren([changePasswordRoute, shellRoute.addChildren([indexRoute, profileRoute, notificationsRoute, ...adminRoutes, ...sharedRoutes, ...roleRoutes])]),
]);

export const router = createRouter({
  routeTree,
  defaultPreload: 'intent',
  defaultPreloadStaleTime: 0,
  scrollRestoration: true,
  defaultNotFoundComponent: NotFoundPage,
  defaultErrorComponent: ({ error, reset }) => <RouteError error={error as Error} reset={reset} />,
});

export function AppRouter() {
  return <RouterProvider router={router} />;
}
