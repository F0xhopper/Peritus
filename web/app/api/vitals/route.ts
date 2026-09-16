import { NextResponse } from 'next/server'

/**
 * Where `useReportWebVitals` posts LCP, INP and CLS.
 *
 * Server-side logging only, so a regression on real phones is visible after
 * launch rather than guessed at from a lab run. Nothing is stored and nothing
 * is forwarded to the API: this is one log line per metric, and it must never
 * be able to fail a page.
 *
 * Deliberately not origin-guarded. `navigator.sendBeacon` fires during page
 * unload, when a 403 would be invisible and the measurement simply lost — and
 * the worst a forged beacon achieves is a wrong number in a log.
 */
export async function POST(request: Request) {
  try {
    const metric = (await request.json()) as {
      name?: string
      value?: number
      rating?: string
      path?: string
    }
    if (typeof metric.name === 'string' && typeof metric.value === 'number') {
      console.info(
        '[vitals] %s=%s rating=%s path=%s',
        metric.name,
        metric.value.toFixed(metric.name === 'CLS' ? 4 : 0),
        metric.rating ?? '-',
        metric.path ?? '-'
      )
    }
  } catch {
    /* a malformed beacon is not worth a status code */
  }
  // 204 so the beacon has nothing to parse and nothing to retry.
  return new NextResponse(null, { status: 204 })
}
