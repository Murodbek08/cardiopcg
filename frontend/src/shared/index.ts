/**
 * Public surface of the shared kit. The doctor/nurse agents import from here (or the sub-barrels):
 *   import { Button, DataTable, KpiCard } from '@/shared/ui';
 *   import { AudioWaveform, SpectrogramView, RiskGauge } from '@/shared/clinical';
 *   import { ChartCard, TimeSeriesChart, DonutChart } from '@/shared/charts';
 */
export * from './ui';
export * from './clinical';
export * from './charts';
export * from './hooks';
export { api, get, post, put, patch, del, downloadFile, cleanParams } from './api/client';
export { connectSse, type RealtimeEvent } from './api/sse';
export { realtime } from './api/realtime';
export { uploadFile } from './api/upload';
export { ApiError, isApiError, normalizeError, fieldErrorMap } from './api/errors';
export { qk } from './api/query';
export { can, type Permission } from './lib/permissions';
export { cn } from './lib/cn';
export * from './lib/format';
export { normalizePage } from './lib/normalize';
export type * from './api/types';
export { useAuthStore } from './store/auth';
