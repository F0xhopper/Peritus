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
 * The sources ledger.
 *
 * The claim the whole product rests on is that you can see what it threw away,
 * so these tests care most about the rejected half being first-class: present
 * by default, filterable to on its own, and carrying its reason.
 */

const SLUG = 'varroa-mite-control-in-temperate-beekeeping'

test.beforeEach(async ({ page }) => {
  await resetApi(page)
  await signIn(page)
})

test('the ledger shows kept and dropped sources together', async ({ page }, testInfo) => {
  await page.goto(`/experts/${SLUG}/sources`)

  await expect(visibleContent(page).getByText('Varroa destructor and honeybee viral loads').first()).toBeVisible()
  // A dropped source, with its reason — not hidden behind a debug toggle.
  await expect(visibleContent(page).getByText('Top 10 beekeeping tips for spring').first()).toBeVisible()
  await expect(visibleContent(page).getByText('Secondary commentary; no primary data.').first()).toBeVisible()

  // The acceptance rate is stated on the page, not left to be inferred.
  await expect(visibleContent(page).getByText(/70.0% kept/)).toBeVisible()

  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('the decision filter is URL state, so a filtered ledger is a link', async ({ page }) => {
  await page.goto(`/experts/${SLUG}/sources`)

  await page.getByRole('radio', { name: /Dropped/ }).click()
  await expect(page).toHaveURL(/decision=rejected/, { timeout: 15_000 })
  await expect(visibleContent(page).getByText('Top 10 beekeeping tips for spring').first()).toBeVisible()
  await expect(visibleContent(page).getByText('Varroa destructor and honeybee viral loads')).toHaveCount(0)

  // And it survives a reload, because it is in the URL.
  await page.reload()
  await expect(page.getByRole('radio', { name: /Dropped/ })).toHaveAttribute(
    'aria-checked',
    'true',
  )
})

test('the counts on the filter are true totals, not page counts', async ({ page }) => {
  await page.goto(`/experts/${SLUG}/sources`)
  // 30 considered, 21 kept, 9 dropped — computed over the whole corpus even
  // though the page returns three rows.
  await expect(page.getByRole('radio', { name: 'All 30' })).toBeVisible()
  await expect(page.getByRole('radio', { name: 'Kept 21' })).toBeVisible()
  await expect(page.getByRole('radio', { name: 'Dropped 9' })).toBeVisible()
})

test('a row opens its full record, including the second-read provenance', async ({ page }) => {
  await page.goto(`/experts/${SLUG}/sources`)

  // The reviewed row: a borderline first pass re-read by a stronger model.
  await visibleContent(page).getByText('Amitraz resistance in field populations').first().click()

  const panel = page
    .getByRole('complementary', { name: 'Source' })
    .or(page.getByRole('dialog', { name: 'Source' }))
  await expect(panel.getByText('Reviewed a second time')).toBeVisible({ timeout: 15_000 })
  await expect(panel.getByText(/First pass scored q5.5 r5.5/)).toBeVisible()
  // And the abstract-only warning, which is the first thing a reviewer asks.
  await expect(panel.getByText(/Abstract only/)).toBeVisible()
  // Rubric version lives here rather than in the list.
  await expect(panel.getByText('v5-structured-q5r6')).toBeVisible()
})

test('a duplicate’s zero scores are explained, not left as a verdict', async ({ page }) => {
  await page.goto(`/experts/${SLUG}/sources`)
  // The exclusion summary states it; a reader must not read 0.0 as "bad".
  await expect(visibleContent(page).getByText(/duplicate of https:\/\/example.org\/varroa-cohort/)).toBeVisible()
})

test('the export menu offers CSV and RIS, and the download works', async ({ page }) => {
  await page.goto(`/experts/${SLUG}/sources`)

  await page.getByRole('button', { name: /Export/ }).click()
  await expect(page.getByRole('menuitem', { name: 'CSV' })).toBeVisible()
  const ris = page.getByRole('menuitem', { name: /RIS/ })
  await expect(ris).toBeVisible()
  // RIS is the operationally important one: Zotero, Covidence, EndNote.
  await expect(ris).toContainText('Zotero')

  const download = page.waitForEvent('download')
  await ris.click()
  const file = await download
  // The filename comes from the API's own Content-Disposition.
  expect(file.suggestedFilename()).toMatch(/\.ris$/)
})

test('adding a source by URL queues an ingest and says it is reading', async ({ page }) => {
  await page.goto(`/experts/${SLUG}/sources`)

  await page.getByRole('button', { name: /Add a source/ }).first().click()
  await expect(page.getByRole('heading', { name: 'Add a source' })).toBeVisible()

  await page.getByRole('tab', { name: 'URL' }).click()
  await fillField(page.getByLabel('Page address'), 'https://example.org/a-paper')
  await page.getByRole('button', { name: 'Add', exact: true }).click()

  // Ingest is durable: the dialog closes as soon as the job is queued.
  await expect(visibleContent(page).getByText('Reading a new source')).toBeVisible({ timeout: 15_000 })
})

test('the upload tab refuses an oversized file before sending it', async ({ page }) => {
  await page.goto(`/experts/${SLUG}/sources`)
  await page.getByRole('button', { name: /Add a source/ }).first().click()

  // 21 MB, just over the API's own 20 MB ceiling. Refused client-side so it is
  // not carried across the wire twice to be rejected at the far end.
  await page.setInputFiles('#source-file', {
    name: 'huge.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.alloc(21 * 1024 * 1024),
  })
  await expect(page.getByText(/larger than the 20 MB limit|21.0 MB/)).toBeVisible()
})

test('the ledger is a card list on a phone and a table above it', async ({ page }, testInfo) => {
  await page.goto(`/experts/${SLUG}/sources`)
  const phone = isPhoneProject(testInfo.project.name)

  if (phone) {
    // Cards, with the same fields as the table except rubric and identifiers.
    await expect(page.getByRole('table')).toBeHidden()
    await expect(page.getByRole('button', { name: /Top 10 beekeeping tips/ })).toBeVisible()
  } else {
    await expect(page.getByRole('table')).toBeVisible()
    await expect(page.getByRole('columnheader', { name: /Source/ })).toBeVisible()
  }
  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('a concept link from the overview filters the ledger', async ({ page }) => {
  await page.goto(`/experts/${SLUG}`)
  await page.getByRole('link', { name: 'acaricide resistance' }).click()

  await expect(page).toHaveURL(/concept=acaricide\+resistance|concept=acaricide%20resistance/, {
    timeout: 15_000,
  })
  await expect(visibleContent(page).getByText('acaricide resistance').first()).toBeVisible()
  // Only the source that covers it.
  await expect(visibleContent(page).getByText('Amitraz resistance in field populations').first()).toBeVisible()
  await expect(visibleContent(page).getByText('Top 10 beekeeping tips for spring')).toHaveCount(0)
})

test('the provenance note is surfaced rather than dropped', async ({ page }) => {
  await page.goto(`/experts/${SLUG}/sources`)
  // The fixture's corpus is complete, so the method statement is what shows —
  // the caveat banner is the same component keyed on `provenance.complete`.
  await expect(visibleContent(page).getByText(/Screening is a single language-model pass/)).toBeVisible()
})
