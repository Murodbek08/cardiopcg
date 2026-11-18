import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

// Emoji / pictograph ban (project rule: Tabler Icons only, never emoji).
const EMOJI = /(?![\xA9\xAE\u{2122}])[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}\u{FE0F}\u{20E3}]/u;

const noEmoji = {
  meta: {
    type: 'problem',
    messages: { emoji: 'Emoji/pictograph "{{ch}}" is forbidden. Use a Tabler icon (@tabler/icons-react).' },
    schema: [],
  },
  create(context) {
    const check = (node, text) => {
      const m = EMOJI.exec(text);
      if (m) context.report({ node, messageId: 'emoji', data: { ch: m[0] } });
    };
    return {
      Literal(node) {
        if (typeof node.value === 'string') check(node, node.value);
      },
      TemplateElement(node) {
        check(node, node.value.raw);
      },
      JSXText(node) {
        check(node, node.value);
      },
    };
  },
};

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'coverage', 'src/shared/api/schema.gen.ts', 'public'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: { ecmaVersion: 2023, globals: { ...globals.browser, ...globals.node } },
    plugins: { 'react-hooks': reactHooks, cardiopcg: { rules: { 'no-emoji': noEmoji } } },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/incompatible-library': 'off',
      'cardiopcg/no-emoji': 'error',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      '@typescript-eslint/consistent-type-imports': ['error', { prefer: 'type-imports' }],
      'no-restricted-syntax': [
        'error',
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: 'dangerouslySetInnerHTML is forbidden (XSS).' },
      ],
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'no-restricted-globals': ['error', { name: 'localStorage', message: 'Use the safe storage helpers; never store tokens.' }],
    },
  },
  {
    // Feature modules must not reach into each other (use shared/ or a public index).
    files: ['src/features/**/*.{ts,tsx}'],
    ignores: ['**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/features/*/*', '@/app/*'],
              message: 'Features may only depend on @/shared (or another feature public index).',
            },
          ],
        },
      ],
    },
  },
  {
    files: ['src/shared/lib/safe-storage.ts', 'src/**/*.test.{ts,tsx}', 'src/test/**'],
    rules: { 'no-restricted-globals': 'off' },
  },
  { files: ['src/shared/ui/**', 'src/shared/charts/**'], rules: { 'react-hooks/exhaustive-deps': 'warn' } },
);
