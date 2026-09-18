import { chromium, devices } from '@playwright/test'
const [scenario, device, path, name, action] = process.argv.slice(2)
const browser = await chromium.launch()
const opts =
  device === 'desktop'
    ? { viewport: { width: 1440, height: 900 } }
    : device === 'reduced'
      ? { viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' }
      : devices[device]
const context = await browser.newContext({ ...opts, colorScheme: 'dark' })
await context.addCookies([
  {
    name: 'peritus_access_token',
    value: 'mock-access',
    url: 'http://127.0.0.1:3100',
    httpOnly: true,
    sameSite: 'Lax',
  },
  {
    name: 'peritus_refresh_token',
    value: 'mock-refresh',
    url: 'http://127.0.0.1:3100',
    httpOnly: true,
    sameSite: 'Lax',
  },
])
const page = await context.newPage()
page.on('pageerror', (e) => console.log('pageerror:', e.message))
page.on('console', (m) => {
  if (m.type() === 'error') console.log('console:', m.text())
})
await fetch('http://127.0.0.1:8787/__reset', { method: 'POST' })
await fetch('http://127.0.0.1:8787/__scenario', {
  method: 'POST',
  body: JSON.stringify({ scenario }),
})
await page.goto('http://127.0.0.1:3100' + path)
await page.waitForTimeout(2500)
if (action === 'hover') {
  await page.mouse.move(800, 450)
  await page.waitForTimeout(800)
}
if (action === 'tapnode') {
  await page.getByLabel('Find a source or concept').fill('amitraz')
  await page.waitForTimeout(300)
  await page.keyboard.press('Enter')
  await page.waitForTimeout(1800)
}
await page.screenshot({
  path:
    '/private/tmp/claude-501/-Users-edenfoxphillips-Projects-Peritus/48c625a0-8fc1-4a1f-bb60-c9f48d2e3893/scratchpad/' +
    name +
    '.png',
})
console.log(page.url())
await browser.close()
