import { expect, type Page } from '@playwright/test';
import type { Creds } from './env';

export const HOME: Record<Creds['role'], RegExp> = {
  admin: /\/admin$/,
  doctor: /\/doctor$/,
  nurse: /\/nurse$/,
};

/** Logs in through the real login form (Uzbek labels from the auth namespace). */
export async function loginViaUi(page: Page, u: Pick<Creds, 'username' | 'password' | 'role'>): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Foydalanuvchi nomi').fill(u.username);
  await page.getByRole('textbox', { name: 'Parol', exact: true }).fill(u.password);
  await page.getByRole('button', { name: 'Kirish' }).click();
  await expect(page).toHaveURL(HOME[u.role]);
}

/** The access-denied page rendered for a role that may not open the route. */
export async function expectForbidden(page: Page, path: string): Promise<void> {
  await page.goto(path);
  await expect(page).toHaveURL(/\/403$/);
  await expect(page.getByRole('heading', { name: "Ruxsat yo'q" })).toBeVisible();
}

/** No emoji code points anywhere in the visible text (project rule: icons, not emoji). */
export async function expectNoEmoji(page: Page): Promise<void> {
  const text = await page.locator('body').innerText();
  expect(/\p{Extended_Pictographic}/u.test(text), 'emoji found in visible UI text').toBe(false);
}
