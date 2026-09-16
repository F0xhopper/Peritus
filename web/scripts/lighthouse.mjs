/**
 * The Lighthouse run, both halves of it.
 *
 * Two configs rather than one because of the session: the public pages must be
 * audited *without* cookies, and `/login` with a valid session redirects to
 * `/experts` — Lighthouse would then audit that page twice under the wrong
 * name. `lighthouserc.public.json` covers `/` and `/login`; the app half sends
 * the mock API's session cookies and covers `/experts` and a seeded chat.
 *
 * The mock API is started here rather than by `lhci`, which can start exactly
 * one server. It is the same `e2e/mock-api/server.mjs` the Playwright suite
 * uses, so the audited pages hold the same fixtures — a real build costs money
 * and takes minutes, and a page audited against an empty API is not the page.
 *
 * The budgets are web-design.md §9: LCP under 2.5s, CLS under 0.1, and TBT
 * under 200ms as the lab stand-in for INP, which cannot be measured without a
 * real interaction. They are asserted on the median of three runs, because a
 * shared CI runner's first run is frequently its slowest.
 */
import { spawn } from 'node:child_process'

// Fetched on demand rather than installed. `@lhci/cli` drags in Lighthouse,
// puppeteer-core and extract-zip, which between them account for every one of
// the twelve advisories `npm audit` reports on this project — all of them in a
// tool that never ships and only ever runs against 127.0.0.1. Keeping it out of
// devDependencies means `npm ci` installs a clean tree and the audit gate in CI
// is meaningful; the version here is the pin.
const LHCI = '@lhci/cli@0.15.1'

const MOCK_API_PORT = process.env.MOCK_API_PORT ?? '8788'
const PORT = '3200'
const BASE_URL = `http://127.0.0.1:${PORT}`

const env = {
  ...process.env,
  MOCK_API_PORT,
  PERITUS_API_URL: `http://127.0.0.1:${MOCK_API_PORT}`,
  NEXT_PUBLIC_APP_URL: BASE_URL,
  // The audit is served over plain http on loopback, so the session cookies
  // cannot carry `Secure` or the app would never see them.
  PERITUS_ALLOW_INSECURE_COOKIES: 'true',
}

const mockApi = spawn('node', ['e2e/mock-api/server.mjs'], { env, stdio: 'inherit' })
const stopMockApi = () => mockApi.kill('SIGTERM')
process.on('exit', stopMockApi)
process.on('SIGINT', () => process.exit(130))

await waitFor(`http://127.0.0.1:${MOCK_API_PORT}/auth/status`)

let failed = false
for (const config of ['lighthouserc.public.json', 'lighthouserc.app.json']) {
  const code = await run('npx', ['--yes', LHCI, 'autorun', `--config=${config}`])
  if (code !== 0) failed = true
}

stopMockApi()
process.exit(failed ? 1 : 0)

function run(command, args) {
  return new Promise((resolve) => {
    const child = spawn(command, args, { env, stdio: 'inherit' })
    child.on('exit', (code) => resolve(code ?? 1))
  })
}

async function waitFor(url, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // Not up yet.
    }
    if (Date.now() > deadline) throw new Error(`${url} never became ready`)
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
}
