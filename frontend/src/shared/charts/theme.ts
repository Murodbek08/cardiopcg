import { useSyncExternalStore } from 'react';

export interface ChartTheme {
  grid: string;
  axis: string;
  text: string;
  surface: string;
  brand: string;
  series: string[];
  scale: string[]; // sequential brand scale, light -> dark (single hue, for heatmaps)
  dark: boolean;
}

function cssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/** Reads tokens from CSS variables so charts follow light/dark without hard-coded colours. */
export function readChartTheme(): ChartTheme {
  const dark = typeof document !== 'undefined' && document.documentElement.classList.contains('dark');
  return {
    dark,
    grid: cssVar('--chart-grid', '#e4e9ef'),
    axis: cssVar('--chart-axis', '#5b6776'),
    text: cssVar('--text', '#101828'),
    surface: cssVar('--surface', '#ffffff'),
    brand: cssVar('--color-brand-600', '#187f8c'),
    series: [
      cssVar('--color-brand-600', '#187f8c'),
      cssVar('--color-info-500', '#2f6fdb'),
      cssVar('--color-warning-500', '#d98a0b'),
      cssVar('--color-danger-500', '#d6354b'),
      cssVar('--color-success-500', '#1f9d62'),
      '#7c5cbf',
      '#6b7a8c',
    ],
    scale: [
      cssVar('--color-brand-100', '#d3f4f4'),
      cssVar('--color-brand-300', '#78d5da'),
      cssVar('--color-brand-500', '#209ea9'),
      cssVar('--color-brand-700', '#17666f'),
    ],
  };
}

let cached: ChartTheme | null = null;

function subscribe(cb: () => void): () => void {
  const mo = new MutationObserver(() => {
    cached = null;
    cb();
  });
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
  return () => mo.disconnect();
}

function getSnapshot(): ChartTheme {
  if (!cached) cached = readChartTheme();
  return cached;
}

/** Re-renders consumers when the theme class on <html> changes. */
export function useChartTheme(): ChartTheme {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
