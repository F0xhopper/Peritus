import { expect, test } from '@playwright/test'

import { resetApi, signIn } from './helpers'

/**
 * The content security policy, measured rather than assumed.
 *
 * It ships **report-only**, and the whole point of that mode is to find out
 * what it would break before it breaks it. That only works if someone looks —
 * and "someone looks at the console for a week" is not a thing that reliably
 * happens, so this looks on every run instead.
 *
 * A violation here is not a test being fussy. It is the exact page that would
 * have gone blank, with no error a user could report, on the day the header is
 * promoted to `Content-Security-Policy`.
 */

const SLUG = 'varroa-mite-control-in-temperate-beekeeping'

/** Every route a signed-out visitor can reach, and the signed-in shell. */
const PUBLIC_PAGES = ['/', '/login', '/privacy', '/terms']
/**
 * Open a page and give hydration a beat to finish.
 *
 * `domcontentloaded`, never `load` or `networkidle`: the app shell opens an SSE
 * connection for build events and keeps it open, so both of those wait for
 * something that is never going to happen. The beat afterwards is the part that
 * matters — the inline style and React's streaming runtime are the two things
 * most likely to trip a policy, and both land during hydration.
 */
async function visit(page: import('@playwright/test').Page, path: string): Promise<void> {
  try {
    await page.goto(path, { waitUntil: 'domcontentloaded' })
  } catch (error) {
    // Next's router can start a client navigation of its own — a prefetch
    // resolving, a `router.refresh` committing — while this one is in flight,
    // and Playwright reports that as an interrupted `goto`. It is not a CSP
    // problem and it is not a bug; going again from a settled page is enough.
    if (!String(error).includes('interrupted by another navigation')) throw error
    await page.waitForTimeout(200)
    await page.goto(path, { waitUntil: 'domcontentloaded' })
  }
  await page.waitForTimeout(600)
}

const APP_PAGES = [
  '/experts',
  `/experts/${SLUG}`,
  `/experts/${SLUG}/sources`,
  `/experts/${SLUG}/graph`,
  `/experts/${SLUG}/settings`,
  '/settings',
]

/**
 * Collect CSP report-only violations while `visit` runs.
 *
 * Chromium reports them through `securitypolicyviolation`, which fires on the
 * document. Installed before navigation so nothing during first paint is
 * missed — which is when the inline style and the streaming runtime land.
 */
async function violationsDuring(
  page: import('@playwright/test').Page,
  visit: () => Promise<void>
): Promise<string[]> {
  await page.addInitScript(() => {
    const store = window as unknown as { __csp: string[] }
    store.__csp = []
    document.addEventListener('securitypolicyviolation', (event) => {
      store.__csp.push(`${event.violatedDirective} blocked ${event.blockedURI || '(inline)'}`)
    })
  })
  await visit()
  return page.evaluate(() => (window as unknown as { __csp: string[] }).__csp ?? [])
}

test('the policy is sent, and is report-only until it has been proven quiet', async ({ page }) => {
  const response = await page.goto('/')
  const headers = response!.headers()

  expect(headers['content-security-policy-report-only']).toContain("default-src 'self'")
  // `frame-ancestors` is the modern `X-Frame-Options: DENY`, and both are sent:
  // the old header for browsers that do not implement the new one.
  expect(headers['content-security-policy-report-only']).toContain("frame-ancestors 'none'")
  expect(headers['x-frame-options']).toBe('DENY')
  // Enforcing it is a deliberate later step. If this ever fails because the
  // enforcing header appeared, that is the promotion — delete this assertion.
  expect(headers['content-security-policy']).toBeUndefined()
})

for (const path of PUBLIC_PAGES) {
  test(`${path} violates nothing`, async ({ page }) => {
    const violations = await violationsDuring(page, async () => {
      await visit(page, path)
    })
    expect(violations).toEqual([])
  })
}

test('the signed-in shell violates nothing, on any of its pages', async ({ page }) => {
  await resetApi(page)
  const violations = await violationsDuring(page, async () => {
    await signIn(page)
    for (const path of APP_PAGES) {
      await visit(page, path)
    }
  })
  expect(violations).toEqual([])
})
