import { z } from 'zod'

/**
 * Zod, with its JIT compiler off.
 *
 * Zod 4 compiles faster validators with `new Function`, and **feature-detects
 * that by calling `Function("")`** — which a content security policy without
 * `'unsafe-eval'` reports, on the login page, before any form is submitted.
 * The report-only CSP caught it; `e2e/csp.spec.ts` is what keeps it caught.
 *
 * `jitless` is the supported way off, and the trade is nothing here: these are
 * two small schemas validated on a form submit, so the interpreted path costs
 * microseconds a person cannot perceive — against `'unsafe-eval'`, which would
 * hand every injected string on the page a way to execute.
 *
 * Import `z` from here rather than from `zod`, so the setting cannot be
 * bypassed by a module that forgets.
 */
z.config({ jitless: true })

export { z }
