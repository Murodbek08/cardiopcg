/** Admin sees patient identity partially masked ("A*** K***"). */
export function maskName(full: string | null | undefined): string {
  if (!full) return '-';
  return full
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => `${p[0]?.toUpperCase() ?? ''}***`)
    .join(' ');
}
export function maskPhone(p: string | null | undefined): string {
  if (!p) return '-';
  return p.length <= 6 ? '***' : `${p.slice(0, 4)}*****${p.slice(-2)}`;
}
