export const API_BASE = '/api/v1';
export const AGE_GROUPS = ['0-17', '18-39', '40-59', '60-74', '75+'] as const;
export const PAGE_SIZES = [10, 20, 50, 100] as const;
export const ROLE_HOME = { admin: '/admin', doctor: '/doctor', nurse: '/nurse' } as const;
/** Below this sample size we show "not enough data" instead of a percentage (doc 03, section 4). */
export const MIN_SAMPLE = 10;
