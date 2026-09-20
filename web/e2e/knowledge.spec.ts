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
const FLOW = `/experts/${SLUG}/knowledge?view=flow`
const GRAPH = `/experts/${SLUG}/knowledge?view=graph`
const OUTLINE = `/experts/${SLUG}/knowledge?view=outline`
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

/**
 * The Overview, in whichever of its two forms is showing: the column beside the
 * views from `lg`, or folded above the List below it. Both are in the HTML.
 */
function overview(page: Page): Locator {
  return page.getByRole('region', { name: 'Overview' }).filter({ visible: true })
}

/** Below `lg` the Overview's sections start folded, so the sources stay in reach. */
async function unfold(page: Page, section: string) {
  const header = overview(page).getByRole('button', { name: new RegExp(`^${section}`) })
  if ((await header.getAttribute('aria-expanded')) === 'false') await header.click()
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

  // The concept graph is a view of its own again, and the old link means what
  // it always did — at the size it asked for.
  await page.goto(`/experts/${SLUG}/graph?limit=200`)
  await expect(page).toHaveURL(/\/knowledge\?view=graph&limit=200$/)
  await page.goto(`/experts/${SLUG}/graph?limit=7`)
  await expect(page).toHaveURL(/\/knowledge\?view=graph$/)
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

// ── the overview ────────────────────────────────────────────────────────────

test('the overview says what the expert has read and how well it covers the syllabus', async ({
  page,
}, testInfo) => {
  await page.goto(LIST)

  const region = overview(page)
  await expect(region).toHaveCount(1)
  // Headline numbers, folded from the map: ten sources, 187 concepts.
  await expect(region.getByText('Passages')).toBeVisible()
  await expect(region.locator('dd').filter({ hasText: /^187$/ })).toBeVisible()

  await unfold(page, 'Syllabus')
  // Three of five key concepts meet their target, and the two that do not say
  // so in words — never by the bar's colour alone.
  await expect(region.getByText('3 of 5 on target')).toBeVisible()
  await expect(
    region.getByRole('button', { name: /monitoring thresholds.*2 · short/ })
  ).toBeVisible()

  await unfold(page, 'Missing texts')
  await expect(region.getByRole('button', { name: /Tools for Varroa Management/ })).toBeVisible()
  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('a kind filters the list, is a link, and clears from the toolbar', async ({ page }) => {
  await page.goto(LIST)
  await expect(
    visibleContent(page)
      .getByText(/Amitraz resistance in field/)
      .first()
  ).toBeVisible()

  await unfold(page, 'Sources')
  const webPages = overview(page).getByRole('button', { name: /^Web page/ })
  await webPages.click()
  await expect(page).toHaveURL(/kind=web/)
  await expect(webPages).toHaveAttribute('aria-pressed', 'true')
  // The list's two loaded rows are both papers.
  await expect(visibleContent(page).getByText('No sources match this filter.')).toBeVisible()

  // Loaded from the URL alone, it is the same page.
  await page.goto(`${LIST}&kind=paper`)
  await expect(
    visibleContent(page)
      .getByText(/Amitraz resistance in field/)
      .first()
  ).toBeVisible()
  await expect(content(page).getByText(/2 of 21 sources match/)).toBeVisible()

  await page.getByRole('button', { name: 'Show every source' }).click()
  await expect(page).not.toHaveURL(/kind=/)
})

test('a key concept chosen in the overview opens on the map', async ({ page }, testInfo) => {
  test.skip(isTouchProject(testInfo.project.name), 'below `lg` the overview stands above the List')
  await page.goto(MAP)
  const canvas = page.getByRole('img', { name: /Map of this expert's knowledge/ })
  await expect.poll(() => painted(canvas), { timeout: 20_000 }).toBeGreaterThan(2_000)

  await overview(page)
    .getByRole('button', { name: /^acaricide resistance/ })
    .click()
  await expect(page).toHaveURL(/concept=acaricide/)
  await expect(
    panel(page, 'Key concept').getByRole('heading', { name: 'acaricide resistance' })
  ).toBeVisible({ timeout: 15_000 })
})

test('the map can be zoomed and refitted from its own controls', async ({ page }) => {
  await page.goto(MAP)
  const canvas = page.getByRole('img', { name: /Map of this expert's knowledge/ })
  await expect.poll(() => painted(canvas), { timeout: 20_000 }).toBeGreaterThan(2_000)

  await page.getByRole('button', { name: 'Zoom in' }).click()
  await page.getByRole('button', { name: 'Zoom in' }).click()
  await page.getByRole('button', { name: 'Fit the whole map' }).click()
  // Still a picture, not a blank canvas: the loop re-armed after each.
  await expect.poll(() => painted(canvas), { timeout: 10_000 }).toBeGreaterThan(2_000)
  // The marks are explained where the map is wide enough to spare the room.
  if (page.viewportSize()!.width >= 640) {
    await expect(page.getByRole('list', { name: /What the map's marks mean/ })).toBeVisible()
  }
})

// ── the flow ────────────────────────────────────────────────────────────────

test('the flow draws sources, syllabus and concepts, and the links between them', async ({
  page,
}, testInfo) => {
  await page.goto(FLOW)

  const acaricide = content(page).getByRole('button', { name: /^acaricide resistance/ })
  await expect(acaricide.filter({ visible: true }).first()).toBeVisible({ timeout: 15_000 })
  await expect(
    content(page).getByRole('button', { name: /^Amitraz resistance in field/ })
  ).toBeVisible()
  await expect(content(page).getByRole('button', { name: /^amitraz/ })).toBeVisible()
  // A missing text stands where it would have been read.
  await expect(
    content(page).getByRole('button', { name: /^Missing\s*Tools for Varroa Management/ })
  ).toBeVisible()

  // One link per tag and one per concept shown: the fixture has fifteen tags.
  expect(await page.locator('path.flow-link').count()).toBeGreaterThan(15)
  // The diagram scrolls inside its own box; the page never does.
  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('a concept chosen in the flow opens with the sources that say it', async ({ page }) => {
  await page.goto(FLOW)
  const amitraz = content(page).getByRole('button', { name: /^amitraz/ })
  await expect(amitraz).toBeVisible({ timeout: 15_000 })
  await amitraz.click()

  await expect(page).toHaveURL(/node=\d+/)
  await expect(page).toHaveURL(/view=flow/)
  const concept = panel(page, 'Concept')
  await expect(concept.getByRole('heading', { name: 'amitraz' })).toBeVisible({ timeout: 15_000 })
  await expect(concept.getByText('Said by')).toBeVisible()
})

test('a folded sector opens in place', async ({ page }) => {
  await page.goto(FLOW)
  const more = content(page).getByRole('button', { name: '+1 more' })
  await expect(more).toBeVisible({ timeout: 15_000 })
  const before = await page.locator('path.flow-link').count()
  await more.click()
  await expect(content(page).getByRole('button', { name: 'Show fewer' })).toBeVisible()
  expect(await page.locator('path.flow-link').count()).toBe(before + 1)
})

// ── the graph ───────────────────────────────────────────────────────────────

/**
 * The Graph view: the concept graph the product had before the Map, back as a
 * view of this page. Its important behaviour is negative — **`computed: false`
 * is never an empty canvas** — and its canvas is held to the same rule as the
 * Map's: a test asserts that pixels were painted.
 */
function graphCanvas(page: Page): Locator {
  return page.getByRole('img', { name: /^Graph of \d+ concepts and claims/ })
}

test('the graph draws its concepts and claims on a canvas', async ({ page }, testInfo) => {
  await page.goto(GRAPH)

  const canvas = graphCanvas(page)
  await expect(canvas).toBeVisible({ timeout: 15_000 })
  await expect(canvas).toHaveAttribute('aria-label', /Graph of 6 concepts and claims/)
  // The Map is not mounted behind it: one view, one canvas.
  await expect(page.locator('canvas')).toHaveCount(1)
  await expect
    .poll(() => painted(canvas), { message: 'the graph never painted a pixel', timeout: 20_000 })
    .toBeGreaterThan(500)

  // What is shown, against what exists — the Graph's own count, with its links.
  // (The toolbar's "n of 187 concepts" is the Map's, and is hidden here.)
  await expect(content(page).getByText(/6 of 187 concepts · \d+ links/)).toBeVisible()
  await expect(content(page).getByText('busiest first')).toBeVisible()
  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('a graph the size of a real expert still draws', async ({ page }) => {
  // Four hundred nodes, which is the default cap. The fixture has six, and six
  // exercise neither the worker's tick budget nor the paint loop's early-outs.
  await useScenario(page, 'big-graph')
  await page.goto(GRAPH)

  await expect(content(page).getByText(/400 of 1,125 concepts/)).toBeVisible({ timeout: 15_000 })
  await expect
    .poll(() => painted(graphCanvas(page)), {
      message: 'a 400-node graph painted nothing',
      timeout: 30_000,
    })
    .toBeGreaterThan(5_000)
})

test('an un-extracted graph says so instead of showing an empty canvas', async ({ page }) => {
  await page.goto(`/experts/${BUILDING}/knowledge?view=graph`)

  await expect(content(page).getByText(/concept graph is still being extracted/)).toBeVisible({
    timeout: 15_000,
  })
  // No canvas at all — an empty one would read as "no concepts found".
  await expect(page.locator('canvas')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Watch the build' })).toBeVisible()
})

test('the node limit is URL state and re-fetches', async ({ page }, testInfo) => {
  test.skip(isTouchProject(testInfo.project.name), "the slider is in the node's sheet below lg")
  await page.goto(GRAPH)
  await expect(graphCanvas(page)).toBeVisible({ timeout: 15_000 })

  // Driven by keyboard: the accessible path, and the one a range input reports
  // reliably. One step down from the 400 default.
  const slider = page.getByLabel('Nodes')
  await slider.focus()
  await slider.press('ArrowLeft')
  await expect(page).toHaveURL(/limit=200/, { timeout: 15_000 })
  await expect(page).toHaveURL(/view=graph/)
  await expect(content(page).getByText(/6 of 187 concepts · \d+ links/)).toBeVisible()
})

test("the page's search finds a node of the graph and opens it there", async ({ page }) => {
  await page.goto(GRAPH)
  await expect(graphCanvas(page)).toBeVisible({ timeout: 15_000 })
  await choose(page, 'amitraz', /^amitraz\s*Concept/)

  // The Graph's own panel — its links — and not the Map's concept panel.
  const node = panel(page, 'Concept')
  await expect(node.getByRole('heading', { name: 'amitraz' })).toBeVisible({ timeout: 15_000 })
  await expect(node.getByText(/Concept · \d+ links?/)).toBeVisible()
  // A node of the Graph is not the page's selection: it may be a claim.
  await expect(page).not.toHaveURL(/node=/)
})

test('a contradiction is labelled as a judgement about this corpus', async ({ page }) => {
  await page.goto(GRAPH)
  await expect(graphCanvas(page)).toBeVisible({ timeout: 15_000 })
  // A claim: drawn on the Graph and nowhere else on the page.
  await choose(page, 'Mechanical control alone', /^Mechanical control alone.*Claim$/)

  const claim = panel(page, 'Claim')
  // "Judged to disagree", never "contradictions in the literature".
  await expect(claim.getByText('Judged to disagree')).toBeVisible({ timeout: 15_000 })
  await expect(claim.getByRole('button', { name: 'Show on map' })).toHaveCount(0)
})

test('a concept on the graph leads across to the same concept on the map', async ({
  page,
}, testInfo) => {
  test.skip(isTouchProject(testInfo.project.name), 'the panel is a modal sheet on touch')
  await page.goto(GRAPH)
  await expect(graphCanvas(page)).toBeVisible({ timeout: 15_000 })
  await choose(page, 'amitraz', /^amitraz\s*Concept/)

  await panel(page, 'Concept').getByRole('button', { name: 'Show on map' }).click()
  await expect(page).toHaveURL(/view=map/)
  await expect(page).toHaveURL(/node=5003/)
  // Now the Map's panel, with what the sources say.
  await expect(panel(page, 'Concept').getByText('Said by')).toBeVisible({ timeout: 15_000 })
})

// ── the outline ─────────────────────────────────────────────────────────────

test('the outline lists each work, how it was read, and its parts in place', async ({
  page,
}, testInfo) => {
  await page.goto(OUTLINE)

  // The header says the whole in words: nothing here is said by a bar alone.
  await expect(
    content(page).getByText('10 works · 152 of 172 passages read closely, 20 held')
  ).toBeVisible({ timeout: 15_000 })

  const book = content(page).getByRole('button', { name: /^Mite biology for beekeepers/ })
  await expect(book).toContainText('20 read closely, 20 held')
  await expect(book).toHaveAttribute('aria-expanded', 'false')
  await book.click()
  await expect(book).toHaveAttribute('aria-expanded', 'true')

  // A part by its heading with its place beside it, and a held stretch with no
  // heading by its place alone — collapsed to a range, not the locus twice.
  const host = content(page).getByRole('button', { name: /^The Mite and Its Host/ })
  await expect(host).toContainText('Book I, Chapter 1')
  await expect(host).toContainText('varroa biology')
  const held = content(page).getByRole('button', { name: /^Book II, Chapter 3–5/ })
  await expect(held).toContainText('Held')

  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('a part opens onto what it establishes, and leads to the text', async ({ page }) => {
  await page.goto(OUTLINE)
  const book = content(page).getByRole('button', { name: /^Mite biology for beekeepers/ })
  await expect(book).toBeVisible({ timeout: 15_000 })
  await book.click()

  await content(page)
    .getByRole('button', { name: /^The Reproductive Cycle/ })
    .click()
  // The stored summary opens with a title line; the view shows the prose.
  await expect(content(page).getByText(/The foundress enters a cell/)).toBeVisible({
    timeout: 15_000,
  })
  await expect(content(page).getByText(/Index Entry/)).toHaveCount(0)
  // Said once, at the head of the view, and not under every part.
  await expect(content(page).getByText(/own index of it, not a quotation/)).toHaveCount(1)

  // The summary is an index entry; the text is one link away, at that passage.
  const read = content(page).getByRole('link', { name: 'Read it' }).first()
  await expect(read).toHaveAttribute('href', /\/sources\/820\/read\?at=\d+$/)
})

test('a source with no headings shows what it establishes, or says it has none', async ({
  page,
}) => {
  await page.goto(OUTLINE)
  const cohort = content(page).getByRole('button', { name: /^Varroa destructor and honeybee/ })
  await expect(cohort).toBeVisible({ timeout: 15_000 })
  await cohort.click()
  await expect(content(page).getByText(/A five-year cohort of 212 colonies/)).toBeVisible({
    timeout: 15_000,
  })

  await content(page)
    .getByRole('button', { name: /^Deformed wing virus: transmission/ })
    .click()
  await expect(content(page).getByText('This source has no headings to outline.')).toBeVisible()
})

test('a source chosen in the outline opens its panel and keeps the view', async ({
  page,
}, testInfo) => {
  await page.goto(OUTLINE)
  const details = content(page).getByRole('button', {
    name: 'Details of Mite biology for beekeepers',
  })
  await expect(details).toBeVisible({ timeout: 15_000 })
  await details.click()

  await expect(page).toHaveURL(/source=820/)
  await expect(page).toHaveURL(/view=outline/)
  await expect(
    panel(page, 'Source').getByRole('heading', { name: 'Mite biology for beekeepers' })
  ).toBeVisible({ timeout: 15_000 })
  // On touch the panel is a modal sheet, and the page under it is inert.
  if (isTouchProject(testInfo.project.name)) return
  // The work in hand is open without having been opened.
  await expect(
    content(page).getByRole('button', { name: /^Mite biology for beekeepers/ })
  ).toHaveAttribute('aria-expanded', 'true')
})

test('the search narrows the outline to a part and opens the work it is in', async ({ page }) => {
  await page.goto(OUTLINE)
  await expect(
    content(page).getByRole('button', { name: /^Mite biology for beekeepers/ })
  ).toBeVisible({ timeout: 15_000 })

  await fillUntil(
    page.getByRole('textbox', { name: 'Find a source or concept' }),
    'reproductive',
    content(page).getByRole('button', { name: /^The Reproductive Cycle/ })
  )
  await expect(content(page).getByRole('button', { name: /^The Mite and Its Host/ })).toHaveCount(0)
  await expect(content(page).getByRole('button', { name: /^Varroa destructor and/ })).toHaveCount(0)
})

test('an expert that has read nothing says so in the outline', async ({ page }) => {
  await page.goto(`/experts/${BUILDING}/knowledge?view=outline`)
  await expect(content(page).getByText(/Nothing has been read yet/)).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByRole('button', { name: 'Watch the build' })).toBeVisible()
})
