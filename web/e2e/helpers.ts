import { expect, type Locator, type Page } from '@playwright/test'

/**
 * Shared assertions.
 *
 * The two that run on every route in every project — no horizontal overflow and
 * 44px tap targets — are the checklist items from web-implementation.md §13
 * that are easiest to regress and hardest to notice: a single `min-w` or a
 * 32px icon button on a phone breaks them, and neither shows up in a
 * screenshot of a desktop viewport.
 */

const MOCK_API = `http://127.0.0.1:${process.env.MOCK_API_PORT || 8787}`

/**
 * Put the mock API into a named scenario before acting.
 *
 * `slug` scopes it. Worth passing for anything stream-related: Home tails a
 * build of its own for the seeded in-progress expert, so an unscoped scenario
 * can fire on that stream instead of the one under test.
 */
export async function useScenario(page: Page, scenario: string, slug?: string) {
  const response = await page.request.post(`${MOCK_API}/__scenario`, {
    data: { scenario, slug: slug ?? null },
  })
  expect(response.ok()).toBe(true)
}

/** Reset the mock API's state, so tests do not inherit each other's experts. */
export async function resetApi(page: Page) {
  const response = await page.request.post(`${MOCK_API}/__reset`)
  expect(response.ok()).toBe(true)
}

/**
 * Sign in by writing the session cookies directly.
 *
 * The OTP and Google flows have their own tests; every other test needs a
 * session, not a sign-in, and going through the form thirty times would add a
 * minute per project for no coverage.
 */
export async function signIn(page: Page) {
  await page.context().addCookies([
    {
      name: 'peritus_access_token',
      value: 'mock-access',
      url: baseUrl(page),
      httpOnly: true,
      sameSite: 'Lax',
    },
    {
      name: 'peritus_refresh_token',
      value: 'mock-refresh',
      url: baseUrl(page),
      httpOnly: true,
      sameSite: 'Lax',
    },
  ])
}

/** The app's own origin, which is where the session cookies belong. */
function baseUrl(_page: Page): string {
  return `http://127.0.0.1:${process.env.PORT || 3100}`
}

/**
 * Nothing scrolls the page sideways.
 *
 * Tables, the build page's stage strip and the graph canvas are allowed to,
 * each inside its own container — so the assertion is on `<html>` and on the
 * app grid, never on their descendants.
 */
export async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    const root = document.documentElement
    const results: { where: string; scrollWidth: number; clientWidth: number }[] = []
    if (root.scrollWidth > root.clientWidth + 1) {
      results.push({ where: 'html', scrollWidth: root.scrollWidth, clientWidth: root.clientWidth })
    }
    const grid = document.querySelector('body > div.grid, main')
    if (grid && grid.scrollWidth > grid.clientWidth + 1) {
      results.push({
        where: 'app grid',
        scrollWidth: grid.scrollWidth,
        clientWidth: grid.clientWidth,
      })
    }
    return results
  })
  expect(overflow, `horizontal overflow: ${JSON.stringify(overflow)}`).toEqual([])
}

/**
 * Every visible control is at least 44px tall under a coarse pointer.
 *
 * Checked only in the touch projects, because `--row-h` is 32px with a fine
 * pointer by design. Elements smaller than 8px in either axis are skipped as
 * decorative (a status dot inside a row is not a tap target).
 */
export async function expectTapTargets(page: Page) {
  const tooSmall = await page.evaluate(() => {
    const selector = 'button, a[href], [role="button"], input:not([type="range"]), select'
    const failures: { text: string; height: number }[] = []
    for (const element of document.querySelectorAll(selector)) {
      const rect = element.getBoundingClientRect()
      // Off-screen, hidden, or decorative.
      if (rect.width < 8 || rect.height < 8) continue
      if (rect.bottom < 0 || rect.top > window.innerHeight) continue
      const style = getComputedStyle(element)
      if (style.visibility === 'hidden' || style.display === 'none') continue
      // A link inside a paragraph of prose is not a tap target in the sense
      // this rule means, and forcing it to 44px would wreck the typography.
      if (element.closest('p, li, blockquote, summary, dd, .prose')) continue
      // Half a pixel of tolerance: an iPad's viewport is not an integer number
      // of CSS pixels, so a control that is exactly `--row-h` tall measures
      // 43.99997 there. Rounding noise is not a design failure — anything a
      // full pixel short is.
      if (rect.height < 43.5) {
        failures.push({
          text: (element.textContent ?? '').trim().slice(0, 40),
          height: rect.height,
        })
      }
    }
    return failures
  })
  expect(tooSmall, `tap targets under 44px: ${JSON.stringify(tooSmall)}`).toEqual([])
}

/** Both assertions, for the routes every project walks. */
export async function expectResponsive(page: Page, touch: boolean) {
  await expectNoHorizontalOverflow(page)
  if (touch) await expectTapTargets(page)
}

/**
 * The centre column.
 *
 * Content assertions go through this rather than `page`, because the shell
 * keeps **both forms of every region in the HTML** and hides one with
 * `hidden md:flex` — that is what makes the server render correct at every
 * width. An unscoped `getByText` therefore matches the hidden rail or sidebar
 * copy on a phone and fails with "received: hidden", which says nothing about
 * the page under test.
 */
export function content(page: Page) {
  return page.getByRole('main')
}

/**
 * Visible matches only, for a selector that legitimately appears more than once
 * across the tiers — an avatar in both the rail and a card, a ledger row in
 * both the table and the card list, a persona name in the shell and the page.
 */
export function visible(page: Page, selector: string) {
  return page.locator(selector).filter({ visible: true })
}

/**
 * Text in the centre column, in whichever form is showing.
 *
 * Most content is in the HTML twice at once — a table *and* a card list, an
 * inline button *and* a sticky-footer one — because the server render has to be
 * right at every width. Scoping to a visible `main` is not enough: both copies
 * are inside it, and the hidden one is what `.first()` finds. The filter has to
 * be on the match itself.
 */
export function visibleContent(page: Page) {
  const main = page.getByRole('main')
  return {
    getByText: (text: Parameters<typeof main.getByText>[0]) =>
      main.getByText(text).filter({ visible: true }),
  }
}

/**
 * Wait until React has hydrated the page.
 *
 * The reason this is needed at all: `fill()` sets the DOM value and dispatches
 * one `input` event. Do that a millisecond before hydration and the event has
 * no listener — React then hydrates over a field whose DOM value it does not
 * know about, and **does not reset it**, so the field *looks* filled while the
 * component's state is still empty. Everything downstream (a suggestion list,
 * an enabled submit button) is simply absent, and the failure points at the
 * wrong thing entirely.
 *
 * React's own hydration marker is the cleanest signal available from outside:
 * `hydrateRoot` stamps a `__reactContainer$…` key on the container. It is an
 * internal, so this degrades to "carry on" rather than failing if a future
 * React stops writing it — the assertions that follow are what actually fail.
 */
export async function waitForHydration(page: Page) {
  await page
    .waitForFunction(
      () =>
        [document, document.documentElement, document.body].some((node) =>
          Object.keys(node).some((key) => key.startsWith('__react'))
        ),
      undefined,
      { timeout: 10_000 }
    )
    .catch(() => {})
}

/**
 * Wait for hydration, click, fill — and check the value survived.
 *
 * `fill()` alone is enough in Chromium, but on WebKit a fill into a field that
 * has never been focused — one that has only just hydrated — is sometimes
 * dropped, and the symptom is a submit button that never enables. Clicking
 * first is also what a person actually does, so the test matches the
 * interaction it claims to be checking.
 *
 * **And then it is checked.** `waitForHydration` waits for React to attach
 * *somewhere* in the document; React 19 hydrates island by island, so a field
 * can still be filled a moment before its own form comes alive — and hydrating
 * over a controlled input throws the typed value away. The failure surfaces far
 * from its cause, as a disabled Send button that Playwright waits sixty seconds
 * for, which is exactly what CI kept seeing on the slower projects. Asserting
 * the value stuck, and typing it again if it did not, makes the race visible
 * where it happens and survivable.
 */
export async function fillField(field: Locator, value: string) {
  await waitForHydration(field.page())
  await field.click()
  await field.fill(value)
  try {
    await expect(field).toHaveValue(value, { timeout: 2_000 })
  } catch {
    await field.fill(value)
    await expect(field).toHaveValue(value, { timeout: 5_000 })
  }
}

/**
 * Type a question into the chat composer and send it.
 *
 * Send is disabled until the composer's *React state* holds a question, and
 * that is the thing a too-early fill loses: `fillField` can see the text in the
 * DOM and the component still be a hydration behind. Waiting on the button —
 * and typing again if it never enables — checks the only state that matters,
 * and it is why this is a helper rather than three copies of the same two
 * lines. CI's slower device profiles hit this where a local run does not.
 */
export async function askQuestion(page: Page, question: string) {
  const field = page.getByLabel('Your question')
  const send = page.getByRole('button', { name: 'Send' })
  await fillField(field, question)
  try {
    await expect(send).toBeEnabled({ timeout: 2_000 })
  } catch {
    await field.fill(question)
    await expect(send).toBeEnabled({ timeout: 10_000 })
  }
  await send.click()
}

/** True for the projects that emulate a touch device. */
export function isTouchProject(projectName: string): boolean {
  return ['iphone', 'pixel', 'ipad-portrait', 'ipad-landscape'].includes(projectName)
}

/** True below the `md` tier, where the nav drawer is the only navigation. */
export function isPhoneProject(projectName: string): boolean {
  return ['iphone', 'pixel'].includes(projectName)
}

/**
 * The longest frame the browser painted during `action`.
 *
 * Used on the throttled projects to hold the "no frame over 50ms" budget while
 * a 3,000-row log scrolls or a 2,000-token answer streams. `requestAnimationFrame`
 * deltas are the only measure available from inside the page that reflects what
 * the user actually sees.
 */
export async function longestFrame(page: Page, action: () => Promise<void>): Promise<number> {
  await page.evaluate(() => {
    const store = { worst: 0, last: performance.now(), running: true }
    ;(window as unknown as { __frames: typeof store }).__frames = store
    const tick = () => {
      const now = performance.now()
      store.worst = Math.max(store.worst, now - store.last)
      store.last = now
      if (store.running) requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })

  await action()

  return page.evaluate(() => {
    const store = (window as unknown as { __frames: { worst: number; running: boolean } }).__frames
    store.running = false
    return store.worst
  })
}
