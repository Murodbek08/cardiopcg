import { expect, test } from '@playwright/test';
import { Api, randomPassword, uniqueName } from '../helpers/api';
import { users } from '../helpers/env';
import { loginViaUi } from '../helpers/ui';

const U = users();

test.describe('admin: user management and audit', () => {
  test('admin creates a user in the UI; the new user must change the password at first login', async ({ page, request }) => {
    await loginViaUi(page, U.admin);

    const username = uniqueName('e2e.ui');
    const password = randomPassword();

    await page.goto('/admin/users/new');
    await page.getByLabel('Foydalanuvchi nomi').fill(username);
    await page.getByLabel('F.I.Sh.').fill('UI Yaratilgan Hamshira');
    await page.getByLabel('Vaqtinchalik parol').fill(password);
    await page.getByRole('button', { name: 'Yaratish', exact: true }).click();

    // one-shot dialog with the credentials
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Foydalanuvchi yaratildi')).toBeVisible();
    await expect(dialog.getByText(username)).toBeVisible();
    await dialog.getByRole('button', { name: 'Yopish' }).click();
    await expect(page).toHaveURL(/\/admin\/users\/[0-9a-f-]{36}$/);

    // listed in the users table
    await page.goto('/admin/users');
    await page.getByPlaceholder('Qidirish: ism yoki foydalanuvchi nomi').fill(username);
    await expect(page.getByText(username, { exact: true })).toBeVisible();

    // first login of the new user forces a password change
    const other = await page.context().browser()!.newContext({ baseURL: page.url().split('/admin')[0] });
    const p2 = await other.newPage();
    await p2.goto('/login');
    await p2.getByLabel('Foydalanuvchi nomi').fill(username);
    await p2.getByRole('textbox', { name: 'Parol', exact: true }).fill(password);
    await p2.getByRole('button', { name: 'Kirish' }).click();
    await expect(p2).toHaveURL(/\/change-password$/);
    await other.close();

    // the creation is in the audit trail (API)
    const admin = await Api.login(request, U.admin.username, U.admin.password);
    const logs = await (await admin.get('/audit-logs', { action: 'create', resource_type: 'user', limit: 50 })).json();
    expect(logs.items.length).toBeGreaterThan(0);
  });

  test('audit log page is visible to admin and is append-only', async ({ page, request }) => {
    await loginViaUi(page, U.admin);
    await page.goto('/admin/audit');
    await expect(page.getByRole('heading', { name: 'Audit log' })).toBeVisible();
    await expect(page.getByText("Faqat qo'shiladigan jurnal")).toBeVisible();
    // at least one data row besides the header (our own logins are in there)
    await expect.poll(async () => page.getByRole('row').count(), { timeout: 15_000 }).toBeGreaterThan(1);

    const admin = await Api.login(request, U.admin.username, U.admin.password);
    const list = await (await admin.get('/audit-logs', { limit: 20 })).json();
    expect(list.items.length).toBeGreaterThan(0);
    const first = list.items[0];
    // no way to edit or delete audit rows
    expect([404, 405]).toContain((await admin.patch(`/audit-logs/${first.id}`, { action: 'x' })).status());
    expect([404, 405]).toContain((await admin.delete(`/audit-logs/${first.id}`)).status());
  });

  test('admin can open settings, drugs and reports pages', async ({ page }) => {
    await loginViaUi(page, U.admin);
    for (const path of ['/admin/settings', '/admin/drugs', '/admin/reports', '/admin/users']) {
      await page.goto(path);
      await expect(page).toHaveURL(new RegExp(`${path}$`));
      await expect(page.getByRole('heading').first()).toBeVisible();
    }
  });
});
