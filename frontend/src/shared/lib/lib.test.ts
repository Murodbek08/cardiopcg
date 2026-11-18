import { describe, expect, it } from 'vitest';
import { checkPassword, generatePassword, passwordScore } from './password';
import { safeNext } from './url';
import { can } from './permissions';
import { maskName, maskPhone } from './mask';
import { normalizePage } from './normalize';
import { formatBytes, formatDuration, formatNumber, formatPercent, toIsoDate } from './format';
import { validateRange, resolvePeriod } from '@/shared/ui/period-picker';
import { backoffMs } from '@/shared/api/sse';
import { jwtExpiry } from '@/shared/api/session';
import { nextSort } from '@/shared/ui/data-table';

describe('password helpers', () => {
  it('checks rules', () => {
    expect(checkPassword('short')).toEqual({ length: false, case: false, digit: false, special: false });
    expect(checkPassword('Abcdefghij1!')).toEqual({ length: true, case: true, digit: true, special: true });
  });
  it('scores weak/common passwords low and long mixed ones high', () => {
    expect(passwordScore('')).toBe(0);
    expect(passwordScore('password123')).toBeLessThanOrEqual(1);
    expect(passwordScore('Zq7!mK2#vR9@pL4$')).toBeGreaterThanOrEqual(3);
  });
  it('generates compliant random passwords', () => {
    const a = generatePassword();
    const b = generatePassword();
    expect(a).not.toBe(b);
    expect(a.length).toBe(16);
    const c = checkPassword(a, 12);
    expect(c.length && c.case && c.digit && c.special).toBe(true);
  });
});

describe('safeNext (open redirect guard)', () => {
  it.each([
    ['/admin/users?page=2', '/admin/users?page=2'],
    ['//evil.example', '/'],
    ['https://evil.example', '/'],
    ['/\\evil.example', '/'],
    ['/login?next=/x', '/'],
    [undefined, '/'],
    [42, '/'],
  ])('%s -> %s', (input, expected) => expect(safeNext(input)).toBe(expected));
});

describe('UI permission matrix', () => {
  it('admin manages users/settings but cannot sign conclusions or see unmasked patients', () => {
    expect(can('admin', 'user:manage')).toBe(true);
    expect(can('admin', 'settings:write')).toBe(true);
    expect(can('admin', 'exam:edit_conclusion')).toBe(false);
    expect(can('admin', 'patient:read_unmasked')).toBe(false);
    expect(can('admin', 'exam:create')).toBe(false);
  });
  it('doctor approves drugs and exports; nurse cannot', () => {
    expect(can('doctor', 'prescription:approve')).toBe(true);
    expect(can('doctor', 'patient:export')).toBe(true);
    expect(can('nurse', 'prescription:approve')).toBe(false);
    expect(can('nurse', 'exam:edit_conclusion')).toBe(false);
    expect(can('nurse', 'patient:export')).toBe(false);
    expect(can('nurse', 'exam:create')).toBe(true);
  });
  it('no role = no access', () => expect(can(null, 'patient:read')).toBe(false));
});

describe('masking', () => {
  it('masks names to initials', () => expect(maskName('Karimov Aziz Anvarovich')).toBe('K*** A***'));
  it('handles empty', () => expect(maskName(null)).toBe('-'));
  it('masks phone', () => expect(maskPhone('+998901234567')).toMatch(/^\+998\*+67$/));
});

describe('normalizePage', () => {
  it('handles cursor, offset and array envelopes', () => {
    expect(normalizePage({ items: [1], page: { total: 9, next_cursor: 'c' } })).toEqual({ items: [1], total: 9, nextCursor: 'c' });
    expect(normalizePage({ items: [1, 2], total: 2 })).toEqual({ items: [1, 2], total: 2, nextCursor: null });
    expect(normalizePage([1, 2, 3])).toEqual({ items: [1, 2, 3], total: 3, nextCursor: null });
    expect(normalizePage(undefined).items).toEqual([]);
  });
});

describe('format helpers', () => {
  it('formats bytes, durations, percent, null-safe', () => {
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(null)).toBe('-');
    expect(formatDuration(75)).toBe('01:15');
    expect(formatPercent(null)).toBe('-');
    expect(formatNumber(undefined)).toBe('-');
  });
  it('uses the Tashkent calendar day', () => {
    // 2026-11-17T20:00Z is already 18 Nov in Asia/Tashkent (UTC+5)
    expect(toIsoDate(new Date('2026-11-17T20:00:00Z'))).toBe('2026-11-18');
  });
});

describe('period validation (1-365 days, from <= to)', () => {
  it('accepts valid and rejects invalid ranges', () => {
    expect(validateRange('2026-01-01', '2026-01-31')).toBe(true);
    expect(validateRange('2026-01-31', '2026-01-01')).toBe(false);
    expect(validateRange('2025-01-01', '2026-06-01')).toBe(false);
    expect(validateRange('', '2026-01-01')).toBe(false);
  });
  it('resolves presets', () => {
    const p = resolvePeriod('7d');
    expect(p.from <= p.to).toBe(true);
    expect(validateRange(p.from, p.to)).toBe(true);
  });
});

describe('transport helpers', () => {
  it('exponential backoff caps at 30 s', () => {
    expect([0, 1, 2, 3].map(backoffMs)).toEqual([1000, 2000, 4000, 8000]);
    expect(backoffMs(20)).toBe(30_000);
  });
  it('decodes JWT exp without trusting it', () => {
    const payload = btoa(JSON.stringify({ exp: 1234567890 })).replace(/=/g, '');
    expect(jwtExpiry(`h.${payload}.s`)).toBe(1234567890);
    expect(jwtExpiry('garbage')).toBeNull();
  });
  it('sort toggles asc -> desc -> none', () => {
    expect(nextSort(undefined, 'name')).toBe('name');
    expect(nextSort('name', 'name')).toBe('-name');
    expect(nextSort('-name', 'name')).toBeUndefined();
    expect(nextSort('other', 'name')).toBe('name');
  });
});
