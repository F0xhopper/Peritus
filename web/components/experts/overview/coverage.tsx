'use client'

import { ArrowRight } from 'lucide-react'
import Link from 'next/link'

import { Section } from '@/components/experts/overview/section'
import { sourceKind } from '@/lib/source-kind'
import type { ExpertWithCatalog } from '@/lib/api/types'

/**
 * What the corpus covers.
 *
 * **Every key concept is a row, and every row opens the sources that cover it.**
 * Real concepts run to 40–120 characters — "Historical development and legacy
 * (medieval scholastic logic, Łukasiewicz's modern reconstruction…)" — so joined
 * by middots into an underlined paragraph they were five to seven lines in which
 * a concept that wrapped was indistinguishable from the next one. As rows they
 * can be counted, scanned and aimed at; two columns from `sm`, where the
 * shortest concepts would otherwise leave half a line of air each.
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
          <ul className="grid grid-cols-1 gap-x-3 sm:grid-cols-2">
            {expert.key_concepts.map((concept) => (
              <li key={concept}>
                <Link
                  href={`/experts/${expert.name}/sources?concept=${encodeURIComponent(concept)}`}
                  className="group flex items-start gap-2 rounded-row px-2 py-1.5 text-sm transition-colors duration-(--dur-1) hover:bg-panel"
                >
                  <span className="min-w-0 flex-1 text-fg-2 group-hover:text-fg">{concept}</span>
                  <ArrowRight
                    aria-hidden="true"
                    className="mt-0.5 size-3.5 shrink-0 text-fg-4 transition-colors duration-(--dur-1) group-hover:text-fg-2"
                  />
                </Link>
              </li>
            ))}
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
