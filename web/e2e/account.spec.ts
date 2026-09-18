import { expect, test } from '@playwright/test'

import { expectResponsive, fillField, isTouchProject, resetApi, signIn } from './helpers'

/**
 * Settings → the account: name, email, password, sign-in methods, sessions,
 * and deletion. Against the mock, where `correct-password` is the password and
 * `123456` is every code.
 */

test.beforeEach(async ({ page }) => {
  await resetApi(page)
  await signIn(page)
})

test('the account sections render and fit', async ({ page }, testInfo) => {
  await page.goto('/settings')
  const main = page.locator('main')
  for (const name of [
    'Profile',
    'Email',
    'Password',
    'Sign-in methods',
    "Where you're signed in",
    'Delete account',
  ]) {
    await expect(main.getByRole('heading', { name, exact: true })).toBeVisible()
  }
  await expect(main.getByText('This device')).toBeVisible()
  await expect(main.getByText('Safari on macOS')).toBeVisible()
  await expect(main.getByText('Chrome on iPhone')).toBeVisible()
  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('renaming saves', async ({ page }) => {
  await page.goto('/settings')
  const field = page.getByLabel('Name', { exact: true })
  await expect(field).toHaveValue('Test Person')
  await fillField(field, 'Ada Lovelace')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText('Name saved.')).toBeVisible()
  await page.reload()
  await expect(page.getByLabel('Name', { exact: true })).toHaveValue('Ada Lovelace')
})

test('changing the password needs the current one', async ({ page }) => {
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Change password' }).click()
  await fillField(page.getByLabel('Current password', { exact: true }), 'wrong')
  await fillField(page.getByLabel('New password', { exact: true }), 'a brand new password')
  await page.getByRole('button', { name: 'Change password' }).click()
  await expect(page.getByText('Your current password is incorrect.')).toBeVisible()

  await fillField(page.getByLabel('Current password', { exact: true }), 'correct-password')
  await page.getByRole('button', { name: 'Change password' }).click()
  await expect(page.getByText(/Password changed/)).toBeVisible()
})

test('changing the email confirms the new address by code', async ({ page }) => {
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Change email' }).click()
  await fillField(page.getByLabel('New email', { exact: true }), 'moved@example.com')
  await page.getByRole('button', { name: 'Send code' }).click()
  await expect(page.getByText(/Enter the code we sent to/)).toBeVisible()

  const cells = page.locator('main input[inputmode="numeric"]')
  for (const [index, digit] of [...'123456'].entries()) await fillField(cells.nth(index), digit)
  await expect(page.locator('main').getByText('moved@example.com').first()).toBeVisible({
    timeout: 15_000,
  })
})

test('Google can be linked and then unlinked', async ({ page }) => {
  await page.goto('/settings')
  await page.getByRole('link', { name: 'Link Google' }).click()
  await expect(page).toHaveURL(/\/settings\?linked=google/, { timeout: 15_000 })
  await expect(page.getByText('Google is linked.')).toBeVisible()

  await page.getByRole('button', { name: 'Unlink' }).click()
  await page.getByRole('button', { name: 'Unlink' }).click()
  await expect(page.getByText('Google unlinked.')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Link Google' })).toBeVisible()
})

test('another device can be signed out', async ({ page }) => {
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Sign out of Chrome on iPhone' }).click()
  await expect(page.getByText('Signed out of that device.')).toBeVisible()
  await expect(page.locator('main').getByText('Chrome on iPhone')).toHaveCount(0)
})

test('deleting the account needs the email typed, then signs out', async ({ page }) => {
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Delete account…' }).click()
  const confirm = page.getByRole('button', { name: 'Delete forever' })
  await expect(confirm).toBeDisabled()
  await fillField(page.getByLabel(/to confirm/), 'someone@else.com')
  await expect(confirm).toBeDisabled()
  await fillField(page.getByLabel(/to confirm/), 'tester@example.com')
  await confirm.click()

  await expect(page).toHaveURL(/\/\?account=deleted/, { timeout: 15_000 })
  const names = (await page.context().cookies()).map((cookie) => cookie.name)
  expect(names).not.toContain('peritus_access_token')
  expect(names).not.toContain('peritus_refresh_token')
})
