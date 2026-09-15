'use client'

import { useReportWebVitals } from 'next/web-vitals'

/**
 * Post the field measurements to `/api/vitals` for server-side logging.
 *
 * A lab run on a developer's laptop says nothing about a mid-range phone on a
 * real network, which is where the budgets in web-design.md §9 actually have to
 * hold. `sendBeacon` so the metric survives the page unload that usually
 * triggers the final CLS report.
 */
const REPORTED = new Set(['LCP', 'INP', 'CLS'])

export function WebVitals() {
  useReportWebVitals((metric) => {
    if (!REPORTED.has(metric.name)) return
    const body = JSON.stringify({
      name: metric.name,
      value: metric.value,
      rating: metric.rating,
      path: window.location.pathname,
    })
    if (navigator.sendBeacon) {
      navigator.sendBeacon('/api/vitals', new Blob([body], { type: 'application/json' }))
    } else {
      void fetch('/api/vitals', { method: 'POST', body, keepalive: true })
    }
  })
  return null
}
