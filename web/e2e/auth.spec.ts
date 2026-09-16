import { expect, test } from '@playwright/test'

import { expectResponsive, isTouchProject, resetApi, fillField } from './helpers'

/**
 * Signing in, both ways.
 *
 * The Google flow is the one worth testing end to end rather than unit-testing
 * in pieces: it is three redirects and two short-lived httpOnly cookies, and
 * every step is invisible from inside the app. A verifier that is the wrong
 * length, a `redirect_to` that does not match, or a cookie with
 * `SameSite=Strict` all produce the same symptom — the user lands back on the
 * login page — and only a full round trip distinguishes them.
 */

test.beforeEach(async ({ page }) => {
  await resetApi(page)
  await page.context().clearCookies()
})

test('an app route redirects to sign-in and comes back to where it was aimed', async ({
  page,
}, testInfo) => {
  await page.goto('/experts/varroa-mite-control-in-temperate-beekeeping/sources')

  await expect(page).toHaveURL(/\/login\?next=/)
  // The destination survives the redirect, which is the whole point.
  expect(new URL(page.url()).searchParams.get('next')).toBe(
    '/experts/varroa-mite-control-in-temperate-beekeeping/sources'
  )
  await expect(page.getByRole('heading', { name: 'Sign in to Peritus' })).toBeVisible()
  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('the email code round trip signs in and lands on the requested page', async ({ page }) => {
  await page.goto('/login?next=%2Fchats')

  await fillField(page.getByLabel('Email'), 'tester@example.com')
  await page.getByRole('button', { name: 'Continue' }).click()

  await expect(page).toHaveURL(/\/login\/verify\?/)
  await expect(page.getByRole('heading', { name: 'Enter your code' })).toBeVisible()
  await expect(page.getByText('tester@example.com')).toBeVisible()

  // Six cells, and the sixth digit submits on its own.
  const cells = page.locator('input[autocomplete="one-time-code"], input[inputmode="numeric"]')
  await expect(cells.first()).toBeFocused()
  await fillField(cells.first(), '1')
  await fillField(cells.nth(1), '2')
  await fillField(cells.nth(2), '3')
  await fillField(cells.nth(3), '4')
  await fillField(cells.nth(4), '5')
  await fillField(cells.nth(5), '6')

  await expect(page).toHaveURL(/\/chats$/, { timeout: 15_000 })
  await expect(page.getByRole('heading', { name: 'Chats', exact: true })).toBeVisible()

  // The session is in httpOnly cookies, never in page JavaScript.
  const cookies = await page.context().cookies()
  const access = cookies.find((cookie) => cookie.name === 'peritus_access_token')
  expect(access?.httpOnly).toBe(true)
  expect(access?.sameSite).toBe('Lax')
  const readable = await page.evaluate(() => document.cookie)
  expect(readable).not.toContain('peritus_access_token')
})

test('a wrong code shows an error without moving the resend link', async ({ page }) => {
  await page.goto('/login?next=%2Fexperts')
  await fillField(page.getByLabel('Email'), 'tester@example.com')
  await page.getByRole('button', { name: 'Continue' }).click()
  await expect(page).toHaveURL(/\/login\/verify/)

  const resend = page.getByRole('button', { name: /Resend/ })
  const before = await resend.boundingBox()

  const cells = page.locator('input[inputmode="numeric"]')
  for (let index = 0; index < 6; index += 1) await fillField(cells.nth(index), '9')

  await expect(page.getByText(/wrong or has expired|Invalid or expired/i)).toBeVisible()
  // The reserved slot is the point: a notice must not shift the controls.
  const after = await resend.boundingBox()
  expect(Math.abs((after?.y ?? 0) - (before?.y ?? 0))).toBeLessThan(2)
})

test('a rate-limited request shows the countdown from Retry-After', async ({ page }) => {
  await page.goto('/login')
  await fillField(page.getByLabel('Email'), 'ratelimited@example.com')
  await page.getByRole('button', { name: 'Continue' }).click()

  await expect(page.getByText(/Too many attempts/)).toBeVisible()
  await expect(page.getByText(/Try again in \d+s/)).toBeVisible()
  // It stays on the form: there is nothing to verify.
  await expect(page).toHaveURL(/\/login/)
})

test('an invite-only refusal shows the server’s own message', async ({ page }) => {
  await page.goto('/login')
  await fillField(page.getByLabel('Email'), 'unknown@example.com')
  await page.getByRole('button', { name: 'Continue' }).click()
  // Passed through rather than reworded, so the policy lives in one place.
  await expect(page.getByText('Signups are disabled on this server.')).toBeVisible()
})

test('Google sign-in completes the PKCE round trip', async ({ page }) => {
  await page.goto('/login?next=%2Fexperts')

  // A plain anchor, so it works before hydration too.
  const google = page.getByRole('link', { name: /Continue with Google/ })
  await expect(google).toBeVisible()
  await expect(google).toHaveAttribute('href', /\/api\/auth\/google\/start\?next=/)

  // Watch the whole chain: start → authorize URL → callback → the app.
  const seen: string[] = []
  page.on('request', (request) => {
    if (request.isNavigationRequest()) seen.push(new URL(request.url()).pathname)
  })

  await google.click()
  await expect(page).toHaveURL(/\/experts$/, { timeout: 20_000 })
  await expect(page.getByRole('heading', { name: 'Home', exact: true })).toBeVisible()

  expect(seen).toContain('/api/auth/google/start')
  expect(seen).toContain('/api/auth/callback')

  // The session is set, and both short-lived PKCE cookies are gone.
  const cookies = await page.context().cookies()
  const names = cookies.map((cookie) => cookie.name)
  expect(names).toContain('peritus_access_token')
  expect(names).toContain('peritus_refresh_token')
  // A used verifier left behind would let a replayed code be exchanged again.
  expect(names).not.toContain('peritus_pkce_verifier')
  expect(names).not.toContain('peritus_login_next')
})

test('the Google callback with no code returns to sign-in with a message', async ({ page }) => {
  await page.goto('/api/auth/callback')
  await expect(page).toHaveURL(/\/login\?.*error=/)
  await expect(page.getByText(/returned no code|expired/i)).toBeVisible()
})

test('a cancelled Google sign-in returns quietly, with no error', async ({ page }) => {
  // `access_denied` is the user pressing cancel. Not an error worth alarming
  // them about. (The `role="alert"` that is always present is Next's own route
  // announcer, so the assertion has to be scoped to the card.)
  await page.goto('/api/auth/callback?error=access_denied')
  await expect(page).toHaveURL(/\/login(\?|$)/)
  await expect(page.getByRole('heading', { name: 'Sign in to Peritus' })).toBeVisible()
  expect(new URL(page.url()).searchParams.get('error')).toBeNull()
  const card = page.locator('form').locator('..')
  await expect(card.locator('[role="alert"]')).toHaveCount(0)
})

test('signing out clears the session and blocks the app again', async ({ page }) => {
  await page.goto('/login')
  await fillField(page.getByLabel('Email'), 'tester@example.com')
  await page.getByRole('button', { name: 'Continue' }).click()
  const cells = page.locator('input[inputmode="numeric"]')
  for (const [index, digit] of [...'123456'].entries()) await fillField(cells.nth(index), digit)
  await expect(page).toHaveURL(/\/experts$/, { timeout: 15_000 })

  await page.goto('/settings')
  await page.getByRole('button', { name: 'Sign out everywhere' }).click()
  await expect(page).toHaveURL(/\/login/, { timeout: 15_000 })

  // And the app is gated again.
  await page.goto('/experts')
  await expect(page).toHaveURL(/\/login\?next=/)
})

test('an already-signed-in visitor to /login is sent on', async ({ page }) => {
  await page.goto('/login')
  await fillField(page.getByLabel('Email'), 'tester@example.com')
  await page.getByRole('button', { name: 'Continue' }).click()
  const cells = page.locator('input[inputmode="numeric"]')
  for (const [index, digit] of [...'123456'].entries()) await fillField(cells.nth(index), digit)
  await expect(page).toHaveURL(/\/experts$/, { timeout: 15_000 })

  // The back button after a sign-in should not show a form that would do
  // nothing.
  await page.goto('/login?next=%2Fchats')
  await expect(page).toHaveURL(/\/chats$/)
})
