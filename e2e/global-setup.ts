import { request } from '@playwright/test';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { Api, randomPassword, uniqueName } from './helpers/api';
import { AUTH_DIR, USERS_FILE, WAV_FIXTURE, baseUrl, loadEnvFile, type TestUsers } from './helpers/env';
// @ts-expect-error plain ESM script without type declarations
import { makePcgWav } from './scripts/gen-wav.mjs';

/**
 * 1. make sure the synthetic WAV fixture exists
 * 2. log in as the test admin created by scripts/setup-e2e.sh (backend/scripts/create_admin.py)
 * 3. create a fresh doctor and nurse for this run through the admin API (random passwords, no forced change)
 */
export default async function globalSetup(): Promise<void> {
  loadEnvFile();
  if (!existsSync(WAV_FIXTURE)) {
    mkdirSync(WAV_FIXTURE.replace(/[\\/][^\\/]+$/, ''), { recursive: true });
    writeFileSync(WAV_FIXTURE, makePcgWav({ seconds: 8, sampleRate: 4000 }));
  }

  const adminUser = process.env.E2E_ADMIN_USERNAME;
  const adminPass = process.env.E2E_ADMIN_PASSWORD;
  if (!adminUser || !adminPass) {
    throw new Error('E2E_ADMIN_USERNAME / E2E_ADMIN_PASSWORD missing - run `bash scripts/setup-e2e.sh` first');
  }

  const ctx = await request.newContext({ baseURL: baseUrl() });
  const admin = await Api.login(ctx, adminUser, adminPass);

  const mk = async (role: 'doctor' | 'nurse') => {
    const username = uniqueName(`e2e.${role}`);
    const password = randomPassword();
    const full_name = role === 'doctor' ? 'E2E Shifokor' : 'E2E Hamshira';
    const body: Record<string, unknown> = { username, full_name, role, password, must_change_password: false };
    if (role === 'doctor') Object.assign(body, { specialty: 'Kardiologiya', license_no: `E2E-${Date.now()}` });
    else Object.assign(body, { department: 'Kardiologiya' });
    const r = await admin.post('/users', body);
    if (r.status() !== 201 && r.status() !== 200) throw new Error(`create ${role} failed: ${r.status()} ${await r.text()}`);
    const created = (await r.json()) as { id: string };
    return { username, password, full_name, role, id: created.id };
  };

  const users: TestUsers = {
    admin: { username: adminUser, password: adminPass, full_name: 'E2E Administrator', role: 'admin' },
    doctor: await mk('doctor'),
    nurse: await mk('nurse'),
  };
  mkdirSync(AUTH_DIR, { recursive: true });
  writeFileSync(USERS_FILE, JSON.stringify(users), { mode: 0o600 });
  await ctx.dispose();
}
