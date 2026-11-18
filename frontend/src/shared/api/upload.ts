import { api } from './client';
import { normalizeError } from './errors';

export interface UploadOptions {
  url: string;
  file: File;
  fields?: Record<string, string>;
  onProgress?: (pct: number) => void;
  signal?: AbortSignal;
}

/**
 * Multipart upload with progress and cancellation (doc 01, 3.5: one file per request).
 * Timeout is disabled on purpose: large files over slow links.
 */
export async function uploadFile<T>({ url, file, fields, onProgress, signal }: UploadOptions): Promise<T> {
  const form = new FormData();
  form.append('file', file);
  for (const [k, v] of Object.entries(fields ?? {})) form.append(k, v);
  try {
    const res = await api.post<T>(url, form, {
      timeout: 0,
      signal,
      onUploadProgress: (e) => {
        if (e.total) onProgress?.(Math.round((e.loaded / e.total) * 100));
      },
    });
    return res.data;
  } catch (e) {
    throw normalizeError(e);
  }
}
