import type { CorpusReport } from '@/lib/api/types'
import { formatNumber, formatScore } from '@/lib/format'

/**
 * Why sources were dropped, grouped by reason, from the corpus report's
 * `exclusions.by_reason`.
 *
 * A duplicate is dropped by content fingerprinting before it is judged, so its
 * mean scores come back as 0.0. Printed beside the other reasons they would read
 * as "the worst sources in the corpus"; they are shown as not a verdict instead,
 * matching the row detail's explanation.
 */
export function ExclusionsSection({ exclusions }: { exclusions: CorpusReport['exclusions'] }) {
  const reasons = exclusions.by_reason
  if (reasons.length === 0) return null

  return (
    <section aria-labelledby="exclusions-heading" className="rounded-card bg-panel p-3 md:p-4">
      <h2 id="exclusions-heading" className="text-sm font-medium text-fg">
        Why sources were dropped
      </h2>
      <ul className="mt-2 space-y-2">
        {reasons.map((row) => {
          const duplicate = row.reason.startsWith('duplicate of')
          return (
            <li key={row.reason} className="flex items-baseline justify-between gap-3 text-sm">
              <span className="min-w-0">
                <span className="break-words text-fg-2">{row.reason}</span>
                <span className="block text-xs text-fg-3">
                  {duplicate
                    ? 'Dropped by content fingerprinting — never judged on merit, so no scores'
                    : `Mean quality ${formatScore(row.mean_quality)} · relevance ${formatScore(row.mean_relevance)}`}
                </span>
              </span>
              <span className="shrink-0 font-mono text-fg">{formatNumber(row.count)}</span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
