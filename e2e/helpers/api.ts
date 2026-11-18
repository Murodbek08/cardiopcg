import { expect, type APIRequestContext, type APIResponse } from '@playwright/test';
import { randomBytes } from 'node:crypto';

/** Thin typed wrapper around the REST API (/api/v1) for test setup and verification. */
export class Api {
  constructor(private readonly request: APIRequestContext, private token = '') {}

  static async login(request: APIRequestContext, username: string, password: string): Promise<Api> {
    const r = await request.post('/api/v1/auth/login', { data: { username, password } });
    expect(r.status(), `login ${username}: ${await r.text()}`).toBe(200);
    const body = (await r.json()) as { access_token: string };
    return new Api(request, body.access_token);
  }

  private headers(): Record<string, string> {
    return { Authorization: `Bearer ${this.token}` };
  }
  get(url: string, params?: Record<string, string | number | boolean>): Promise<APIResponse> {
    return this.request.get(`/api/v1${url}`, { headers: this.headers(), params });
  }
  post(url: string, data?: unknown): Promise<APIResponse> {
    return this.request.post(`/api/v1${url}`, { headers: this.headers(), data });
  }
  put(url: string, data?: unknown): Promise<APIResponse> {
    return this.request.put(`/api/v1${url}`, { headers: this.headers(), data });
  }
  patch(url: string, data?: unknown): Promise<APIResponse> {
    return this.request.patch(`/api/v1${url}`, { headers: this.headers(), data });
  }
  delete(url: string): Promise<APIResponse> {
    return this.request.delete(`/api/v1${url}`, { headers: this.headers() });
  }
  upload(url: string, file: { name: string; mimeType: string; buffer: Buffer }, fields: Record<string, string> = {}): Promise<APIResponse> {
    return this.request.post(`/api/v1${url}`, { headers: this.headers(), multipart: { file, ...fields } });
  }
}

/** Random throw-away password for test accounts (satisfies the strength policy; never reused outside the run). */
export function randomPassword(): string {
  return `${randomBytes(15).toString('base64url')}-Aa1`;
}

export function uniqueName(prefix: string): string {
  return `${prefix}.${randomBytes(3).toString('hex')}`;
}
