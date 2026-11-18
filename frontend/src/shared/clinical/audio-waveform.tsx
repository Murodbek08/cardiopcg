import { useCallback, useEffect, useImperativeHandle, useRef, useState, type Ref } from 'react';
import { useTranslation } from 'react-i18next';
import { IconPlayerPause, IconPlayerPlay, IconZoomIn, IconZoomOut, IconPlayerSkipBack, IconPlayerSkipForward } from '@tabler/icons-react';
import type WaveSurfer from 'wavesurfer.js';
import type RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.js';
import type { PcgSegment } from '@/shared/api/types';
import { Button } from '@/shared/ui/button';
import { Select } from '@/shared/ui/select';
import { Skeleton, ErrorState } from '@/shared/ui/feedback';
import { useAuthedBlobUrl } from '@/shared/hooks';
import { formatDuration } from '@/shared/lib/format';
import { cn } from '@/shared/lib/cn';

export interface WaveformHandle {
  seek: (seconds: number) => void;
  toggle: () => void;
}

export interface AudioWaveformProps {
  /** API path of the audio stream (fetched with auth), or a ready blob/object URL via `objectUrl`. */
  src?: string | null;
  objectUrl?: string | null;
  /** Server-computed peaks (avoids decoding large files in the browser). */
  peaks?: number[] | null;
  segments?: Pick<PcgSegment, 'type' | 'start_ms' | 'end_ms' | 'cycle_no'>[];
  /** Doctors may drag/resize regions; nurses and admins get `false` (read-only). */
  editable?: boolean;
  height?: number;
  onTime?: (seconds: number, duration: number) => void;
  onReady?: (duration: number) => void;
  handleRef?: Ref<WaveformHandle>;
  className?: string;
}

const REGION_COLORS: Record<string, string> = {
  S1: 'rgba(214, 53, 75, 0.28)',
  S2: 'rgba(47, 111, 219, 0.28)',
  murmur: 'rgba(217, 138, 11, 0.32)',
  systole: 'rgba(0,0,0,0)',
  diastole: 'rgba(0,0,0,0)',
};
const SPEEDS = ['0.25', '0.5', '1', '1.5', '2'];

/**
 * wavesurfer.js v7+ player with S1/S2/murmur regions. The library is loaded on demand (never in the
 * initial bundle). Region labels are text (not colour-only). Space = play/pause, arrows = +/-1 s.
 */
export function AudioWaveform({ src, objectUrl, peaks, segments = [], editable = false, height = 128, onTime, onReady, handleRef, className }: AudioWaveformProps) {
  const { t } = useTranslation('clinical');
  const host = useRef<HTMLDivElement>(null);
  const ws = useRef<WaveSurfer | null>(null);
  const regionsRef = useRef<InstanceType<typeof RegionsPlugin> | null>(null);
  const fetched = useAuthedBlobUrl(objectUrl ? null : src);
  const url = objectUrl ?? fetched.url;

  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState<unknown>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [zoom, setZoom] = useState(0);
  const [rate, setRate] = useState('1');
  const cb = useRef({ onTime, onReady });
  useEffect(() => {
    cb.current = { onTime, onReady };
  });

  useImperativeHandle(handleRef, () => ({
    seek: (s) => ws.current?.setTime(s),
    toggle: () => void ws.current?.playPause(),
  }));

  useEffect(() => {
    if (!url || !host.current) return;
    let disposed = false;
    setReady(false);
    setFailed(null);
    void (async () => {
      try {
        const [{ default: WaveSurfer }, { default: Regions }, { default: Timeline }] = await Promise.all([
          import('wavesurfer.js'),
          import('wavesurfer.js/dist/plugins/regions.js'),
          import('wavesurfer.js/dist/plugins/timeline.js'),
        ]);
        if (disposed || !host.current) return;
        const css = getComputedStyle(document.documentElement);
        const regions = Regions.create();
        regionsRef.current = regions;
        const inst = WaveSurfer.create({
          container: host.current,
          url,
          peaks: peaks ? [Float32Array.from(peaks)] : undefined,
          height,
          waveColor: css.getPropertyValue('--text-muted').trim() || '#93a1b3',
          progressColor: css.getPropertyValue('--color-pcg-wave').trim() || '#187f8c',
          cursorColor: css.getPropertyValue('--text').trim() || '#101828',
          barWidth: 2,
          barGap: 1,
          barRadius: 2,
          normalize: true,
          minPxPerSec: 0,
          plugins: [regions, Timeline.create({ height: 18 })],
        });
        ws.current = inst;
        inst.on('ready', (d) => {
          setDuration(d);
          setReady(true);
          cb.current.onReady?.(d);
        });
        inst.on('timeupdate', (tm) => {
          setTime(tm);
          cb.current.onTime?.(tm, inst.getDuration());
        });
        inst.on('play', () => setPlaying(true));
        inst.on('pause', () => setPlaying(false));
        inst.on('finish', () => setPlaying(false));
        inst.on('error', (e) => setFailed(e));
      } catch (e) {
        setFailed(e);
      }
    })();
    return () => {
      disposed = true;
      ws.current?.destroy();
      ws.current = null;
      regionsRef.current = null;
    };
  }, [url, peaks, height]);

  // (re)draw regions whenever segments or edit mode change
  useEffect(() => {
    const regions = regionsRef.current;
    if (!regions || !ready) return;
    regions.clearRegions();
    for (const s of segments) {
      if (s.type === 'systole' || s.type === 'diastole') continue;
      const label = document.createElement('span');
      label.textContent = s.type;
      label.style.cssText = 'font-size:10px;font-weight:600;padding:0 2px;color:var(--text)';
      regions.addRegion({
        start: s.start_ms / 1000,
        end: s.end_ms / 1000,
        color: REGION_COLORS[s.type] ?? 'rgba(120,120,120,0.2)',
        drag: editable,
        resize: editable,
        content: label,
      });
    }
  }, [segments, editable, ready]);

  useEffect(() => {
    ws.current?.setPlaybackRate(Number(rate), true);
  }, [rate]);

  const applyZoom = useCallback((z: number) => {
    setZoom(z);
    if (ws.current && ready) ws.current.zoom(z);
  }, [ready]);

  const onKey = (e: React.KeyboardEvent) => {
    if (!ws.current) return;
    if (e.key === ' ') {
      e.preventDefault();
      void ws.current.playPause();
    } else if (e.key === 'ArrowRight') ws.current.skip(1);
    else if (e.key === 'ArrowLeft') ws.current.skip(-1);
    else if (e.key === '+' || e.key === '=') applyZoom(Math.min(zoom + 20, 400));
    else if (e.key === '-') applyZoom(Math.max(zoom - 20, 0));
  };

  if (failed || fetched.error) return <ErrorState compact error={fetched.error ?? failed} />;

  return (
    <div className={cn('space-y-2', className)}>
      <div
        tabIndex={0}
        role="group"
        aria-label={t('waveform.label')}
        onKeyDown={onKey}
        className="relative rounded-md border border-border bg-surface p-2 focus-visible:outline-2 focus-visible:outline-ring"
      >
        {(!ready || fetched.loading) && <Skeleton className="absolute inset-2 z-10" />}
        <div ref={host} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="icon" variant="outline" aria-label={t('waveform.back')} onClick={() => ws.current?.skip(-1)} disabled={!ready}>
          <IconPlayerSkipBack size={18} aria-hidden />
        </Button>
        <Button size="icon" aria-pressed={playing} aria-label={playing ? t('waveform.pause') : t('waveform.play')} onClick={() => void ws.current?.playPause()} disabled={!ready}>
          {playing ? <IconPlayerPause size={18} aria-hidden /> : <IconPlayerPlay size={18} aria-hidden />}
        </Button>
        <Button size="icon" variant="outline" aria-label={t('waveform.forward')} onClick={() => ws.current?.skip(1)} disabled={!ready}>
          <IconPlayerSkipForward size={18} aria-hidden />
        </Button>
        <span className="font-mono-num text-sm text-muted">
          {formatDuration(time)} / {formatDuration(duration)}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Select aria-label={t('waveform.speed')} className="h-9 w-24" value={rate} onValueChange={setRate} options={SPEEDS.map((s) => ({ value: s, label: `${s}x` }))} />
          <Button size="icon-sm" variant="ghost" aria-label={t('waveform.zoom_out')} onClick={() => applyZoom(Math.max(zoom - 20, 0))} disabled={!ready}>
            <IconZoomOut size={16} aria-hidden />
          </Button>
          <input type="range" min={0} max={400} value={zoom} onChange={(e) => applyZoom(Number(e.target.value))} aria-label={t('waveform.zoom')} className="w-24 accent-[var(--color-brand-600)]" disabled={!ready} />
          <Button size="icon-sm" variant="ghost" aria-label={t('waveform.zoom_in')} onClick={() => applyZoom(Math.min(zoom + 20, 400))} disabled={!ready}>
            <IconZoomIn size={16} aria-hidden />
          </Button>
        </div>
      </div>
      <ul className="flex flex-wrap gap-3 text-xs text-muted" aria-label={t('waveform.legend')}>
        <li className="flex items-center gap-1"><span aria-hidden className="h-2.5 w-2.5 rounded-sm bg-pcg-s1" /> S1</li>
        <li className="flex items-center gap-1"><span aria-hidden className="h-2.5 w-2.5 rounded-sm bg-pcg-s2" /> S2</li>
        <li className="flex items-center gap-1"><span aria-hidden className="h-2.5 w-2.5 rounded-sm bg-pcg-murmur" /> {t('waveform.murmur')}</li>
        {!editable && <li>{t('waveform.read_only')}</li>}
      </ul>
    </div>
  );
}
