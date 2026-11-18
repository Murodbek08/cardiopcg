import { z } from 'zod';
import i18n from '@/i18n';

/** Registers Uzbek error messages for zod (validation namespace). Call once at startup. */
export function setupZodUz(): void {
  z.config({
    customError: (iss) => {
      const t = (k: string, o?: Record<string, unknown>) => i18n.t(`validation:${k}`, o ?? {}) as string;
      switch (iss.code) {
        case 'invalid_type':
          if (iss.input === undefined || iss.input === null) return t('required');
          return iss.expected === 'number' || iss.expected === 'int' ? t('number') : t('invalid');
        case 'too_small':
          if (iss.origin === 'string') {
            return Number(iss.minimum) <= 1 ? t('required') : t('min_length', { count: Number(iss.minimum) });
          }
          if (iss.origin === 'array') return Number(iss.minimum) <= 1 ? t('required') : t('min_length', { count: Number(iss.minimum) });
          return t('min_value', { min: String(iss.minimum) });
        case 'too_big':
          if (iss.origin === 'string' || iss.origin === 'array') return t('max_length', { count: Number(iss.maximum) });
          return t('max_value', { max: String(iss.maximum) });
        case 'invalid_format':
          if (iss.format === 'email') return t('email');
          if (iss.format === 'url') return t('url');
          return t('invalid');
        default:
          return undefined;
      }
    },
  });
}

export const usernameRegex = /^[a-z0-9._-]{3,32}$/;
export const phoneRegex = /^\+998\d{9}$/;
export const atcRegex = /^[A-Z]\d{2}[A-Z]{2}\d{2}$/;

/** Optional free-text URL param: TanStack Router parses "123" as a number, so coerce back to string. */
export const optStr = z.preprocess((v) => (v === undefined || v === null || v === '' ? undefined : String(v)), z.string().optional());
