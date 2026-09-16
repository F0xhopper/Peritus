import { expect, test } from '@playwright/test'

import {
  content,
  expectResponsive,
  isTouchProject,
  resetApi,
  signIn,
  visible,
  waitForHydration,
} from './helpers'

/**
 * Share links, from both ends.
 *
 * The owner's half is a small state machine — off, on, reset, off — whose
 * every transition is one people will be nervous about, so each is asserted to
 * say what it did. The viewer's half is mostly about *absence*: someone who
 * opened a link can read and ask, and must not meet a single control that
 * changes the expert. The API enforces that regardless; these tests are about
 * never showing a button that cannot work.
 */

const SLUG = 'varroa-mite-control-in-temperate-beekeeping'
/** Seeded in the mock: someone else's expert with a live link. */
const FOREIGN_TOKEN = 'mockSharedTokenForTheThomismExpert01'
const FOREIGN_SLUG = 'thomism'

test.beforeEach(async ({ page }) => {
  await resetApi(page)
})

test('an owner creates, resets and turns off a link from Settings', async ({ page }, testInfo) => {
  await signIn(page)
  await page.goto(`/experts/${SLUG}/settings`)
  await waitForHydration(page)

  const main = content(page)
  await expect(main.getByRole('heading', { name: 'Sharing' })).toBeVisible()
  // The upload warning is said before the link exists, not after.
  await expect(main.getByText(/Includes 1 file you uploaded/)).toBeVisible()

  await main.getByRole('button', { name: 'Create link' }).click()
  const field = main.getByLabel('Share link')
  await expect(field).toHaveValue(/\/share\/[A-Za-z0-9_-]{32,}$/)
  const first = await field.inputValue()
  await expectResponsive(page, isTouchProject(testInfo.project.name))

  // Resetting is confirmed, then replaces the token.
  await main.getByRole('button', { name: 'Reset link' }).click()
  await expect(main.getByText('Reset the link?')).toBeVisible()
  await main.getByRole('button', { name: 'Reset link' }).click()
  await expect(field).not.toHaveValue(first)

  // Stopping is confirmed, then the link is gone.
  await main.getByRole('button', { name: 'Stop sharing' }).click()
  await expect(main.getByText('Stop sharing?')).toBeVisible()
  await main.getByRole('button', { name: 'Stop sharing' }).click()
  await expect(main.getByRole('button', { name: 'Create link' })).toBeVisible()
  await expect(main.getByLabel('Share link')).toHaveCount(0)
})

test('the Overview menu opens the same share controls', async ({ page }) => {
  await signIn(page)
  await page.goto(`/experts/${SLUG}`)
  await waitForHydration(page)

  await content(page).getByRole('button', { name: 'More actions' }).click()
  await page.getByRole('menuitem', { name: 'Share…' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('button', { name: 'Create link' })).toBeVisible()
})

test('a signed-out visitor sees the card and is asked to sign in', async ({ page }, testInfo) => {
  await page.goto(`/share/${FOREIGN_TOKEN}`)

  const main = content(page)
  await expect(main.getByRole('heading', { level: 1, name: 'Fr. Reginald Hale' })).toBeVisible()
  await expect(main.getByText('Your questions are private.', { exact: false })).toBeVisible()

  // Sign-in comes straight back here.
  const signInLink = main.getByRole('link', { name: 'Sign in to open it' })
  await expect(signInLink).toHaveAttribute(
    'href',
    `/login?next=${encodeURIComponent(`/share/${FOREIGN_TOKEN}`)}`
  )

  // Never indexed, and the token never leaves in a Referer.
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', /noindex/)
  const response = await page.request.get(`/share/${FOREIGN_TOKEN}`)
  expect(response.headers()['referrer-policy']).toBe('no-referrer')
  expect(response.headers()['x-robots-tag']).toMatch(/noindex/)

  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('an inactive link says so, and says nothing else', async ({ page }) => {
  await page.goto('/share/thisTokenDoesNotExistAnywhereAtAll00')
  await expect(
    content(page).getByRole('heading', { name: 'This link is not active' })
  ).toBeVisible()
  await expect(page.getByText('Fr. Reginald Hale')).toHaveCount(0)
})

test('a signed-in viewer opens the expert and meets no owner controls', async ({
  page,
}, testInfo) => {
  await signIn(page)
  await page.goto(`/share/${FOREIGN_TOKEN}`)
  await waitForHydration(page)

  await content(page).getByRole('button', { name: 'Open the expert' }).click()
  await page.waitForURL(`**/experts/${FOREIGN_SLUG}`)

  const main = content(page)
  await expect(main.getByRole('heading', { level: 1, name: 'Fr. Reginald Hale' })).toBeVisible()
  await expect(main.getByText(/Shared with you/)).toBeVisible()
  // Reading and asking, yes.
  await expect(visible(page, `[id="ask"]`)).toBeVisible()
  // Changing, no: no avatar picker, and no Settings or Share in the menu.
  await expect(main.getByRole('button', { name: 'Change avatar' })).toHaveCount(0)
  await main.getByRole('button', { name: 'More actions' }).click()
  await expect(page.getByRole('menuitem', { name: 'Share…' })).toHaveCount(0)
  await expect(page.getByRole('menuitem', { name: 'Settings' })).toHaveCount(0)
  await expect(page.getByRole('menuitem', { name: 'Remove from my experts' })).toBeVisible()
  await page.keyboard.press('Escape')

  if (!isTouchProject(testInfo.project.name)) {
    // The sidebar has no Settings row for it either.
    await expect(visible(page, `a[href="/experts/${FOREIGN_SLUG}/settings"]`)).toHaveCount(0)
  }

  // The Sources page reads the whole record but offers no way to add to it.
  await page.goto(`/experts/${FOREIGN_SLUG}/sources`)
  // Wait for the page itself, or an absence assertion passes on a blank one.
  await expect(content(page).getByRole('button', { name: 'Export the sources' })).toBeVisible()
  await expect(content(page).getByRole('button', { name: 'Add a source' })).toHaveCount(0)

  // And Settings does not exist for a viewer.
  await page.goto(`/experts/${FOREIGN_SLUG}/settings`)
  await expect(page.getByText(/does not exist, or it belongs to someone else/)).toBeVisible()
})

test('a viewer can remove a shared expert from their workspace', async ({ page }) => {
  await signIn(page)
  await page.goto(`/share/${FOREIGN_TOKEN}`)
  await waitForHydration(page)
  await content(page).getByRole('button', { name: 'Open the expert' }).click()
  await page.waitForURL(`**/experts/${FOREIGN_SLUG}`)
  await waitForHydration(page)

  await content(page).getByRole('button', { name: 'More actions' }).click()
  await page.getByRole('menuitem', { name: 'Remove from my experts' }).click()
  await page.waitForURL('**/experts')
  await expect(page.getByText(/Removed Fr\. Reginald Hale/)).toBeVisible()
  await expect(page.locator(`a[href="/experts/${FOREIGN_SLUG}"]`)).toHaveCount(0)
})
