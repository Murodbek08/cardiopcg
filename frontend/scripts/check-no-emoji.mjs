// Static check: no emoji in src/, index.html, locales (CI: "no_emoji.lint").
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, extname } from 'node:path';

const EMOJI = /(?![\xA9\xAE\u{2122}])[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}\u{FE0F}\u{20E3}]/u;
const EXT = new Set(['.ts', '.tsx', '.css', '.json', '.html', '.svg', '.md']);
const roots = ['src', 'index.html', 'public'];
let bad = 0;

function walk(p) {
  const st = statSync(p);
  if (st.isDirectory()) return readdirSync(p).forEach((f) => walk(join(p, f)));
  if (!EXT.has(extname(p))) return;
  readFileSync(p, 'utf8')
    .split(/\r?\n/)
    .forEach((line, i) => {
      const m = EMOJI.exec(line);
      if (m) {
        bad++;
        console.error(`${p}:${i + 1} emoji "${m[0]}"`);
      }
    });
}
roots.forEach((r) => {
  try {
    walk(r);
  } catch {
    /* missing root */
  }
});
if (bad) {
  console.error(`\n${bad} emoji occurrence(s) found. Use Tabler icons.`);
  process.exit(1);
}
console.log('check:emoji OK');
