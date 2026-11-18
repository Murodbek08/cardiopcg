import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuthedBlobUrl } from '@/shared/hooks';
import { Skeleton, ErrorState } from '@/shared/ui/feedback';
import { cn } from '@/shared/lib/cn';

export interface SpectrogramViewProps {
  /** API path, e.g. `/recordings/{id}/spectrogram` (server-rendered PNG, viridis colormap). */
  src: string | null | undefined;
  /** 0..1 playback position, drawn as a cursor line synchronised with the waveform. */
  progress?: number;
  maxHz?: number;
  className?: string;
  alt?: string;
}

export function SpectrogramView({ src, progress, maxHz = 1000, className, alt }: SpectrogramViewProps) {
  const { t } = useTranslation('clinical');
  const { url, loading, error } = useAuthedBlobUrl(src);
  const [contrast, setContrast] = useState(1);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(maxHz * f));

  if (error) return <ErrorState compact error={error} />;
  return (
    <div className={cn('space-y-2', className)}>
      <div className="flex gap-2">
        <div className="flex w-10 shrink-0 flex-col-reverse justify-between py-0.5 text-right text-[10px] text-muted tabular-nums" aria-hidden>
          {ticks.map((tk) => (
            <span key={tk}>{tk}</span>
          ))}
        </div>
        <div className="relative min-h-32 flex-1 overflow-hidden rounded-md border border-border bg-black">
          {loading || !url ? (
            <Skeleton className="h-40 w-full" />
          ) : (
            <img src={url} alt={alt ?? t('spectrogram.alt')} className="block h-full w-full select-none object-fill" style={{ filter: `contrast(${contrast})` }} draggable={false} />
          )}
          {progress !== undefined && url && (
            <div aria-hidden className="pointer-events-none absolute inset-y-0 w-px bg-white" style={{ left: `${Math.max(0, Math.min(1, progress)) * 100}%` }} />
          )}
        </div>
      </div>
      <div className="flex items-center justify-between gap-3 text-xs text-muted">
        <span>{t('spectrogram.axis', { max: maxHz })}</span>
        <label className="flex items-center gap-2">
          {t('spectrogram.contrast')}
          <input type="range" min={0.6} max={1.8} step={0.1} value={contrast} onChange={(e) => setContrast(Number(e.target.value))} className="w-28 accent-[var(--color-brand-600)]" />
        </label>
      </div>
    </div>
  );
}
