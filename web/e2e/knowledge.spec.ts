import { expect, test, type Locator, type Page } from '@playwright/test'

import {
  content,
  expectResponsive,
  fillUntil,
  isTouchProject,
  resetApi,
  signIn,
  useScenario,
  visibleContent,
} from './helpers'

/**
 * The Knowledge page: the Map and the List of one expert's syllabus, concepts
 * and sources (docs/plans/expert-brain.md).
 *
 * The canvas rule from web/AGENTS.md holds here: **a canvas test asserts that
 * pixels were painted.** A correctly sized blank canvas is still a correctly
 * sized canvas, which is how a wedged paint loop once stayed green.
 */

const SLUG = 'varroa-mite-control-in-temperate-beekeeping'
const BUILDING = 'measurement-error-in-nutritional-epidemiology'
const MAP = `/experts/${SLUG}/knowledge?view=map`
const LIST = `/experts/${SLUG}/knowledge?view=list`

test.beforeEach(async ({ page }) => {
  await resetApi(page)
  await signIn(page)
})

function panel(page: Page, name: string): Locator {
  return page.getByRole('complementary', { name }).or(page.getByRole('dialog', { name }))
}

function painted(canvas: Locator): Promise<number> {
  return canvas.evaluate((node: HTMLCanvasElement) => {
    const context = node.getContext('2d')
    if (!context) return 0
    const { data } = context.getImageData(0, 0, node.width, node.height)
    let count = 0
    for (let i = 3; i < data.length; i += 4) if (data[i] !== 0) count++
    return count
  })
}

async function choose(page: Page, text: string, option: RegExp) {
  const field = page.getByLabel('Find a source or concept')
  const match = page.getByRole('button', { name: option }).first()
  await fillUntil(field, text, match)
  await match.click()
}

test('the map draws the syllabus, the cloud and the orbit', async ({ page }, testInfo) => {
  await page.goto(MAP)

  const canvas = page.getByRole('img', { name: /Map of this expert's knowledge/ })
  await expect(canvas).toBeVisible()
  // The canvas's own summary is the accessible form of what it draws.
  await expect(canvas).toHaveAttribute('aria-label', /5 key concepts in 2 facets, 22 concepts/)
  await expect(canvas).toHaveAttribute('aria-label', /2 named texts missing/)

  await expect
    .poll(() => painted(canvas), { message: 'the map never painted', timeout: 20_000 })
    .toBeGreaterThan(2_000)

  // What is drawn, against what exists.
  await expect(content(page).getByText(/22 of 187 concepts/)).toBeVisible()
  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('a map the size of a real expert still draws', async ({ page }) => {
  await useScenario(page, 'big-map')
  await page.goto(MAP)

  await expect(content(page).getByText(/250 of 1,063 concepts/)).toBeVisible()
  await expect
    .poll(() => painted(page.getByRole('img', { name: /Map of this expert's knowledge/ })), {
      message: 'a 250-concept map painted nothing',
      timeout: 30_000,
    })
    .toBeGreaterThan(8_000)
})

test('an expert with nothing to map says so instead of drawing an empty canvas', async ({
  page,
}) => {
  await page.goto(`/experts/${BUILDING}/knowledge?view=map`)

  await expect(content(page).getByText(/Nothing to map yet/)).toBeVisible()
  await expect(page.locator('canvas')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Watch the build' })).toBeVisible()
})

test('a concept opens with its sources, its claims and the point in dispute', async ({ page }) => {
  await page.goto(MAP)
  await choose(page, 'drone brood removal', /^drone brood removal\s*Concept/)
  const concept = panel(page, 'Concept')
  await expect(concept.getByRole('heading', { name: 'drone brood removal' })).toBeVisible({
    timeout: 15_000,
  })
  // The bridge the old concept panel never managed: the sources that say it.
  await expect(concept.getByText('Said by')).toBeVisible()
  await expect(
    concept.getByRole('button', { name: /Drone brood trapping as integrated pest management/ })
  ).toBeVisible()
  // "Judged to disagree", in this corpus — never "contradictions in the literature".
  await expect(
    concept.getByText(/Judged to disagree about whether removal alone/).first()
  ).toBeVisible()
  // Every claim leads into the passage it came from.
  await expect(
    concept.getByRole('link', { name: /Mite biology for beekeepers/ }).first()
  ).toHaveAttribute('href', /\/sources\/820\/read\?at=8820/)
})

test('a key concept says its coverage in words and leads to the list', async ({ page }) => {
  await page.goto(MAP)
  await choose(page, 'monitoring', /^monitoring thresholds\s*Key concept/)

  const key = panel(page, 'Key concept')
  await expect(key.getByRole('heading', { name: 'monitoring thresholds' })).toBeVisible({
    timeout: 15_000,
  })
  await expect(key.getByText('2 sources; 2 treat it.')).toBeVisible()
  await expect(key.getByText('Short of this expert’s target.')).toBeVisible()
  // The named text, and that it is missing.
  await expect(key.getByText('Tools for Varroa Management', { exact: true })).toBeVisible()
  await expect(key.getByText('not in the sources')).toBeVisible()

  await key.getByRole('button', { name: 'Show in list' }).click()
  await expect(page).toHaveURL(/view=list/)
  await expect(page).toHaveURL(/concept=monitoring/)
})

test('a missing text leads the owner to add a source', async ({ page }) => {
  await page.goto(`${MAP}&gap=0`)

  const gap = panel(page, 'Missing text')
  await expect(gap.getByText(/The plan named/)).toBeVisible({ timeout: 15_000 })
  await expect(gap.getByText(/It is not in this expert’s sources/)).toBeVisible()
  await gap.getByRole('button', { name: 'Add a source' }).click()
  await expect(page.getByRole('heading', { name: 'Add a source' })).toBeVisible()
})

test('a source names the concepts drawn from it', async ({ page }) => {
  await page.goto(LIST)
  await visibleContent(page).getByText('Amitraz resistance in field populations').first().click()

  const source = panel(page, 'Source')
  await expect(source.getByRole('heading', { name: /Amitraz resistance/ })).toBeVisible({
    timeout: 15_000,
  })
  await expect(source.getByText('Concepts from this source')).toBeVisible()
  await expect(source.getByRole('button', { name: /^amitraz/ })).toBeVisible()
  await expect(
    source.getByRole('button', { name: /acaricide resistance\s*Sets out/ })
  ).toBeVisible()
})

test('switching view keeps the selection', async ({ page }, testInfo) => {
  // Below `lg` the panel is a modal bottom sheet over the toolbar; there the
  // view is switched with the panel closed, and the selection is the URL's.
  test.skip(isTouchProject(testInfo.project.name), 'the panel is a modal sheet on touch')
  await page.goto(`${LIST}&source=812`)
  await expect(panel(page, 'Source').getByRole('heading', { name: /Amitraz/ })).toBeVisible({
    timeout: 15_000,
  })

  await page.getByRole('radio', { name: 'Map' }).first().click()
  await expect(page).toHaveURL(/view=map/)
  await expect(page).toHaveURL(/source=812/)
  await expect(panel(page, 'Source').getByRole('heading', { name: /Amitraz/ })).toBeVisible()
  await expect(page.getByRole('img', { name: /Map of this expert's knowledge/ })).toBeVisible()
})

test('the old pages still lead here, with what they asked for', async ({ page }) => {
  await page.goto(`/experts/${SLUG}/sources?source=812`)
  await expect(page).toHaveURL(/\/knowledge\?.*source=812/)
  await expect(page).toHaveURL(/view=list/)

  await page.goto(`/experts/${SLUG}/graph?limit=200`)
  await expect(page).toHaveURL(/\/knowledge\?view=map$/)
})

test('an answer shows its cited sources on the map', async ({ page }) => {
  await page.goto(`${MAP}&cited=804,812`)
  await expect(content(page).getByText('The sources one answer cited')).toBeVisible()
  await expect
    .poll(() => painted(page.getByRole('img', { name: /Map of this expert's knowledge/ })), {
      timeout: 20_000,
    })
    .toBeGreaterThan(2_000)
  await page.getByRole('button', { name: /Stop showing the answer/ }).click()
  await expect(page).not.toHaveURL(/cited=/)
})

test('idle is alive and engaged is still; reduced motion is always still', async ({
  page,
}, testInfo) => {
  test.skip(isTouchProject(testInfo.project.name), 'the idle turn is judged with a mouse')
  await page.goto(MAP)
  const canvas = page.getByRole('img', { name: /Map of this expert's knowledge/ })
  await expect.poll(() => painted(canvas), { timeout: 20_000 }).toBeGreaterThan(2_000)
  // Past the entrance pulses.
  await page.waitForTimeout(2_000)

  const reduced = testInfo.project.name === 'reduced-motion'
  const first = await canvas.screenshot()
  await page.waitForTimeout(1_000)
  const second = await canvas.screenshot()
  if (reduced) {
    // Never turns, tilts or fires.
    expect(second.equals(first), 'the map moved under reduced motion').toBe(true)
  } else {
    // Untouched, it turns and fires.
    expect(second.equals(first), 'the idle map held perfectly still').toBe(false)
    // Engaged, it flattens and holds still.
    const box = await canvas.boundingBox()
    await page.mouse.move(box!.x + 12, box!.y + 12)
    await page.waitForTimeout(1_200)
    const still = await canvas.screenshot()
    await page.waitForTimeout(700)
    expect((await canvas.screenshot()).equals(still), 'the engaged map kept moving').toBe(true)
  }
})
