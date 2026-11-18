import { describe, expect, it } from 'vitest';
import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios';
import { ApiError, fieldErrorMap, normalizeError } from './errors';

function axiosErr(status: number | null, data?: unknown, headers: Record<string, string> = {}) {
  const config = { headers: new AxiosHeaders() } as InternalAxiosRequestConfig;
  const e = new AxiosError('boom', status ? 'ERR_BAD_REQUEST' : 'ERR_NETWORK', config);
  if (status) e.response = { status, data, headers, statusText: '', config };
  return e;
}

describe('normalizeError', () => {
  it('parses the backend envelope (code, message, request_id, field errors)', () => {
    const err = normalizeError(
      axiosErr(422, { error: { code: 'VALIDATION_ERROR', message: 'bad', request_id: 'rid-1', details: [{ field: 'body.birth_date', msg: 'future', type: 'value_error' }] } }),
    );
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422);
    expect(err.code).toBe('VALIDATION_ERROR');
    expect(err.requestId).toBe('rid-1');
    expect(fieldErrorMap(err)).toEqual({ birth_date: 'future' });
  });

  it('keeps object details (e.g. locked_until) and Retry-After', () => {
    const err = normalizeError(axiosErr(429, { error: { code: 'RATE_LIMITED', message: 'x', details: { locked_until: '2026-11-18T10:00:00Z' } } }, { 'retry-after': '30' }));
    expect(err.retryAfter).toBe(30);
    expect(err.details?.locked_until).toBe('2026-11-18T10:00:00Z');
  });

  it('marks network failures', () => {
    const err = normalizeError(axiosErr(null));
    expect(err.isNetwork).toBe(true);
    expect(err.status).toBe(0);
  });

  it('falls back gracefully for non-axios errors', () => {
    expect(normalizeError(new Error('x')).code).toBe('UNKNOWN');
    expect(normalizeError('weird').message).toBeTruthy();
  });
});
