import { expect, test } from '@playwright/test';
import { Api } from '../helpers/api';
import { users } from '../helpers/env';
import { HOME, expectForbidden, expectNoEmoji, loginViaUi } from '../helpers/ui';

const U = users();

test.describe('login per role', () => {
  for (const role of ['admin', 'doctor', 'nurse'] as const) {
    test(`${role} signs in and lands on the role home`, async ({ page }) => {
      await loginViaUi(page, U[role]);
      await expect(page).toHaveURL(HOME[role]);
      await expectNoEmoji(page);
    });
  }

  test('session survives a reload (refresh cookie)', async ({ page }) => {
    await loginViaUi(page, U.admin);
    await page.reload();
    await expect(page).toHaveURL(HOME.admin);
  });

  test('wrong password shows a generic error and stays on /login', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('Foydalanuvchi nomi').fill(U.nurse.username);
    await page.getByRole('textbox', { name: 'Parol', exact: true }).fill('definitely-wrong-Passw0rd');
    await page.getByRole('button', { name: 'Kirish' }).click();
    await expect(page.getByText("Foydalanuvchi nomi yoki parol noto'g'ri")).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });
});

test.describe('RBAC redirects', () => {
  test('anonymous user is redirected to /login', async ({ page }) => {
    await page.goto('/patients');
    await expect(page).toHaveURL(/\/login/);
  });

  test('nurse cannot open admin or doctor pages', async ({ page }) => {
    await loginViaUi(page, U.nurse);
    await expectForbidden(page, '/admin');
    await expectForbidden(page, '/admin/users');
    await expectForbidden(page, '/doctor');
  });

  test('doctor cannot open admin pages', async ({ page }) => {
    await loginViaUi(page, U.doctor);
    await expectForbidden(page, '/admin');
    await expectForbidden(page, '/admin/audit');
    await expectForbidden(page, '/admin/settings');
  });

  test('admin cannot open doctor-only pages', async ({ page }) => {
    await loginViaUi(page, U.admin);
    await expectForbidden(page, '/doctor');
  });

  test('API enforces RBAC independently of the UI', async ({ request }) => {
    const nurse = await Api.login(request, U.nurse.username, U.nurse.password);
    const doctor = await Api.login(request, U.doctor.username, U.doctor.password);
    expect((await nurse.get('/users')).status()).toBe(403);
    expect((await nurse.get('/audit-logs')).status()).toBe(403);
    expect((await nurse.get('/settings')).status()).toBe(403);
    expect((await doctor.get('/users')).status()).toBe(403);
    expect((await doctor.get('/settings')).status()).toBe(403);
    expect((await request.get('/api/v1/auth/me')).status()).toBe(401);
  });
});
