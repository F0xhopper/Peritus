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
 *
 * Which is why `name` and `path` are clamped and stripped before they are
 * logged: unguarded means anyone can post them, and a string that reaches a log
 * unfiltered can carry newlines to forge extra log lines, or ANSI escapes to
 * rewrite a terminal reading them.
 */

/** At most 120 printable characters, no control characters, no line breaks. */
function forLog(value: unknown, fallback = '-'): string {
  if (typeof value !== 'string' || value.length === 0) return fallback
  const clean = value.replace(/[\u0000-\u001f\u007f-\u009f]/g, '')
  return clean.slice(0, 120) || fallback
}

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
        forLog(metric.name),
        metric.value.toFixed(metric.name === 'CLS' ? 4 : 0),
        forLog(metric.rating),
        forLog(metric.path)
      )
    }
  } catch {
    /* a malformed beacon is not worth a status code */
  }
  // 204 so the beacon has nothing to parse and nothing to retry.
  return new NextResponse(null, { status: 204 })
}
