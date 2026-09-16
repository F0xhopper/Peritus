'use client'

import Link from 'next/link'

import { Section } from '@/components/experts/overview/section'
import { sourceKind } from '@/lib/source-kind'
import type { ExpertWithCatalog } from '@/lib/api/types'

/**
 * What the corpus covers.
 *
 * **Every key concept links to the sources that cover it.** The concepts are
 * what the search set out to find; a list of words with nothing behind them
 * would be a claim rather than evidence.
 */
export function OverviewCoverage({ expert }: { expert: ExpertWithCatalog }) {
  return (
    <>
      {expert.persona_bio && (
        <Section title="About">
          <p>{expert.persona_bio}</p>
        </Section>
      )}

      {expert.key_concepts.length > 0 && (
        <Section title="Key concepts">
          <p className="leading-relaxed">
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
