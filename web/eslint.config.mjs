import { defineConfig, globalIgnores } from 'eslint/config'
import nextVitals from 'eslint-config-next/core-web-vitals'
import nextTs from 'eslint-config-next/typescript'

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
  globalIgnores([
    '.next/**',
    'out/**',
    'build/**',
    'next-env.d.ts',
    'coverage/**',
    'playwright-report/**',
    'test-results/**',
  ]),
])

export default eslintConfig
