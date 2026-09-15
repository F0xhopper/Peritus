import { expect, test } from '@playwright/test'

import { content, expectResponsive, isTouchProject, resetApi, signIn, visible } from './helpers'

/**
 * The expert's avatar.
 *
 * Three properties matter and none of them is visual. The identity is **never
 * uploaded** — it is either a drawing generated from a stored recipe or a
 * licensed picture the server found, fetched and stored itself, so a user
 * cannot put an arbitrary image beside answers that cite real sources. It is
 * **the same everywhere**, because the server decides it rather than each
 * client guessing. And the found picture is **served same-origin under a
 * versioned URL**, so no third-party origin appears in anyone's browser.
 */

const SLUG = 'varroa-mite-control-in-temperate-beekeeping'
/** The seeded expert that arrived with a found picture of its subject. */
const PICTURE_SLUG = 'stoic-philosophy'

test.beforeEach(async ({ page }) => {
  await resetApi(page)
  await signIn(page)
})

test('an expert is drawn the same way on every surface', async ({ page }) => {
  await page.goto('/experts')

  // The derived default: initials from the persona name, with the honorific
  // stripped. Visible-only, because the rail and the sidebar are both in the
  // HTML at every width and hidden by CSS.
  await expect(visible(page, '[data-avatar]').first()).toBeVisible()

  // "Dr. Marta Belen" → MB, not DR.
  await expect(visible(page, '[data-avatar]').filter({ hasText: 'MB' }).first()).toBeVisible()
  await expect(page.locator('[data-avatar]').filter({ hasText: 'DR' })).toHaveCount(0)

  // And none of them carries a colour of its own: there are no per-expert hues.
  const hues = await page.locator('[data-avatar]').evaluateAll((nodes) =>
    nodes.map((node) => (node as HTMLElement).style.getPropertyValue('--expert-h').trim()),
  )
  expect(hues.length).toBeGreaterThan(1)
  expect(new Set(hues)).toEqual(new Set(['']))
})

test('the picker offers styles, not colours', async ({ page }) => {
  /**
   * There are no per-expert colours. The picker used to offer twelve hues and a
   * "Next colour" button; an expert is now told apart by its picture or drawing
   * alone, and colour in the product means status.
   */
  await page.goto(`/experts/${SLUG}`)
  await page.getByRole('button', { name: 'Change avatar' }).click()
  await expect(page.getByRole('heading', { name: 'Avatar' })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Shapes/ })).toBeVisible()
  await expect(page.getByText('Colour', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Next colour|^Hue / })).toHaveCount(0)
})

test('the avatar can be changed, and the choice persists', async ({ page }, testInfo) => {
  await page.goto(`/experts/${SLUG}`)

  await page.getByRole('button', { name: 'Change avatar' }).click()
  await expect(page.getByRole('heading', { name: 'Avatar' })).toBeVisible()
  // The dialog says what it is: generated, never uploaded.
  await expect(page.getByText(/Generated, never uploaded/)).toBeVisible()

  // Pick a generated picture instead of the monogram.
  await page.getByRole('button', { name: /^Shapes/ }).click()
  await page.getByRole('button', { name: 'Save' }).click()

  await expect(page.getByText('Avatar updated')).toBeVisible({ timeout: 15_000 })

  // It survives a reload, because the server stores the recipe.
  await page.reload()
  const trigger = page.getByRole('button', { name: 'Change avatar' })
  await expect(trigger.locator('[data-avatar="shapes"]')).toBeVisible({ timeout: 15_000 })
  // And it is the same picture in the rail and the sidebar, not only here.
  expect(await page.locator('[data-avatar="shapes"]').count()).toBeGreaterThan(1)

  await expectResponsive(page, isTouchProject(testInfo.project.name))
})

test('every offered style renders, and none of them is a face', async ({ page }) => {
  await page.goto(`/experts/${SLUG}`)
  await page.getByRole('button', { name: 'Change avatar' }).click()

  for (const style of ['Monogram', 'Shapes', 'Glass', 'Rings', 'Identicon', 'Icon']) {
    const option = page.getByRole('button', { name: new RegExp(`^${style}`) })
    await expect(option, style).toBeVisible()
    // Each option previews itself with the live recipe.
    await expect(option.locator('[data-avatar]'), style).toBeVisible()
  }
  // The face generators are not offered at all, here or server-side.
  for (const face of ['Avataaars', 'Lorelei', 'Personas', 'Thumbprint']) {
    await expect(page.getByRole('button', { name: new RegExp(face, 'i') })).toHaveCount(0)
  }
})

test('reset returns the expert to its derived identity', async ({ page }) => {
  await page.goto(`/experts/${SLUG}`)

  // Pin something first, so there is something to reset.
  await page.getByRole('button', { name: 'Change avatar' }).click()
  await page.getByRole('button', { name: /^Rings/ }).click()
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByText('Avatar updated')).toBeVisible({ timeout: 15_000 })
  await page.reload()
  const trigger = page.getByRole('button', { name: 'Change avatar' })
  await expect(trigger.locator('[data-avatar="rings"]')).toBeVisible({ timeout: 15_000 })

  // Then reset.
  await page.getByRole('button', { name: 'Change avatar' }).click()
  await page.getByRole('button', { name: 'Reset' }).click()
  await expect(page.getByText(/reset to the generated default/)).toBeVisible({ timeout: 15_000 })

  await page.reload()
  await expect(page.locator('[data-avatar="rings"]')).toHaveCount(0)
  await expect(trigger.locator('[data-avatar="sigil"]')).toBeVisible({ timeout: 15_000 })
})

test('shuffling changes the picture without changing the expert', async ({ page }) => {
  await page.goto(`/experts/${SLUG}`)
  await page.getByRole('button', { name: 'Change avatar' }).click()
  await page.getByRole('button', { name: /^Identicon/ }).click()

  const preview = page.getByRole('dialog').locator('[data-avatar="identicon"]').first()
  const before = await preview.innerHTML()
  await page.getByRole('button', { name: 'Shuffle' }).click()
  // A new seed means a different drawing; nothing else about the expert moves.
  await expect
    .poll(async () => (await preview.innerHTML()) !== before, { timeout: 5_000 })
    .toBe(true)
})

test('the avatar can also be changed from expert settings', async ({ page }) => {
  await page.goto(`/experts/${SLUG}/settings`)
  await expect(page.getByRole('heading', { name: 'Avatar' })).toBeVisible()
  // And it says which state it is in, which is the thing a user needs to know
  // before a rebuild renames the expert.
  await expect(page.getByText(/Derived from the persona name/)).toBeVisible()

  await page.getByRole('button', { name: 'Change avatar' }).click()
  await page.getByRole('button', { name: /^Glass/ }).click()
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByText('Avatar updated')).toBeVisible({ timeout: 15_000 })

  await page.reload()
  await expect(content(page).getByText(/Pinned — style "glass"/)).toBeVisible({ timeout: 15_000 })
})


/**
 * The found picture.
 *
 * The seeded expert has one and the mid-build one does not, so both branches of
 * the three-level precedence — recipe, picture, monogram — are on screen in the
 * same run.
 */
test('an expert with a found picture shows it, everywhere, from our own origin', async ({
  page,
}) => {
  await page.goto(`/experts/${PICTURE_SLUG}`)

  const tiles = page.locator('[data-avatar="picture"]')
  // Every surface that draws this expert: the rail, the sidebar header, the
  // breadcrumb and the Overview header — some of them hidden by CSS at this
  // width, all of them in the HTML.
  expect(await tiles.count()).toBeGreaterThan(1)

  for (const src of await tiles.locator('img').evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute('src')),
  )) {
    // Same-origin, and carrying the version that makes the immutable cache safe.
    expect(src).toMatch(/^\/api\/experts\/[^/]+\/picture\?v=[0-9a-f]+$/)
  }

  // The one on screen actually loaded — a broken `<img>` is still an `<img>`,
  // and the hidden copies are `loading="lazy"` so they never fetch at all.
  const onScreen = visible(page, '[data-avatar="picture"]').first().locator('img')
  await expect
    .poll(
      () =>
        onScreen.evaluate(
          (node) =>
            (node as HTMLImageElement).complete && (node as HTMLImageElement).naturalWidth > 0,
        ),
      { timeout: 10_000 },
    )
    .toBe(true)
})

test('the picture is credited where it is the identity of the page', async ({ page }) => {
  await page.goto(`/experts/${PICTURE_SLUG}`)

  // CC BY-SA obliges attribution, so the credit names the work, the artist and
  // the licence, and links out to where the licence is actually stated.
  const credit = content(page).getByText(/^Picture:/).first()
  await expect(credit).toBeVisible()
  await expect(credit.getByRole('link', { name: 'Varroa destructor' })).toHaveAttribute(
    'href',
    /commons\.wikimedia\.org/,
  )
  await expect(credit).toContainText('Gilles San Martin')
  await expect(credit.getByRole('link', { name: 'CC BY-SA 2.0' })).toBeVisible()

  // And not in the rail, where a 20px tile is a navigational mark.
  await expect(page.locator('nav').getByText(/^Picture:/)).toHaveCount(0)
})

test('removing the picture returns the expert to its monogram', async ({ page }) => {
  await page.goto(`/experts/${PICTURE_SLUG}`)
  await page.getByRole('button', { name: 'Change avatar' }).click()

  await expect(page.getByRole('button', { name: /^Picture — Varroa destructor/ })).toBeVisible()
  await page.getByRole('button', { name: 'Remove' }).click()
  await expect(page.getByText('Picture removed')).toBeVisible({ timeout: 15_000 })

  await page.reload()
  await expect(page.locator('[data-avatar="picture"]')).toHaveCount(0)
  const trigger = page.getByRole('button', { name: 'Change avatar' })
  await expect(trigger.locator('[data-avatar="sigil"]')).toBeVisible({ timeout: 15_000 })
  // The credit goes with it — there is nothing left to credit.
  await expect(content(page).getByText(/^Picture:/)).toHaveCount(0)
})

test('find another replaces the picture without touching the recipe', async ({ page }) => {
  await page.goto(`/experts/${PICTURE_SLUG}`)
  await page.getByRole('button', { name: 'Change avatar' }).click()
  await page.getByRole('button', { name: 'Find another' }).click()

  await expect(page.getByText('Found another picture')).toBeVisible({ timeout: 15_000 })
  await page.reload()
  // Still a picture, and still derived — finding one is not a choice the owner
  // made, so Reset stays disabled.
  await expect(
    page.getByRole('button', { name: 'Change avatar' }).locator('[data-avatar="picture"]'),
  ).toBeVisible({ timeout: 15_000 })
  await page.getByRole('button', { name: 'Change avatar' }).click()
  await expect(page.getByRole('button', { name: 'Reset' })).toBeDisabled()
})

test('a pinned drawing overrides the picture, and Reset brings it back', async ({ page }) => {
  await page.goto(`/experts/${PICTURE_SLUG}`)

  await page.getByRole('button', { name: 'Change avatar' }).click()
  await page.getByRole('button', { name: /^Rings/ }).click()
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByText('Avatar updated')).toBeVisible({ timeout: 15_000 })

  await page.reload()
  await expect(page.locator('[data-avatar="picture"]')).toHaveCount(0)
  const trigger = page.getByRole('button', { name: 'Change avatar' })
  await expect(trigger.locator('[data-avatar="rings"]')).toBeVisible({ timeout: 15_000 })

  // Reset is the way back, and it lands on the picture rather than skipping
  // past it to the monogram.
  await page.getByRole('button', { name: 'Change avatar' }).click()
  await page.getByRole('button', { name: 'Reset' }).click()
  await expect(page.getByText(/reset to the generated default/)).toBeVisible({ timeout: 15_000 })

  await page.reload()
  await expect(
    page.getByRole('button', { name: 'Change avatar' }).locator('[data-avatar="picture"]'),
  ).toBeVisible({ timeout: 15_000 })
})
