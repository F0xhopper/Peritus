import { cn } from '@/lib/cn'
import type { ConceptDepth, MapKeyConcept } from '@/lib/api/types'

/**
 * How well the sources cover one key concept, as a thin stacked bar.
 *
 * Length is the number of sources that count toward it, against the
 * best-covered key concept in this expert — so the syllabus reads as a profile,
 * and the thin ones are visible without reading a number. The split is depth:
 * sources that *set it out* in the darker ink, sources that *treat* it in the
 * lighter, a mention in the faintest. One ink, not three hues: colour is status
 * here (web/AGENTS.md), and the only status — short of target — is said in
 * words beside the bar, never by the bar alone.
 *
 * Decorative to a screen reader: the row that holds it says the same thing in a
 * sentence (`coverageInWords`).
 */
const SEGMENTS: { depth: ConceptDepth; className: string }[] = [
  { depth: 'sets_out', className: 'bg-fg-2' },
  { depth: 'treats', className: 'bg-fg-3' },
  { depth: 'mentions', className: 'bg-fg-4' },
]

/** The longest bar's length: the most sources any key concept has. */
export function coverageMax(concepts: MapKeyConcept[]): number {
  return Math.max(1, ...concepts.map(coverageTotal))
}

function coverageTotal(concept: MapKeyConcept): number {
  const split = SEGMENTS.reduce((sum, { depth }) => sum + (concept.depth_counts[depth] ?? 0), 0)
  return Math.max(concept.sources, split)
}

export function CoverageBar({
  concept,
  max,
  className,
}: {
  concept: MapKeyConcept
  max: number
  className?: string
}) {
  const total = coverageTotal(concept)
  const split = SEGMENTS.map(({ depth, className: fill }) => ({
    depth,
    fill,
    count: concept.depth_counts[depth] ?? 0,
  })).filter((segment) => segment.count > 0)
  // Sources the API counted without saying how deeply: drawn as "treats", the
  // middle reading, rather than dropped from the length.
  const unsplit = total - split.reduce((sum, segment) => sum + segment.count, 0)

  return (
    <span
      aria-hidden="true"
      className={cn('flex h-1 w-full overflow-hidden rounded-full bg-raised', className)}
    >
      <span className="flex h-full gap-0.5" style={{ width: `${(total / max) * 100}%` }}>
        {split.map((segment) => (
          <span
            key={segment.depth}
            className={cn('h-full rounded-full', segment.fill)}
            style={{ flexGrow: segment.count, flexBasis: 0 }}
          />
        ))}
        {unsplit > 0 && (
          <span
            className="h-full rounded-full bg-fg-3"
            style={{ flexGrow: unsplit, flexBasis: 0 }}
          />
        )}
      </span>
    </span>
  )
}
