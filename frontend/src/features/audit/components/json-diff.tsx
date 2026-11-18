import { cn } from '@/shared';

type Json = unknown;

/** Flattens an object into dotted paths (arrays are kept as JSON strings). */
export function flatten(v: Json, prefix = '', out: Record<string, string> = {}): Record<string, string> {
  if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
    for (const [k, val] of Object.entries(v as Record<string, Json>)) flatten(val, prefix ? `${prefix}.${k}` : k, out);
  } else if (prefix) {
    out[prefix] = JSON.stringify(v);
  }
  return out;
}

export interface DiffRow {
  path: string;
  before?: string;
  after?: string;
  kind: 'added' | 'removed' | 'changed' | 'same';
}

export function diffJson(before: Json, after: Json): DiffRow[] {
  const b = flatten(before);
  const a = flatten(after);
  const paths = [...new Set([...Object.keys(b), ...Object.keys(a)])].sort();
  return paths.map((path) => {
    const bv = b[path];
    const av = a[path];
    const kind: DiffRow['kind'] = bv === undefined ? 'added' : av === undefined ? 'removed' : bv === av ? 'same' : 'changed';
    return { path, before: bv, after: av, kind };
  });
}

const kindCls = {
  added: 'bg-success-50',
  removed: 'bg-danger-50',
  changed: 'bg-warning-50',
  same: '',
};
const kindLabel = { added: '+', removed: '-', changed: '~', same: '' };

/** Read-only diff table. Change type is shown with a symbol, not only a background colour. */
export function JsonDiffViewer({ before, after }: { before?: Json; after?: Json }) {
  const rows = diffJson(before ?? {}, after ?? {});
  if (!rows.length) return null;
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border bg-surface-2 text-left">
            <th className="w-6 px-2 py-1.5" aria-label="change" />
            <th className="px-2 py-1.5">Maydon</th>
            <th className="px-2 py-1.5">Oldin</th>
            <th className="px-2 py-1.5">Keyin</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.path} className={cn('border-b border-border last:border-0', kindCls[r.kind])}>
              <td className="px-2 py-1 font-mono font-bold" aria-label={r.kind}>{kindLabel[r.kind]}</td>
              <td className="px-2 py-1 font-mono">{r.path}</td>
              <td className="break-all px-2 py-1 font-mono">{r.before ?? '-'}</td>
              <td className="break-all px-2 py-1 font-mono">{r.after ?? '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
