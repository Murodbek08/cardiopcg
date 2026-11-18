const TZ = 'Asia/Tashkent';
const LOCALE = 'uz-UZ';

const dtf = new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
const df = new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, day: '2-digit', month: 'short', year: 'numeric' });
const tf = new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, hour: '2-digit', minute: '2-digit', hour12: false });
const nf = new Intl.NumberFormat('uz-UZ');
const nf1 = new Intl.NumberFormat('uz-UZ', { maximumFractionDigits: 1 });

export const EMPTY = '-';

type DateInput = string | number | Date | null | undefined;

function toDate(v: DateInput): Date | null {
  if (v === null || v === undefined || v === '') return null;
  const d = v instanceof Date ? v : new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}
export function formatDateTime(v: DateInput): string {
  const d = toDate(v);
  return d ? dtf.format(d) : EMPTY;
}
export function formatDate(v: DateInput): string {
  const d = toDate(v);
  return d ? df.format(d) : EMPTY;
}
export function formatTime(v: DateInput): string {
  const d = toDate(v);
  return d ? tf.format(d) : EMPTY;
}
export function formatNumber(v: number | null | undefined, fractionDigits?: number): string {
  if (v === null || v === undefined || Number.isNaN(v)) return EMPTY;
  if (fractionDigits === undefined) return nf.format(v);
  return new Intl.NumberFormat('uz-UZ', { maximumFractionDigits: fractionDigits, minimumFractionDigits: fractionDigits }).format(v);
}
export function formatDecimal(v: number | null | undefined): string {
  return v === null || v === undefined ? EMPTY : nf1.format(v);
}
export function formatPercent(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return EMPTY;
  return `${formatNumber(v, digits)}%`;
}
export function formatBytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return EMPTY;
  if (n < 1024) return `${n} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 ? 0 : 1)} ${units[i]}`;
}
export function formatDuration(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return EMPTY;
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}
/** ISO date (YYYY-MM-DD) in Tashkent for a given instant. */
export function toIsoDate(d: Date): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(d);
}
export function daysAgo(n: number): string {
  return toIsoDate(new Date(Date.now() - n * 86_400_000));
}
export function today(): string {
  return toIsoDate(new Date());
}
