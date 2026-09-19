import { expect, test } from '@playwright/test'

import {
  content,
  expectResponsive,
  fillField,
  isTouchProject,
  resetApi,
  signIn,
  visibleContent,
} from './helpers'

/**
 * Settings, admin and the chats list.
 *
 * The concept graph that used to be tested here is the Knowledge page's Map
 * now, and its tests are in `knowledge.spec.ts`.
 */

const SLUG = 'varroa-mite-control-in-temperate-beekeeping'

test.beforeEach(async ({ page }) => {
  await resetApi(page)
  await signIn(page)
})

test('settings shows the account, the theme and the credit state', async ({ page }, testInfo) => {
  await page.goto('/settings')

  await expect(page.getByRole('heading', { name: 'Account', exact: true })).toBeVisible()
  await expect(content(page).getByText('tester@example.com').first()).toBeVisible()

  await expect(page.getByRole('heading', { name: 'Credits' })).toBeVisible()
  await expect(content(page).getByText('Free', { exact: true })).toBeVisible()
  // No checkout exists anywhere: the only remedy is to ask.
  const request = page.getByRole('link', { name: 'Request credits' })
  await expect(request).toHaveAttribute('href', /^mailto:/)
  await expect(content(page).getByText(/There is no checkout/)).toBeVisible()
  // And nothing pretends otherwise.
  await expect(page.getByRole('button', { name: /Upgrade|Buy|Subscribe/i })).toHaveCount(0)

  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('the theme control switches and sticks', async ({ page }) => {
  await page.goto('/settings')

  await page.getByRole('radio', { name: 'Light' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light', { timeout: 10_000 })
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')

  // And back to following the OS, which writes no attribute at all.
  await page.getByRole('radio', { name: 'System' }).click()
  await expect(page.locator('html')).not.toHaveAttribute('data-theme', 'light', { timeout: 10_000 })
})

test('the credit history shows what a build cost in both currencies', async ({ page }) => {
  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: 'History' })).toBeVisible()
  // Credits are the price; dollars are the cost. Both, together.
  await expect(visibleContent(page).getByText('-3').first()).toBeVisible()
  await expect(visibleContent(page).getByText('$1.62').first()).toBeVisible()
})

test('a rebuild warns that it starts the corpus over', async ({ page }, testInfo) => {
  await page.goto(`/experts/${SLUG}/settings`)

  await expect(page.getByRole('heading', { name: 'Rebuild' })).toBeVisible()
  await expect(content(page).getByText('A rebuild starts over from scratch')).toBeVisible()
  // And says what survives it, which is the non-obvious half.
  await expect(content(page).getByText(/Sources you uploaded yourself survive/)).toBeVisible()

  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('deleting an expert needs its name typed out', async ({ page }) => {
  await page.goto(`/experts/${SLUG}/settings`)

  await page
    .getByRole('button', { name: /^Delete Varroa mite control in temperate beekeeping$/ })
    .click()
  const confirm = page.getByRole('button', { name: 'Delete', exact: true })
  // Disabled until the name matches: this cannot be undone and cannot be
  // cheaply rebuilt.
  await expect(confirm).toBeDisabled()

  await fillField(
    page.getByLabel(/Type Varroa mite control in temperate beekeeping to confirm/),
    'wrong name'
  )
  await expect(confirm).toBeDisabled()

  await fillField(
    page.getByLabel(/Type Varroa mite control in temperate beekeeping to confirm/),
    'Varroa mite control in temperate beekeeping'
  )
  await expect(confirm).toBeEnabled()
  await confirm.click()

  await expect(page).toHaveURL(/\/experts$/, { timeout: 15_000 })
  // Gone from the rail and the sidebar too, not only from this page — the
  // shell's own data has to be refetched, and the toast is the only place the
  // name may still appear.
  await expect
    .poll(
      async () =>
        page.getByRole('link', { name: /Varroa mite control in temperate beekeeping/ }).count(),
      {
        timeout: 15_000,
      }
    )
    .toBe(0)
})

test('admin can grant credits, and reports the new balance', async ({ page }) => {
  await page.goto('/admin')

  await expect(page.getByRole('heading', { name: 'Admin', level: 1 })).toBeVisible()
  // The form is honest about what it is.
  await expect(content(page).getByText(/no payment provider behind this form/)).toBeVisible()

  await fillField(page.getByLabel('Account email or id'), 'someone@example.com')
  await fillField(page.getByLabel('Credits'), '25')
  await fillField(page.getByLabel('Reason'), 'Asked nicely')
  await page.getByRole('button', { name: 'Grant credits' }).click()

  await expect(content(page).getByText('Done')).toBeVisible({ timeout: 15_000 })
  await expect(content(page).getByText(/Granted 25 credits/)).toBeVisible()
})

test('a negative amount is a clawback, and the button says so', async ({ page }) => {
  await page.goto('/admin')
  await fillField(page.getByLabel('Account email or id'), 'someone@example.com')
  await fillField(page.getByLabel('Credits'), '-5')
  // A mistaken grant has to be reversible, so this is deliberate, not a bug.
  await expect(page.getByRole('button', { name: 'Claw back' })).toBeVisible()
})

test('the chats list groups by expert and undoes a delete', async ({ page }, testInfo) => {
  await page.goto('/chats')

  await expect(page.getByRole('heading', { name: 'Chats', level: 1 })).toBeVisible()
  await expect(
    page.getByRole('heading', { name: 'Varroa mite control in temperate beekeeping' })
  ).toBeVisible()

  // Scoped to the page: from `lg` the sidebar beside it lists the same chats,
  // so an unscoped match finds two links with this name.
  const row = content(page).getByRole('link', { name: /How effective is drone brood removal/ })
  await expect(row).toBeVisible()

  // Scoped for the same reason the row is: the sidebar's copy of this chat has
  // its own row menu with the same name.
  await content(page)
    .getByRole('button', { name: /Actions for How effective/ })
    .click()
  await page.getByRole('menuitem', { name: 'Delete' }).click()

  // Optimistic, with a real undo rather than a confirm in front of something
  // irreversible.
  await expect(row).toBeHidden({ timeout: 10_000 })
  await page.getByRole('button', { name: 'Undo' }).click()
  await expect(row).toBeVisible({ timeout: 10_000 })

  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('the landing page states the claim and replays a real log', async ({ page }, testInfo) => {
  await page.context().clearCookies()
  await page.goto('/')

  await expect(page.getByRole('heading', { level: 1 })).toContainText(/receipts/)
  // The product window is a recorded build log, not an illustration. It sits
  // under the hero and replays only while it is on screen, so bring it there.
  const log = page.getByLabel('A recorded build log')
  await log.scrollIntoViewIfNeeded()
  await expect(log).toBeVisible()
  await expect(content(page).getByText(/Planning the search/)).toBeVisible({ timeout: 15_000 })
  // Including a drop with its reason, which is the whole claim.
  await expect(content(page).getByText(/no primary data/)).toBeVisible({ timeout: 25_000 })

  // The limits are stated on the page, not buried.
  await expect(content(page).getByText(/not recorded/)).toBeVisible()
  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('the FAQ says plainly what Peritus is not', async ({ page }, testInfo) => {
  await page.context().clearCookies()
  await page.goto('/')

  const question = page.getByText('Is this systematic review software?')
  await question.click()
  await expect(content(page).getByText(/no dual human review/)).toBeVisible()
  // No fabricated accuracy figures, and it says why.
  await expect(content(page).getByText(/any number there would be invented/)).toBeVisible()

  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('privacy and terms are reachable and substantive', async ({ page }, testInfo) => {
  await page.context().clearCookies()

  await page.goto('/privacy')
  await expect(page.getByRole('heading', { name: 'Privacy', level: 1 })).toBeVisible()
  // Required for Google OAuth, and specific about this system rather than
  // generic boilerplate.
  await expect(content(page).getByText(/Supabase Auth/)).toBeVisible()
  await expect(content(page).getByText(/HttpOnly/)).toBeVisible()
  await expectResponsive(page, isTouchProject(testInfo.project.name))

  await page.goto('/terms')
  await expect(page.getByRole('heading', { name: 'Terms', level: 1 })).toBeVisible()
  await expect(content(page).getByText(/Its personas are not people/)).toBeVisible()
  await expectResponsive(page, isTouchProject(testInfo.project.name))
})
