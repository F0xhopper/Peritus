import { expect, test } from '@playwright/test'

import {
  fillField,
  expectResponsive,
  isPhoneProject,
  isTouchProject,
  resetApi,
  signIn,
  visibleContent,
} from './helpers'

/**
 * The sources page.
 *
 * It lists the sources an expert answers from: what they are, how many passages
 * each contributed, and a way into the record behind any one of them.
 */

const SLUG = 'varroa-mite-control-in-temperate-beekeeping'

test.beforeEach(async ({ page }) => {
  await resetApi(page)
  await signIn(page)
})

test('the page lists the sources the expert answers from', async ({ page }, testInfo) => {
  await page.goto(`/experts/${SLUG}/sources`)

  await expect(
    visibleContent(page).getByText('Varroa destructor and honeybee viral loads').first()
  ).toBeVisible()

  // Only the kept sources: a dropped candidate is not part of the corpus.
  await expect(visibleContent(page).getByText('Top 10 beekeeping tips for spring')).toHaveCount(0)

  // The count is the whole corpus, not the rows this page happened to return.
  await expect(visibleContent(page).getByText('21 sources')).toBeVisible()

  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('sort is URL state, so a sorted list is a link', async ({ page }, testInfo) => {
  await page.goto(`/experts/${SLUG}/sources`)

  if (isPhoneProject(testInfo.project.name)) {
    await page.getByLabel('Sort by').selectOption('added')
  } else {
    await page.getByRole('columnheader', { name: /Kind/ }).getByRole('button').click()
  }

  await expect(page).toHaveURL(/sort=(added|type)/, { timeout: 15_000 })

  // And it survives a reload, because it is in the URL.
  await page.reload()
  await expect(
    visibleContent(page).getByText('Varroa destructor and honeybee viral loads').first()
  ).toBeVisible()
})

test('a row opens its record', async ({ page }) => {
  await page.goto(`/experts/${SLUG}/sources`)

  await visibleContent(page).getByText('Amitraz resistance in field populations').first().click()

  const panel = page
    .getByRole('complementary', { name: 'Source' })
    .or(page.getByRole('dialog', { name: 'Source' }))
  await expect(panel.getByRole('heading', { name: /Amitraz resistance/ })).toBeVisible({
    timeout: 15_000,
  })
  // What it covers, and the identifiers — the two things worth opening a row for.
  await expect(panel.getByText('Covers')).toBeVisible()
  await expect(panel.getByText('acaricide resistance').first()).toBeVisible()
})

test('the export menu offers CSV and RIS, and the download works', async ({ page }) => {
  await page.goto(`/experts/${SLUG}/sources`)

  await page.getByRole('button', { name: /Export/ }).click()
  await expect(page.getByRole('menuitem', { name: 'CSV' })).toBeVisible()
  const ris = page.getByRole('menuitem', { name: /RIS/ })
  await expect(ris).toBeVisible()
  // RIS is the operationally important one: Zotero, Covidence, EndNote.
  await expect(ris).toContainText('Zotero')

  // And BibTeX, for a bibliography built in LaTeX.
  await expect(page.getByRole('menuitem', { name: /BibTeX/ })).toBeVisible()

  const download = page.waitForEvent('download')
  await ris.click()
  const file = await download
  // The filename comes from the API's own Content-Disposition.
  expect(file.suggestedFilename()).toMatch(/\.ris$/)
})

test('adding a source by URL queues an ingest and says it is reading', async ({ page }) => {
  await page.goto(`/experts/${SLUG}/sources`)

  await page
    .getByRole('button', { name: /Add a source/ })
    .first()
    .click()
  await expect(page.getByRole('heading', { name: 'Add a source' })).toBeVisible()

  await page.getByRole('tab', { name: 'URL' }).click()
  await fillField(page.getByLabel('Page address'), 'https://example.org/a-paper')
  await page.getByRole('button', { name: 'Add', exact: true }).click()

  // Ingest is durable: the dialog closes as soon as the job is queued.
  await expect(visibleContent(page).getByText('Reading a new source')).toBeVisible({
    timeout: 15_000,
  })
})

test('the upload tab refuses an oversized file before sending it', async ({ page }) => {
  await page.goto(`/experts/${SLUG}/sources`)
  await page
    .getByRole('button', { name: /Add a source/ })
    .first()
    .click()

  // 21 MB, just over the API's own 20 MB ceiling. Refused client-side so it is
  // not carried across the wire twice to be rejected at the far end.
  await page.setInputFiles('#source-file', {
    name: 'huge.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.alloc(21 * 1024 * 1024),
  })
  await expect(page.getByText(/larger than the 20 MB limit|21.0 MB/)).toBeVisible()
})

test('the sources are a card list on a phone and a table above it', async ({ page }, testInfo) => {
  await page.goto(`/experts/${SLUG}/sources`)
  const phone = isPhoneProject(testInfo.project.name)

  if (phone) {
    await expect(page.getByRole('table')).toBeHidden()
    await expect(page.getByRole('button', { name: /Varroa destructor/ })).toBeVisible()
  } else {
    await expect(page.getByRole('table')).toBeVisible()
    await expect(page.getByRole('columnheader', { name: /Source/ })).toBeVisible()
  }
  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('a concept link from the overview filters the list', async ({ page }) => {
  await page.goto(`/experts/${SLUG}`)
  await page.getByRole('link', { name: 'acaricide resistance' }).click()

  await expect(page).toHaveURL(/concept=acaricide\+resistance|concept=acaricide%20resistance/, {
    timeout: 15_000,
  })
  await expect(visibleContent(page).getByText('acaricide resistance').first()).toBeVisible()
  // Only the source that covers it.
  await expect(
    visibleContent(page).getByText('Amitraz resistance in field populations').first()
  ).toBeVisible()
  await expect(
    visibleContent(page).getByText('Varroa destructor and honeybee viral loads')
  ).toHaveCount(0)
})
