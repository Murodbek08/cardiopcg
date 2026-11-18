import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
export const E2E_ROOT = resolve(here, '..');
export const AUTH_DIR = resolve(E2E_ROOT, '.auth');
export const USERS_FILE = resolve(AUTH_DIR, 'users.json');
export const WAV_FIXTURE = resolve(E2E_ROOT, 'fixtures', 'pcg-synthetic.wav');

export interface Creds { username: string; password: string; full_name: string; role: 'admin' | 'doctor' | 'nurse'; id?: string }
export interface TestUsers { admin: Creds; doctor: Creds; nurse: Creds }

/** Minimal KEY=VALUE reader for e2e/.e2e.env (written by scripts/setup-e2e.sh). Process env wins. */
export function loadEnvFile(): void {
  const f = resolve(E2E_ROOT, '.e2e.env');
  if (!existsSync(f)) return;
  for (const line of readFileSync(f, 'utf8').split(/\r?\n/)) {
    const m = /^([A-Z0-9_]+)=(.*)$/.exec(line.trim());
    if (m && process.env[m[1]] === undefined) process.env[m[1]] = m[2];
  }
}

export function baseUrl(): string {
  return process.env.E2E_BASE_URL ?? 'http://localhost:8080';
}

export function users(): TestUsers {
  return JSON.parse(readFileSync(USERS_FILE, 'utf8')) as TestUsers;
}
