// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { ESLint } from 'eslint';

/** Proves the "no emoji" ESLint rule actually fires (build check "no_emoji.lint"). */
async function lint(code: string, filePath = 'src/example.tsx') {
  const eslint = new ESLint({ overrideConfigFile: 'eslint.config.js' });
  const [res] = await eslint.lintText(code, { filePath });
  return res!.messages.filter((m) => m.ruleId === 'cardiopcg/no-emoji');
}

const cp = (...c: number[]) => String.fromCodePoint(...c);

describe('cardiopcg/no-emoji', () => {
  it('flags emoji in string literals, template strings and JSX text', async () => {
    expect(await lint(`export const a = "ok ${cp(0x1f600)}";`)).toHaveLength(1);
    expect(await lint(`export const b = \`heart ${cp(0x2764, 0xfe0f)}\`;`)).toHaveLength(1);
    expect(await lint(`export const C = () => <p>done ${cp(0x2705)}</p>;`)).toHaveLength(1);
  });
  it('allows normal Uzbek text and typographic characters', async () => {
    const text = ['O', cp(0x2018), 'zbekcha ', cp(0x2014), ' matn, ', cp(0xb7), ' nuqta, ', cp(0x2192), ' va ', cp(0xa9)].join('');
    expect(await lint(`export const a = "${text}";`)).toHaveLength(0);
  });
}, 60_000);
