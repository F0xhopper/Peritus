import { defineConfig, globalIgnores } from 'eslint/config'
import nextVitals from 'eslint-config-next/core-web-vitals'
import nextTs from 'eslint-config-next/typescript'
import prettier from 'eslint-config-prettier/flat'

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // `eslint-plugin-react` (vendored inside eslint-config-next) sniffs the
    // installed React version by calling `context.getFilename()`, which ESLint
    // 10 removed — so every rule that consults the version throws while
    // loading. Pinning the version here means detection never runs.
    settings: { react: { version: '19.3' } },
  },
  {
    rules: {
      // Unused values are an error, but a deliberately ignored argument or a
      // caught-and-discarded error is not: `_`-prefixed names and bare
      // `catch {}` are how those are spelled in this codebase.
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrors: 'none',
        },
      ],
    },
  },
  // Last, so it wins: turns off every stylistic rule Prettier already decides.
  prettier,
  globalIgnores([
    '.next/**',
    'out/**',
    'build/**',
    // `vercel build` output (the deploy pipeline builds prebuilt, and so can a
    // local `vercel build`): compiled bundles, not source.
    '.vercel/**',
    'next-env.d.ts',
    'coverage/**',
    'playwright-report/**',
    'test-results/**',
  ]),
])

export default eslintConfig
