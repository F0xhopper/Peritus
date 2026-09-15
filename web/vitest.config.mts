import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'

/**
 * Vitest 5 no longer searches parent directories for its config, so this file
 * has to live in `web/` — which is also where the tests are.
 *
 * The suite is deliberately node-environment only. Everything tested here is
 * pure: the SSE frame parser, the build-event reducer, the cookie shaping, the
 * avatar recipe resolver, the readiness gate. Component rendering is covered by
 * Playwright against a real browser, because a jsdom approximation of a
 * scroll container, a `ResizeObserver` and a canvas would be testing the mock.
 */
export default defineConfig({
  test: {
    environment: 'node',
    include: ['tests/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      include: ['lib/**/*.ts'],
      exclude: ['lib/graph/simulation.worker.ts'],
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('.', import.meta.url)),
      // `server-only` is a Next-provided marker module that only resolves
      // inside its bundler; it has no runtime behaviour. Stubbing it lets the
      // server-side modules it guards be unit-tested directly, which is the
      // point — `lib/api/proxy.ts` is the most consequential file here.
      'server-only': fileURLToPath(new URL('./tests/stubs/server-only.ts', import.meta.url)),
    },
  },
})
