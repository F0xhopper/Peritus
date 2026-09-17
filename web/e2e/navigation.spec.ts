import { expect, test } from '@playwright/test'

import { isPhoneProject, isTouchProject, resetApi, signIn, waitForHydration } from './helpers'

/**
 * Moving around inside the shell, without reloading the document.
 *
 * Every other spec in this suite arrives by `page.goto`, which is a full
 * document load — and a full load exercises none of the client router: no
 * `ViewTransition`, no history sync, no prefetch cache. That gap is why this
 * file exists. Both things it checks are invisible when they break: an
 * unhandled rejection leaves no mark on the page, and a shell that forgets
 * which expert you are looking at is only wrong if you know what it should say.
 */

const SLUG = 'varroa-mite-control-in-temperate-beekeeping'

test.beforeEach(async ({ page }) => {
  await resetApi(page)
  await signIn(page)
})

test('walking the expert’s pages raises nothing and reloads nothing', async ({
  page,
}, testInfo) => {
  test.skip(isTouchProject(testInfo.project.name), 'the sidebar is a drawer below lg')

  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(`${error.name}: ${error.message}`))
  await page.addInitScript(() => {
    const store = window as unknown as { __rejections: string[]; __loads: number }
    store.__rejections = []
    store.__loads = (store.__loads ?? 0) + 1
    window.addEventListener('unhandledrejection', (event) => {
      store.__rejections.push(String(event.reason))
    })
  })

  await page.goto(`/experts/${SLUG}`)

  // Three laps, because a transition that is interrupted by the *next*
  // navigation is the case that rejects.
  for (let lap = 0; lap < 3; lap += 1) {
    await page
      .getByRole('link', { name: /^Sources/ })
      .first()
      .click()
    await page.waitForURL(`**/${SLUG}/sources`)
    await page
      .getByRole('link', { name: /^Concepts/ })
      .first()
      .click()
    await page.waitForURL(`**/${SLUG}/graph`)
    await page.getByRole('link', { name: 'Overview' }).first().click()
    await page.waitForURL(`**/${SLUG}`)
  }

  const { rejections, loads } = await page.evaluate(() => {
    const store = window as unknown as { __rejections?: string[]; __loads?: number }
    return { rejections: store.__rejections ?? [], loads: store.__loads ?? 0 }
  })

  expect(rejections, 'an unhandled rejection during client-side navigation').toEqual([])
  expect(pageErrors, 'an uncaught error during client-side navigation').toEqual([])
  // One document for the whole walk: the init script runs once per load, so a
  // second count here means a navigation fell back to a full page load.
  expect(loads).toBe(1)
})

test('the shell keeps the expert while reading one of its chats', async ({ page }, testInfo) => {
  test.skip(isTouchProject(testInfo.project.name), 'the rail and sidebar are hidden below md')

  await page.goto(`/experts/${SLUG}`)
  await page
    .getByRole('link', { name: /How effective is drone brood removal/ })
    .first()
    .click()
  await page.waitForURL('**/chats/**')

  // A conversation's URL does not name an expert, so both navigation columns
  // have to resolve it from the chat — the rail included, which is the one
  // place that tells you *which* expert is answering.
  const rail = page.getByRole('navigation', { name: 'Experts' })
  await expect(rail.getByRole('link', { name: /Dr\. Marta Belen/ }).first()).toHaveAttribute(
    'aria-current',
    'page'
  )
  await expect(page.getByRole('navigation', { name: /Dr\. Marta Belen pages/ })).toBeVisible()
})

test('the sidebar folds away, and says so on the next load', async ({ page }, testInfo) => {
  test.skip(isTouchProject(testInfo.project.name), 'the sidebar only exists from lg')

  await page.goto(`/experts/${SLUG}`)
  await waitForHydration(page)
  const sidebar = page.getByRole('navigation', { name: /Dr\. Marta Belen pages/ })
  await expect(sidebar).toBeVisible()

  // The column's own edge is the control (shadcn's sidebar rail).
  await page.getByRole('button', { name: 'Collapse the sidebar' }).click()
  await expect(sidebar).toBeHidden()
  // Nothing becomes unreachable: the drawer's button comes back with it.
  const menu = page.getByRole('button', { name: 'Open navigation' })
  await expect(menu).toBeVisible()

  // The preference is a cookie, so the *server* renders the next load already
  // collapsed — there is no frame in which the column is back.
  await page.reload()
  await expect(sidebar).toBeHidden()
  await expect(menu).toBeVisible()

  // And the drawer still reaches every page of the expert.
  await menu.click()
  const drawer = page.getByRole('dialog')
  await expect(drawer.getByRole('link', { name: /^Sources/ })).toBeVisible()
  await page.keyboard.press('Escape')

  await waitForHydration(page)
  await page.keyboard.press('ControlOrMeta+\\')
  await expect(sidebar).toBeVisible()

  // And the edge brings it back on a click, from where the column used to be.
  await page.getByRole('button', { name: 'Collapse the sidebar' }).click()
  await expect(sidebar).toBeHidden()
  await page.getByRole('button', { name: 'Expand the sidebar' }).click()
  await expect(sidebar).toBeVisible()
})

test('the phone drawer lists the experts by name', async ({ page }, testInfo) => {
  test.skip(!isPhoneProject(testInfo.project.name), 'phones only')

  await page.goto(`/experts/${SLUG}`)
  await page.getByRole('button', { name: 'Open navigation' }).click()
  const drawer = page.getByRole('dialog')

  // Not a strip of unlabelled avatars: two monograms with the same initials
  // were the same grey square, and there is no tooltip on a touch device.
  await expect(drawer.getByRole('link', { name: /Dr\. Aurelia Vance/ })).toBeVisible()
  await expect(drawer.getByRole('link', { name: /^New expert/ })).toBeVisible()
  await drawer.getByRole('link', { name: /Dr\. Aurelia Vance/ }).click()
  await page.waitForURL('**/experts/stoic-philosophy')
})
