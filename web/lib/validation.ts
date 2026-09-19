import { config, literal, null as nullType, object, string, union, type infer as Infer } from 'zod'

/**
 * Zod, with its JIT compiler off — and only the parts of it this app uses.
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
 *
 * **`z` is assembled from named imports, not re-exported whole.** Zod's own
 * `z` is a namespace object with `locales` on it, and a namespace that escapes
 * as a value cannot be tree-shaken: the login page shipped all sixty-four of
 * Zod's translations — a 389 KB chunk, a third of the page's JavaScript — to
 * check an email and a non-empty password with messages this app writes itself.
 * That is what held `/login` at a total blocking time of 204–220ms against a
 * 200ms budget, passing or failing a deploy by which runner it drew. A schema
 * that needs something not listed here adds it here.
 */
config({ jitless: true })

export const z = { literal, null: nullType, object, string, union }

// Types only, so it shares the name without being a second value: `z.infer<…>`
// keeps reading the way Zod's documentation writes it.
// eslint-disable-next-line @typescript-eslint/no-namespace
export declare namespace z {
  export type infer<T> = Infer<T>
}
