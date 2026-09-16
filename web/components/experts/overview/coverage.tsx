'use client'

import Link from 'next/link'

import { Section } from '@/components/experts/overview/section'
import { formatPercent, plural } from '@/lib/format'
import { sourceKind } from '@/lib/source-kind'
import type { CorpusReport, ExpertWithCatalog } from '@/lib/api/types'

/**
 * What the corpus covers, and how it came to be the corpus.
 *
 * This is the part of the Overview that makes the product's claim checkable, so
 * two things here are not cosmetic:
 *
 * **Every key concept links to the sources that cover it.** The concepts are
 * what the search set out to find; a list of words with nothing behind them
 * would be a claim rather than evidence.
 *
 * **The dropped sources are linked as prominently as the kept ones.** "34 kept
 * of 210 screened" is only meaningful if the other 176 are one click away with
 * the reason for each — they are the evidence that the rest were chosen.
 */
export function OverviewCoverage({
  expert,
  report,
}: {
  expert: ExpertWithCatalog
  report: CorpusReport | null
}) {
  return (
    <>
      {expert.persona_bio && (
        <Section title="About">
          <p>{expert.persona_bio}</p>
        </Section>
      )}

      {expert.key_concepts.length > 0 && (
        <Section title="Key concepts">
          <p className="text-fg-3">
            What the search set out to cover. Each one opens the sources that cover it.
          </p>
          <p className="mt-2 leading-relaxed">
            {expert.key_concepts.map((concept, index) => (
              <span key={concept}>
                {index > 0 && <span className="text-fg-3"> · </span>}
                <Link
                  href={`/experts/${expert.name}/sources?concept=${encodeURIComponent(concept)}`}
                  className="text-fg underline decoration-fg-4 underline-offset-2 hover:decoration-fg-2"
                >
                  {concept}
                </Link>
              </span>
            ))}
          </p>
        </Section>
      )}

      {report && (
        <Section title="How these sources were chosen">
          <p>{report.method_statement}</p>
          <ul className="mt-3 space-y-1.5">
            <li>
              <span className="font-medium text-fg">Kept.</span> {report.totals.accepted} of{' '}
              {report.totals.considered} sources screened (
              {formatPercent(report.totals.acceptance_rate, 1)}). The {report.totals.rejected}{' '}
              dropped are on the{' '}
              <Link
                href={`/experts/${expert.name}/sources?decision=rejected`}
                className="text-fg underline underline-offset-2"
              >
                Sources page
              </Link>{' '}
              with the reason for each — they are the evidence that the rest were chosen.
            </li>
            <li>
              <span className="font-medium text-fg">Screening rules.</span> A source scored below{' '}
              {report.thresholds.quality_min} for quality or {report.thresholds.relevance_min} for
              relevance is dropped, with the reason recorded. Rules version{' '}
              <span className="font-mono text-xs">{report.thresholds.current_rubric_version}</span>.
            </li>
            {report.by_search.distinct_searches > 0 && (
              <li>
                <span className="font-medium text-fg">Searches.</span>{' '}
                {plural(report.by_search.distinct_searches, 'search', 'searches')} found these
                sources, including any follow-up searches for concepts that had no source yet.
              </li>
            )}
            {!report.provenance.complete && (
              <li>
                <span className="font-medium text-warn">Some records are incomplete.</span>{' '}
                {report.provenance.note}
              </li>
            )}
          </ul>
        </Section>
      )}

      {Object.keys(expert.source_type_counts).length > 0 && (
        <Section title="Kinds of source">
          <p className="leading-relaxed">
            {kindCounts(expert.source_type_counts).map(([kind, count], index) => (
              <span key={kind}>
                {index > 0 && <span className="text-fg-3"> · </span>}
                <span className="text-fg-2">{kind}</span> <span className="text-fg-3">{count}</span>
              </span>
            ))}
          </p>
        </Section>
      )}
    </>
  )
}

/** Source-type counts as display kinds, largest first. */
function kindCounts(counts: Record<string, number>): [string, number][] {
  const merged = new Map<string, number>()
  for (const [type, count] of Object.entries(counts)) {
    const kind = sourceKind(type)
    merged.set(kind, (merged.get(kind) ?? 0) + count)
  }
  return [...merged.entries()].sort((a, b) => b[1] - a[1])
}
