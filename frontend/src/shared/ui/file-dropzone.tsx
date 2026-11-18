import { useCallback, useRef, useState, type DragEvent, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { IconUpload } from '@tabler/icons-react';
import { cn } from '@/shared/lib/cn';
import { formatBytes } from '@/shared/lib/format';

export interface FileDropzoneProps {
  accept: string[]; // extensions with dot, e.g. ['.wav', '.mp3']
  maxSizeBytes: number;
  multiple?: boolean;
  disabled?: boolean;
  onFiles: (files: File[]) => void;
  onReject?: (rejections: { file: File; reason: 'size' | 'type' }[]) => void;
  className?: string;
  hint?: string;
}

/** Validates extension and size locally; the server remains authoritative (magic bytes, MIME). */
export function validateFile(file: File, accept: string[], maxSizeBytes: number): 'size' | 'type' | null {
  const ext = `.${file.name.split('.').pop()?.toLowerCase() ?? ''}`;
  if (!accept.map((a) => a.toLowerCase()).includes(ext)) return 'type';
  if (file.size > maxSizeBytes) return 'size';
  return null;
}

export function FileDropzone({ accept, maxSizeBytes, multiple, disabled, onFiles, onReject, className, hint }: FileDropzoneProps) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const handle = useCallback(
    (list: FileList | null) => {
      if (!list?.length) return;
      const ok: File[] = [];
      const bad: { file: File; reason: 'size' | 'type' }[] = [];
      for (const f of Array.from(list)) {
        const r = validateFile(f, accept, maxSizeBytes);
        if (r) bad.push({ file: f, reason: r });
        else ok.push(f);
      }
      if (bad.length) onReject?.(bad);
      if (ok.length) onFiles(multiple ? ok : ok.slice(0, 1));
    },
    [accept, maxSizeBytes, multiple, onFiles, onReject],
  );

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (!disabled) handle(e.dataTransfer.files);
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      input.current?.click();
    }
  };

  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled}
      onClick={() => !disabled && input.current?.click()}
      onKeyDown={onKey}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={cn(
        'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border bg-surface px-6 py-8 text-center transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-ring',
        over && 'border-brand-500 bg-brand-50 dark:bg-brand-900/30',
        disabled && 'cursor-not-allowed opacity-60',
        className,
      )}
    >
      <IconUpload size={28} className="text-brand-600" aria-hidden />
      <p className="font-medium">{t('dropzone.title')}</p>
      <p className="text-xs text-muted">
        {t('dropzone.accepted', { types: accept.join(' ') })} &middot; {t('dropzone.max_size', { size: formatBytes(maxSizeBytes) })}
      </p>
      {hint && <p className="text-xs text-muted">{hint}</p>}
      <input
        ref={input}
        type="file"
        className="sr-only"
        tabIndex={-1}
        accept={accept.join(',')}
        multiple={multiple}
        disabled={disabled}
        onChange={(e) => {
          handle(e.target.files);
          e.target.value = '';
        }}
      />
    </div>
  );
}
