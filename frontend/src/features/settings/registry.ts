import type { SettingItem, SettingValueType } from '@/shared/api/types';

export type SettingGroup = 'ai' | 'limits' | 'security' | 'retention' | 'clinic' | 'other';

export interface SettingMeta {
  group: SettingGroup;
  type: SettingValueType;
  min?: number;
  max?: number;
  options?: string[];
  /** Changing this setting asks for explicit confirmation (clinical/security impact). */
  risky?: boolean;
  unit?: string;
}

/** Known keys from doc 01, section 1.16 with sensible bounds. Unknown keys still work via value_type. */
export const SETTINGS_REGISTRY: Record<string, SettingMeta> = {
  'upload.max_audio_mb': { group: 'limits', type: 'int', min: 1, max: 200, unit: 'MB' },
  'upload.max_image_mb': { group: 'limits', type: 'int', min: 1, max: 50, unit: 'MB' },
  'upload.max_files_per_exam': { group: 'limits', type: 'int', min: 1, max: 50 },
  'audio.min_duration_sec': { group: 'limits', type: 'int', min: 1, max: 60, unit: 's' },
  'audio.max_duration_sec': { group: 'limits', type: 'int', min: 5, max: 600, unit: 's' },
  'analysis.auto_start': { group: 'ai', type: 'bool' },
  'analysis.model_version': { group: 'ai', type: 'string', risky: true },
  'ai.llm_model': { group: 'ai', type: 'string', options: ['deepseek-chat', 'deepseek-reasoner'], risky: true },
  'ai.llm_enabled': { group: 'ai', type: 'bool', risky: true },
  'ai.drug_suggestions_enabled': { group: 'ai', type: 'bool', risky: true },
  'ai.critical_probability_threshold': { group: 'ai', type: 'float', min: 0, max: 1, risky: true },
  'security.lockout_attempts': { group: 'security', type: 'int', min: 1, max: 20, risky: true },
  'security.lockout_minutes': { group: 'security', type: 'int', min: 1, max: 1440, risky: true, unit: 'min' },
  'security.password_min_length': { group: 'security', type: 'int', min: 8, max: 64, risky: true },
  'retention.audit_days': { group: 'retention', type: 'int', min: 30, max: 36500, unit: 'kun' },
  'retention.raw_llm_days': { group: 'retention', type: 'int', min: 1, max: 3650, unit: 'kun' },
  'clinic.name': { group: 'clinic', type: 'string' },
  'clinic.logo_key': { group: 'clinic', type: 'string' },
  'clinic.report_footer': { group: 'clinic', type: 'string' },
};

export function metaFor(item: SettingItem): SettingMeta {
  return SETTINGS_REGISTRY[item.key] ?? { group: groupFromKey(item.key), type: item.value_type };
}

export function groupFromKey(key: string): SettingGroup {
  const p = key.split('.')[0];
  if (p === 'ai' || p === 'analysis') return 'ai';
  if (p === 'upload' || p === 'audio') return 'limits';
  if (p === 'security') return 'security';
  if (p === 'retention') return 'retention';
  if (p === 'clinic') return 'clinic';
  return 'other';
}

/** Accepts array form, `{items: []}` or a plain `{key: value}` map. */
export function normalizeSettings(raw: unknown): SettingItem[] {
  if (Array.isArray(raw)) return raw as SettingItem[];
  if (raw && typeof raw === 'object') {
    const o = raw as Record<string, unknown>;
    if (Array.isArray(o.items)) return o.items as SettingItem[];
    return Object.entries(o).map(([key, value]) => ({
      key,
      value,
      value_type: typeof value === 'boolean' ? 'bool' : typeof value === 'number' ? (Number.isInteger(value) ? 'int' : 'float') : typeof value === 'string' ? 'string' : 'json',
    }));
  }
  return [];
}

export type Draft = Record<string, unknown>;

export type SettingError = { code: 'required' | 'integer' | 'number' | 'min' | 'max' | 'option' | 'json' | 'min_lt_max'; min?: number; max?: number };

/** Validates one value (and cross-field rules). Returns undefined when valid. */
export function validateSetting(item: SettingItem, value: unknown, all: Draft): SettingError | undefined {
  const m = metaFor(item);
  switch (m.type) {
    case 'bool':
      return undefined;
    case 'int':
    case 'float': {
      if (value === '' || value === null || value === undefined) return { code: 'required' };
      const n = typeof value === 'number' ? value : Number(value);
      if (Number.isNaN(n)) return { code: 'number' };
      if (m.type === 'int' && !Number.isInteger(n)) return { code: 'integer' };
      if (m.min !== undefined && n < m.min) return { code: 'min', min: m.min };
      if (m.max !== undefined && n > m.max) return { code: 'max', max: m.max };
      if (item.key === 'audio.min_duration_sec' || item.key === 'audio.max_duration_sec') {
        const min = Number(item.key === 'audio.min_duration_sec' ? n : all['audio.min_duration_sec']);
        const max = Number(item.key === 'audio.max_duration_sec' ? n : all['audio.max_duration_sec']);
        if (!Number.isNaN(min) && !Number.isNaN(max) && min >= max) return { code: 'min_lt_max' };
      }
      return undefined;
    }
    case 'string': {
      if (m.options && !m.options.includes(String(value))) return { code: 'option' };
      return undefined;
    }
    case 'json': {
      if (typeof value !== 'string') return undefined;
      try {
        JSON.parse(value);
        return undefined;
      } catch {
        return { code: 'json' };
      }
    }
  }
}

export function coerceForSave(item: SettingItem, value: unknown): unknown {
  const m = metaFor(item);
  if (m.type === 'int' || m.type === 'float') return Number(value);
  if (m.type === 'json' && typeof value === 'string') return JSON.parse(value);
  return value;
}
