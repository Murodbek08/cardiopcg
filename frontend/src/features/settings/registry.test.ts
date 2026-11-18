import { describe, expect, it } from 'vitest';
import { coerceForSave, normalizeSettings, validateSetting } from './registry';
import type { SettingItem } from '@/shared/api/types';

const item = (key: string, value: unknown, value_type: SettingItem['value_type']): SettingItem => ({ key, value, value_type });

describe('settings validation', () => {
  it('enforces numeric bounds from the registry', () => {
    const it = item('security.lockout_attempts', 5, 'int');
    expect(validateSetting(it, 0, {})).toMatchObject({ code: 'min' });
    expect(validateSetting(it, 21, {})).toMatchObject({ code: 'max' });
    expect(validateSetting(it, 3.5, {})).toMatchObject({ code: 'integer' });
    expect(validateSetting(it, '', {})).toMatchObject({ code: 'required' });
    expect(validateSetting(it, 'abc', {})).toMatchObject({ code: 'number' });
    expect(validateSetting(it, 5, {})).toBeUndefined();
  });
  it('threshold is a probability 0..1', () => {
    const it = item('ai.critical_probability_threshold', 0.85, 'float');
    expect(validateSetting(it, 1.2, {})).toMatchObject({ code: 'max' });
    expect(validateSetting(it, 0.9, {})).toBeUndefined();
  });
  it('audio min duration must stay below max duration', () => {
    const min = item('audio.min_duration_sec', 5, 'int');
    expect(validateSetting(min, 130, { 'audio.min_duration_sec': 130, 'audio.max_duration_sec': 120 })).toMatchObject({ code: 'max' });
    expect(validateSetting(min, 60, { 'audio.min_duration_sec': 60, 'audio.max_duration_sec': 50 })).toMatchObject({ code: 'min_lt_max' });
  });
  it('restricts the LLM model to known options', () => {
    const it = item('ai.llm_model', 'deepseek-chat', 'string');
    expect(validateSetting(it, 'gpt-x', {})).toMatchObject({ code: 'option' });
    expect(validateSetting(it, 'deepseek-reasoner', {})).toBeUndefined();
  });
  it('validates json settings', () => {
    const it = item('custom.blob', {}, 'json');
    expect(validateSetting(it, '{bad', {})).toMatchObject({ code: 'json' });
    expect(validateSetting(it, '{"a":1}', {})).toBeUndefined();
  });
});

describe('settings normalisation', () => {
  it('accepts array, {items} and map forms', () => {
    expect(normalizeSettings([item('a', 1, 'int')])).toHaveLength(1);
    expect(normalizeSettings({ items: [item('a', 1, 'int')] })).toHaveLength(1);
    const m = normalizeSettings({ 'x.flag': true, 'x.n': 3, 'x.f': 1.5, 'x.s': 'v' });
    expect(m.map((i) => i.value_type)).toEqual(['bool', 'int', 'float', 'string']);
  });
  it('coerces numeric strings before saving', () => {
    expect(coerceForSave(item('upload.max_audio_mb', 25, 'int'), '30')).toBe(30);
  });
});
