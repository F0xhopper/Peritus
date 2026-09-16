import { expect, test } from '@playwright/test'

import {
  content,
  expectResponsive,
  fillField,
  isTouchProject,
  resetApi,
  signIn,
  useScenario,
  visibleContent,
} from './helpers'

/**
 * The graph, settings, admin and the public pages.
 *
 * The graph's important behaviour is negative: **`computed: false` is never an
 * empty canvas.** An expert can be answering questions while its concept graph
 * is still being extracted, and drawing nothing in that state would say "this
 * corpus has no concepts", which is the opposite of the truth.
 */

const SLUG = 'varroa-mite-control-in-temperate-beekeeping'
const BUILDING = 'measurement-error-in-nutritional-epidemiology'

test.beforeEach(async ({ page }) => {
  await resetApi(page)
  await signIn(page)
})

test('the graph draws its concepts on a canvas', async ({ page }, testInfo) => {
  await page.goto(`/experts/${SLUG}/graph`)

  const canvas = page.locator('canvas')
  await expect(canvas).toBeVisible()
  // Sized to its container at the device pixel ratio, not a fixed box.
  const size = await canvas.evaluate((node: HTMLCanvasElement) => ({
    w: node.width,
    h: node.height,
  }))
  expect(size.w).toBeGreaterThan(100)
  expect(size.h).toBeGreaterThan(100)

  /**
   * And it has actually **drawn** something.
   *
   * This assertion exists because its absence hid a dead feature: the layout
   * runs in a web worker, the worker was being loaded through a path the
   * bundler compiles as a static asset rather than a worker entry, and the
   * browser was handed raw TypeScript. No positions ever came back and the
   * canvas stayed empty — while this test passed, because a correctly sized
   * blank canvas is still a correctly sized canvas.
   *
   * Counting opaque pixels is the cheapest honest check: it needs no fixed
   * layout, no screenshot baseline, and it fails for every cause of "nothing
   * was painted" rather than for one.
   */
  await expect
    .poll(
      () =>
        canvas.evaluate((node: HTMLCanvasElement) => {
          const context = node.getContext('2d')
          if (!context) return 0
          const { data } = context.getImageData(0, 0, node.width, node.height)
          let painted = 0
          for (let i = 3; i < data.length; i += 4) if (data[i] !== 0) painted++
          return painted
        }),
      { message: 'the canvas never painted a pixel', timeout: 20_000 }
    )
    .toBeGreaterThan(500)

  // The counts say what is shown against what exists.
  await expect(content(page).getByText(/of 187 concepts/)).toBeVisible()
  await expect(content(page).getByText('busiest first')).toBeVisible()

  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('a graph the size of a real corpus still draws', async ({ page }) => {
  // Four hundred nodes, which is what the page caps at — the captured fixture
  // has six, and six nodes exercise neither the worker's tick budget nor the
  // paint loop's early-outs. A real expert in this product has a thousand
  // concepts, and the first time anyone looked at one the canvas was blank.
  await useScenario(page, 'big-graph')
  await page.goto(`/experts/${SLUG}/graph`)

  await expect(content(page).getByText(/400 of 1,125 concepts/)).toBeVisible()
  await expect
    .poll(
      () =>
        page.locator('canvas').evaluate((node: HTMLCanvasElement) => {
          const context = node.getContext('2d')
          if (!context) return 0
          const { data } = context.getImageData(0, 0, node.width, node.height)
          let painted = 0
          for (let i = 3; i < data.length; i += 4) if (data[i] !== 0) painted++
          return painted
        }),
      { message: 'a 400-node graph painted nothing', timeout: 30_000 }
    )
    .toBeGreaterThan(5_000)
})

test('an un-extracted graph says so instead of showing an empty canvas', async ({ page }) => {
  await page.goto(`/experts/${BUILDING}/graph`)

  await expect(content(page).getByText(/still being extracted/)).toBeVisible()
  await expect(content(page).getByText(/may already be answering questions/)).toBeVisible()
  // No canvas at all — an empty one would read as "no concepts found".
  await expect(page.locator('canvas')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Watch the build' })).toBeVisible()
})

test('the node limit is URL state and re-fetches', async ({ page }, testInfo) => {
  test.skip(isTouchProject(testInfo.project.name), 'the slider is in the sheet below lg')

  await page.goto(`/experts/${SLUG}/graph`)
  const slider = page.getByLabel('Nodes')
  await expect(slider).toBeVisible()

  // Driven by keyboard, which is both the accessible path and the one a range
  // input reports reliably.
  await slider.focus()
  await slider.press('ArrowLeft')
  // One step down from the 400 default.
  await expect(page).toHaveURL(/limit=200/, { timeout: 15_000 })
  await expect(content(page).getByText(/of 187 concepts/)).toBeVisible()
})

test('searching a concept focuses it and opens its detail', async ({ page }, testInfo) => {
  test.skip(isTouchProject(testInfo.project.name), 'search is a top-bar icon below lg')

  await page.goto(`/experts/${SLUG}/graph`)
  const search = page.getByLabel('Find a concept')
  await fillField(search, 'amitraz')
  await expect(page.getByRole('button', { name: /amitraz/ })).toBeVisible()
  await search.press('Enter')

  const panel = page
    .getByRole('complementary', { name: 'Concept' })
    .or(page.getByRole('dialog', { name: 'Concept' }))
  await expect(panel.getByRole('heading', { name: 'amitraz' })).toBeVisible({ timeout: 15_000 })
  await expect(panel.getByText(/link/)).toBeVisible()
})

test('a contradiction is labelled as a judgement about this corpus', async ({ page }, testInfo) => {
  test.skip(isTouchProject(testInfo.project.name), 'needs the search field')

  await page.goto(`/experts/${SLUG}/graph`)
  // The claim that sits on one side of the fixture's contradiction.
  await fillField(page.getByLabel('Find a concept'), 'Mechanical control alone')
  // Clicked, not Enter: this test is about what the panel *says* about a
  // contradiction, and the keyboard path has its own test above. A key event
  // has to land in the window between the suggestion rendering and the next
  // re-render, which under a loaded machine is a coin toss; a click on a
  // visible button is not.
  await page.getByRole('button', { name: /^Mechanical control alone/ }).click()

  const panel = page
    .getByRole('complementary', { name: 'Concept' })
    .or(page.getByRole('dialog', { name: 'Concept' }))
  // "Judged to disagree", never "contradictions in the literature".
  await expect(panel.getByText('Judged to disagree')).toBeVisible({ timeout: 15_000 })
})

test('settings shows the account, the theme and the credit state', async ({ page }, testInfo) => {
  await page.goto('/settings')

  await expect(page.getByRole('heading', { name: 'Account' })).toBeVisible()
  await expect(content(page).getByText('tester@example.com')).toBeVisible()

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

  await page.getByRole('button', { name: /^Delete Dr\. Marta Belen$/ }).click()
  const confirm = page.getByRole('button', { name: 'Delete', exact: true })
  // Disabled until the name matches: this cannot be undone and cannot be
  // cheaply rebuilt.
  await expect(confirm).toBeDisabled()

  await fillField(page.getByLabel(/Type Dr\. Marta Belen to confirm/), 'wrong name')
  await expect(confirm).toBeDisabled()

  await fillField(page.getByLabel(/Type Dr\. Marta Belen to confirm/), 'Dr. Marta Belen')
  await expect(confirm).toBeEnabled()
  await confirm.click()

  await expect(page).toHaveURL(/\/experts$/, { timeout: 15_000 })
  // Gone from the rail and the sidebar too, not only from this page — the
  // shell's own data has to be refetched, and the toast is the only place the
  // name may still appear.
  await expect
    .poll(async () => page.getByRole('link', { name: /Dr\. Marta Belen/ }).count(), {
      timeout: 15_000,
    })
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
  await expect(page.getByRole('heading', { name: 'Dr. Marta Belen' })).toBeVisible()

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
  // The hero is a recorded build log, not an illustration.
  await expect(page.getByLabel('A recorded build log')).toBeVisible()
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
