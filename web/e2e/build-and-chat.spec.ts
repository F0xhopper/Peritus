import { expect, test } from '@playwright/test'

import {
  fillField,
  content,
  expectResponsive,
  isPhoneProject,
  isTouchProject,
  resetApi,
  signIn,
  useScenario,
  waitForHydration,
} from './helpers'

/**
 * The end-to-end flow the product exists for: type a topic, watch it build,
 * ask it something, read the citation.
 *
 * Written against the mock API's SSE streams rather than static responses,
 * because the two behaviours most worth testing here are only observable
 * against a real stream: the slug comes from the `created` event (never from a
 * client-side slugify), and a dropped connection resumes from its cursor
 * instead of replaying the log.
 */

test.beforeEach(async ({ page }) => {
  await resetApi(page)
  await signIn(page)
})

test('home lists the experts and the credit state', async ({ page }, testInfo) => {
  await page.goto('/experts')

  await expect(page.getByRole('heading', { name: 'Home', level: 1 })).toBeVisible()
  // Scoped to the centre column: the rail and the sidebar carry the same name
  // and are in the HTML at every width, hidden by CSS below `lg`.
  await expect(content(page).getByText('Dr. Marta Belen').first()).toBeVisible()

  if (isPhoneProject(testInfo.project.name)) {
    // On a phone the tiles are one line of text, so the expert cards — the
    // page — are not a screen and a half down.
    await expect(content(page).getByText(/\d+ experts? · \d+ building/)).toBeVisible()
  } else {
    // Only the tiles that say something, as label/value pairs. "Can answer"
    // is on each card, so it has no tile; Building shows while one runs.
    await expect(page.getByRole('term').filter({ hasText: /^Experts$/ })).toBeVisible()
    await expect(page.getByRole('term').filter({ hasText: /^Can answer$/ })).toHaveCount(0)
    await expect(page.getByRole('term').filter({ hasText: /^Building$/ })).toBeVisible()
    // Credits are enforced in the fixture, so the last tile is credits.
    await expect(page.getByRole('term').filter({ hasText: /^Credits$/ })).toBeVisible()
  }

  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('a topic builds, reaching chat-ready before the build finishes', async ({
  page,
}, testInfo) => {
  await page.goto('/experts')

  await fillField(page.getByLabel('Topic'), 'Beekeeping in cold climates')
  await page.getByRole('button', { name: 'Build' }).click()

  // The slug came from the server's `created` event, not from the client.
  await expect(page).toHaveURL(/\/experts\/beekeeping-in-cold-climates\/build/, {
    timeout: 20_000,
  })

  // Stages appear in order, from the streamed events.
  await expect(page.getByText('Research plan ready', { exact: false })).toBeVisible({
    timeout: 20_000,
  })
  await expect(page.getByText(/Screening done — kept 21/)).toBeVisible({
    timeout: 20_000,
  })

  // Asking becomes possible at `chat_ready`, a whole stage before `done` —
  // which is the single most important behaviour on this page.
  const askNow = page.getByRole('button', { name: /Ask now/ })
  await expect(askNow).toBeVisible({ timeout: 30_000 })

  // And the log keeps going afterwards. Scoped to the log, because the
  // terminal row deliberately appears twice: once there, once as the notice
  // above it.
  const log = page.getByRole('log', { name: 'Build log' })
  await expect(log.getByText(/Graph ready/)).toBeVisible({ timeout: 30_000 })
  await expect(log.getByText(/Voice written/)).toBeVisible({ timeout: 30_000 })
  await expect(log.getByText(/is ready —/)).toBeVisible({ timeout: 30_000 })
  // The finished notice, with its way onward: into a chat, not the Overview.
  await expect(page.getByRole('button', { name: 'Ask it something' })).toBeVisible()

  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('a dropped build stream resumes from its cursor rather than replaying', async ({ page }) => {
  // Every tail the client opens, by its `after=` cursor.
  const cursors: number[] = []
  page.on('request', (request) => {
    const match = /\/build\/events\?after=(\d+)/.exec(request.url())
    if (match) cursors.push(Number(match[1]))
  })

  await page.goto('/experts')
  await useScenario(page, 'drop-midway', 'resumable-build-test')

  await fillField(page.getByLabel('Topic'), 'Resumable build test')
  await page.getByRole('button', { name: 'Build' }).click()
  await expect(page).toHaveURL(/\/experts\/resumable-build-test\/build/, {
    timeout: 20_000,
  })

  // The connection dies part-way through; the client says so and reopens. It
  // is announced twice on purpose — once in the log's tail, once as a retry
  // button beside the counts.
  await expect(page.getByText('· reconnecting to the build log…')).toBeVisible({
    timeout: 20_000,
  })
  await expect(page.getByRole('button', { name: 'reconnecting — retry now' })).toBeVisible()

  // It then reaches the end, and — the point — the reconnect resumed from the
  // cursor rather than replaying the log: once a tail has resumed past seq 0,
  // no later tail starts from 0 again.
  const log = page.getByRole('log', { name: 'Build log' })
  await expect(log.getByText(/is ready —|Build finished/)).toBeVisible({
    timeout: 40_000,
  })
  const resumed = cursors.findIndex((cursor) => cursor > 0)
  expect(resumed, `tails opened at cursors ${cursors.join(', ')}`).toBeGreaterThanOrEqual(0)
  expect(cursors.slice(resumed)).not.toContain(0)

  // And each row is there exactly once. The log is virtualized and follows the
  // tail, so on a phone the first row is out of the DOM until scrolled back to.
  await expect(log.getByText('Chat ready —', { exact: false })).toHaveCount(1)
  await log.evaluate((element) => element.scrollTo({ top: 0 }))
  await expect(log.getByText('Research plan ready', { exact: false })).toHaveCount(1)
})

test('a 402 renders the numbers and the one remedy, and keeps the form', async ({ page }) => {
  await page.goto('/experts/new')
  await useScenario(page, 'insufficient-credits')

  const subject = page.getByLabel('Subject')
  await subject.click()
  await fillField(subject, 'Something expensive')
  // The visible one: `/experts/new` has an inline Build at `md` and up and a
  // sticky-footer Build below it, and both are in the HTML.
  await page.getByRole('button', { name: 'Build' }).filter({ visible: true }).first().click()

  await expect(content(page).getByText('Not enough credits')).toBeVisible({
    timeout: 20_000,
  })
  await expect(content(page).getByText(/costs 8 credits, and you have 2/)).toBeVisible()
  // The remedy is to ask. There is no checkout anywhere in this product.
  const request = page.getByRole('link', { name: 'Request credits' })
  await expect(request).toBeVisible()
  await expect(request).toHaveAttribute('href', /^mailto:/)
  // The form is still there, with the topic still in it.
  await expect(page.getByLabel('Subject')).toHaveValue('Something expensive')
})

test('cancelling a build refunds and says so', async ({ page }) => {
  await page.goto('/experts')
  await fillField(page.getByLabel('Topic'), 'Cancel me please')
  await page.getByRole('button', { name: 'Build' }).click()
  await expect(page).toHaveURL(/\/experts\/cancel-me-please\/build/, {
    timeout: 20_000,
  })

  await page
    .getByRole('button', { name: /^Cancel/ })
    .first()
    .click()
  await expect(page.getByRole('heading', { name: 'Cancel this build?' })).toBeVisible()
  await page.getByRole('button', { name: 'Cancel build' }).click()

  // In the toast, which lives outside `main`.
  await expect(page.getByText(/credits refunded/i)).toBeVisible({
    timeout: 20_000,
  })
})

test('the overview reads correctly and gates chat on readiness', async ({ page }, testInfo) => {
  await page.goto('/experts/varroa-mite-control-in-temperate-beekeeping')

  await expect(page.getByRole('heading', { name: 'Dr. Marta Belen', level: 1 })).toBeVisible()
  await expect(
    content(page).getByText('Varroa mite control in temperate beekeeping').first(),
  ).toBeVisible()

  // Properties, read off the real payload.
  // Status and readiness are one line now, not two rows saying the same thing.
  await expect(content(page).getByText('Ready · concept map built')).toBeVisible()
  await expect(content(page).getByText('21 kept of 30 screened')).toBeVisible()
  // The acceptance rate and the rubric are stated, not implied.
  await expect(content(page).getByText(/70.0%/)).toBeVisible()
  await expect(content(page).getByText('v5-structured-q5r6', { exact: false })).toBeVisible()

  // Chat is offered, because readiness is past pending.
  await expect(page.getByRole('heading', { name: /^Ask Dr\. Marta Belen$/ })).toBeVisible()
  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('a pending expert cannot be chatted with, and says where to look', async ({ page }) => {
  await page.goto('/experts/measurement-error-in-nutritional-epidemiology')
  await expect(content(page).getByText(/cannot answer yet/)).toBeVisible()
  // With a link to the build rather than a dead end.
  await expect(page.getByRole('link', { name: /Watch the build/ })).toBeVisible()
})

test('an answer streams, cites its sources, and flags an invented marker', async ({
  page,
}, testInfo) => {
  await page.goto('/chats/2f2b8a4e-1c9d-4f8a-9b1e-7c0d2a5f6e31')

  // The persisted turn is server-rendered, so it is there on first paint.
  await expect(
    content(page)
      .getByText(/Drone brood removal reduces mite load/)
      .first(),
  ).toBeVisible()

  const composer = page.getByLabel('Your question')
  await fillField(composer, 'Does the timing of removal matter?')
  await page.getByRole('button', { name: 'Send' }).click()

  // The status line, then tokens.
  await expect(content(page).getByText(/Searching|Composing|Reading the question/)).toBeVisible({
    timeout: 15_000,
  })
  await expect(
    content(page)
      .getByText(/43% reduction relative to untreated/)
      .first(),
  ).toBeVisible({ timeout: 30_000 })

  // Citations resolve to chips; the marker the answer invented does not.
  const chip = page.getByRole('button', { name: /^Citation 1:/ })
  await expect(chip.first()).toBeVisible({ timeout: 30_000 })
  // Exactly one: a fabricated marker is rendered as plain text, and the
  // streamed turn must not still be on screen beside its persisted copy.
  await expect(page.getByTitle('This reference resolves to nothing')).toHaveCount(1)

  // Opening a citation shows the passage in the context panel. Scoped to the
  // panel, because the answer's own collapsed citation list holds the same
  // text — and that list is closed, so an unscoped match finds a hidden node.
  await chip.first().click()
  const panel = page
    .getByRole('complementary', { name: 'Cited passage' })
    .or(page.getByRole('dialog', { name: 'Cited passage' }))
  await expect(panel.getByText(/reduced mite load by 43%/)).toBeVisible({
    timeout: 15_000,
  })

  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('a busy conversation says so and counts down instead of retrying blindly', async ({
  page,
}) => {
  await page.goto('/chats/2f2b8a4e-1c9d-4f8a-9b1e-7c0d2a5f6e31')
  await useScenario(page, 'chat-busy')

  await fillField(page.getByLabel('Your question'), 'Anything at all')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(content(page).getByText('Still answering')).toBeVisible({
    timeout: 15_000,
  })
  await expect(content(page).getByText(/It will free up in \d+s/)).toBeVisible()
})

test('renaming a chat is optimistic and persists', async ({ page }) => {
  await page.goto('/chats/2f2b8a4e-1c9d-4f8a-9b1e-7c0d2a5f6e31')

  // The title is server-rendered, so it is clickable before React has attached
  // its handler — a click that early is lost and the field never opens.
  await waitForHydration(page)
  await page.getByTitle('Click to rename').click()
  const field = page.getByLabel('Chat title')
  await fillField(field, 'Drone brood removal, revisited')
  await field.press('Enter')

  // Visible immediately, from the optimistic update.
  await expect(page.getByText('Drone brood removal, revisited').first()).toBeVisible()
  await page.reload()
  // The top bar's title, which is the one place it always shows.
  await expect(page.getByTitle('Click to rename')).toContainText('Drone brood removal, revisited', {
    timeout: 15_000,
  })
})

test('the nav drawer opens, navigates, and closes behind it', async ({ page }, testInfo) => {
  const compact = isPhoneProject(testInfo.project.name) || testInfo.project.name === 'ipad-portrait'
  test.skip(!compact, 'the drawer only exists below the lg tier')

  await page.goto('/experts')
  const menu = page.getByRole('button', { name: 'Open navigation' })
  await menu.click()

  // The rail's tooltips become names in the drawer — the tap form of the same
  // information.
  const drawer = page.getByRole('dialog')
  await expect(drawer).toBeVisible()
  await expect(drawer.getByText('All experts')).toBeVisible()

  await drawer.getByText('All experts').click()
  // Any navigation closes it: a drawer left over the page just navigated to is
  // the commonest drawer bug there is.
  await expect(drawer).toBeHidden({ timeout: 10_000 })
})

test('Escape closes the drawer and returns focus to the menu button', async ({
  page,
}, testInfo) => {
  test.skip(!isPhoneProject(testInfo.project.name), 'phones only')

  await page.goto('/experts')
  const menu = page.getByRole('button', { name: 'Open navigation' })
  await menu.click()
  await expect(page.getByRole('dialog')).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toBeHidden()
  await expect(menu).toBeFocused()
})

test('the command palette finds an expert and jumps to it', async ({ page }, testInfo) => {
  test.skip(
    isPhoneProject(testInfo.project.name),
    'a phone uses the search icon, tested separately',
  )

  await page.goto('/experts')
  await page.keyboard.press('ControlOrMeta+k')

  const search = page.getByLabel('Search experts, chats and actions')
  await expect(search).toBeVisible()
  await fillField(search, 'varroa')
  await page.keyboard.press('Enter')

  await expect(page).toHaveURL(/\/experts\/varroa-mite-control-in-temperate-beekeeping/, {
    timeout: 15_000,
  })
})

test('the sidebar search opens the palette where the top bar has no search button', async ({
  page,
}, testInfo) => {
  test.skip(
    isPhoneProject(testInfo.project.name) || testInfo.project.name === 'ipad-portrait',
    'below lg there is no sidebar; the top bar search icon is the trigger',
  )

  await page.goto('/experts')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(page.getByLabel('Search experts, chats and actions')).toBeVisible()
})
