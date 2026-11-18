// Initial-load JS budget check: entry + modulepreload chunks from dist/index.html, gzip size (doc 03 target: 180 KB).
import { readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';

const BUDGET_KB = Number(process.env.JS_BUDGET_KB ?? 180);
const html = readFileSync('dist/index.html', 'utf8');
const files = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+\.js)"/g)].map((m) => m[1]);
let total = 0;
for (const f of [...new Set(files)]) {
  const gz = gzipSync(readFileSync(`dist${f}`)).length;
  total += gz;
  console.log(`${(gz / 1024).toFixed(1).padStart(7)} KB  ${f}`);
}
const kb = total / 1024;
console.log(`initial JS gzip: ${kb.toFixed(1)} KB (budget ${BUDGET_KB} KB)`);
if (kb > BUDGET_KB && process.env.ENFORCE_BUDGET === '1') process.exit(1);
