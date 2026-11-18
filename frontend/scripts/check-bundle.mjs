// Production bundle must not contain the MSW mock layer or dev-only fixtures.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const FORBIDDEN = ['mockServiceWorker', 'msw/browser', 'setupWorker', '__MOCK_LAYER__'];
let bad = 0;
function walk(p) {
  const st = statSync(p);
  if (st.isDirectory()) return readdirSync(p).forEach((f) => walk(join(p, f)));
  if (!/\.(js|html|css|map)$/.test(p) && !p.endsWith('mockServiceWorker.js')) return;
  const text = readFileSync(p, 'utf8');
  for (const w of FORBIDDEN) if (text.includes(w)) { bad++; console.error(`${p}: contains "${w}"`); }
}
walk('dist');
if (bad) process.exit(1);
console.log('check:bundle OK (no MSW in production bundle)');
