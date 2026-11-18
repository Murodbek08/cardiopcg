import { describe, expect, it } from 'vitest';
import { diffJson, flatten } from './json-diff';
import { auditRangeOk } from '../api';

describe('json diff', () => {
  it('flattens nested objects', () => {
    expect(flatten({ a: { b: 1 }, c: [1, 2] })).toEqual({ 'a.b': '1', c: '[1,2]' });
  });
  it('classifies added/removed/changed/same', () => {
    const rows = diffJson({ status: 'draft', same: 1, gone: true }, { status: 'uploaded', same: 1, fresh: 'x' });
    const kind = Object.fromEntries(rows.map((r) => [r.path, r.kind]));
    expect(kind).toEqual({ status: 'changed', same: 'same', gone: 'removed', fresh: 'added' });
  });
});

describe('audit range (<= 90 days per request)', () => {
  it('accepts <= 90 days, rejects longer or inverted', () => {
    expect(auditRangeOk('2026-11-01', '2026-11-18')).toBe(true);
    expect(auditRangeOk('2026-01-01', '2026-11-18')).toBe(false);
    expect(auditRangeOk('2026-11-18', '2026-11-01')).toBe(false);
  });
});
