'use client'

import { ChevronRight } from 'lucide-react'
import { useId, useMemo, useState } from 'react'

import { CoverageBar, coverageMax } from '@/components/knowledge/coverage-bar'
import { KindIcon, MarkGlyph, tierMark } from '@/components/knowledge/kind-icon'
import { coverageInWords } from '@/components/knowledge/panels'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import {
  TIERS,
  kindCounts,
  knowledgeStats,
  tierCounts,
  type SourceFilter,
} from '@/lib/brain/overview'
import type { BrainSelection } from '@/lib/brain/selection'
import type { MapKeyConcept, MapResponse } from '@/lib/api/types'

/** What resting on a row of the Overview lights, before anything is chosen. */
export type OverviewPreview = BrainSelection | { kind: 'filter'; filter: SourceFilter }

/**
 * What this expert knows, before anything is selected.
 *
 * The Knowledge page used to open on a picture and a search box: the picture
 * said how much there was and nothing about what, and every fact a reader comes
 * for — how much was read, of what kind, how well it covers the syllabus, what
 * the plan wanted and never found — was one click into a panel, per item. This
 * is those facts in one place, and **every row of it is a control**: a key
 * concept or a missing text selects (the same selection as the Map, the Flow
 * and the List), a kind or a tier filters, and resting on any of them lights
 * what it would touch.
 *
 * It stands where a selection's panel opens — the right-hand column from `lg`,
 * and folded above the List below it, where there is no column. Both forms are
 * in the HTML and CSS picks one (web/AGENTS.md: `useMediaQuery` may not decide
 * what renders), which is why `compact` is a prop and not a query.
 */
export function KnowledgeOverview({
  map,
  selection,
  filter,
  compact = false,
  onSelect,
  onFilter,
  onPreview,
  className,
}: {
  map: MapResponse
  selection: BrainSelection | null
  filter: SourceFilter
  /** Stacked above the List: sections start folded, so the sources stay in reach. */
  compact?: boolean
  onSelect: (selection: BrainSelection) => void
  onFilter: (filter: SourceFilter) => void
  onPreview?: (preview: OverviewPreview | null) => void
  className?: string
}) {
  const stats = useMemo(() => knowledgeStats(map), [map])
  const kinds = useMemo(() => kindCounts(map), [map])
  const tiers = useMemo(() => tierCounts(map), [map])
  const max = useMemo(() => coverageMax(map.syllabus.key_concepts), [map])
  const groups = useMemo(() => syllabusGroups(map), [map])

  const preview = (next: OverviewPreview | null) => ({
    onPointerEnter: (event: React.PointerEvent) => {
      if (event.pointerType === 'mouse') onPreview?.(next)
    },
    onPointerLeave: () => onPreview?.(null),
    onFocus: () => onPreview?.(next),
    onBlur: () => onPreview?.(null),
  })

  const short = stats.keyConcepts - stats.met
  const kindMax = Math.max(1, ...kinds.map((kind) => kind.count))
  const tierMax = Math.max(1, ...TIERS.map((tier) => tiers[tier.id]))

  return (
    <section
      aria-label="Overview"
      // Folded, the sections are three rows of a list, not three blocks.
      className={cn('text-sm', compact ? 'space-y-1' : 'space-y-4', className)}
    >
      <dl className={cn('grid gap-1.5', compact ? 'grid-cols-4 pb-1.5' : 'grid-cols-2')}>
        <Stat label="Sources" value={stats.sources} compact={compact} />
        <Stat label="Passages" value={stats.passages} compact={compact} />
        <Stat label="Concepts" value={stats.concepts} compact={compact} />
        <Stat label="Claims" value={stats.claims} compact={compact} />
      </dl>

      {stats.keyConcepts > 0 && (
        <Fold
          title="Syllabus"
          defaultOpen={!compact}
          summary={
            short > 0 ? (
              <>
                {stats.met} of {stats.keyConcepts} on target
              </>
            ) : (
              <>
                {stats.keyConcepts} key {stats.keyConcepts === 1 ? 'concept' : 'concepts'}
              </>
            )
          }
        >
          <div className="space-y-2.5">
            {groups.map((group) => (
              <div key={group.name ?? ''}>
                {group.name && (
                  <p className="truncate px-1.5 pb-0.5 text-label tracking-[0.04em] text-fg-3 uppercase">
                    {group.name}
                  </p>
                )}
                {group.concepts.map((concept) => {
                  const me: BrainSelection = { kind: 'keyConcept', index: concept.index }
                  const current =
                    selection?.kind === 'keyConcept' && selection.index === concept.index
                  return (
                    <button
                      key={concept.index}
                      type="button"
                      onClick={() => onSelect(me)}
                      {...preview(me)}
                      aria-current={current ? 'true' : undefined}
                      title={coverageInWords(concept.sources, concept.depth_counts)}
                      className={cn(
                        ROW,
                        'flex-col items-stretch justify-center gap-1 py-1.5',
                        current && 'bg-raised text-fg'
                      )}
                    >
                      <span className="flex items-baseline gap-2">
                        <span className="min-w-0 flex-1 truncate">{concept.label}</span>
                        {concept.named_text?.status === 'missing' && (
                          <span className="sr-only">, its named text is missing</span>
                        )}
                        <span
                          className={cn(
                            'shrink-0 text-label',
                            concept.met ? 'text-fg-3' : 'text-warn'
                          )}
                        >
                          {formatNumber(concept.sources)}
                          {!concept.met && ' · short'}
                        </span>
                      </span>
                      <CoverageBar concept={concept} max={max} />
                    </button>
                  )
                })}
              </div>
            ))}
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1.5 text-label text-fg-3">
              <Key className="bg-fg-2">Sets it out</Key>
              <Key className="bg-fg-3">Treats it</Key>
              <span>Length: sources</span>
            </p>
          </div>
        </Fold>
      )}

      {stats.sources > 0 && (
        <Fold
          title="Sources"
          defaultOpen={!compact}
          summary={
            <>
              {kinds.length} {kinds.length === 1 ? 'kind' : 'kinds'}
            </>
          }
        >
          <div className="space-y-2.5">
            <div>
              {kinds.map((kind) => {
                const on = filter.kind === kind.id
                const next = { ...filter, kind: on ? null : kind.id }
                return (
                  <button
                    key={kind.id}
                    type="button"
                    onClick={() => onFilter(next)}
                    {...preview({ kind: 'filter', filter: { ...filter, kind: kind.id } })}
                    aria-pressed={on}
                    className={cn(ROW, on && 'bg-raised text-fg')}
                  >
                    <KindIcon kind={kind.id} className={on ? 'text-fg' : 'text-fg-3'} />
                    <span className="min-w-0 flex-1 truncate">{kind.label}</span>
                    <Meter value={kind.count} max={kindMax} />
                    <span className="w-6 shrink-0 text-right text-label text-fg-3">
                      {formatNumber(kind.count)}
                    </span>
                  </button>
                )
              })}
            </div>
            <div>
              <p className="px-1.5 pb-0.5 text-label tracking-[0.04em] text-fg-3 uppercase">
                By tier
              </p>
              {TIERS.filter((tier) => tiers[tier.id] > 0).map((tier) => {
                const on = filter.tier === tier.id
                const next = { ...filter, tier: on ? null : tier.id }
                return (
                  <button
                    key={tier.id}
                    type="button"
                    onClick={() => onFilter(next)}
                    {...preview({ kind: 'filter', filter: { ...filter, tier: tier.id } })}
                    aria-pressed={on}
                    title={tier.hint}
                    className={cn(ROW, on && 'bg-raised text-fg')}
                  >
                    <MarkGlyph mark={tierMark(tier.id)} className="mx-px" />
                    <span className="min-w-0 flex-1 truncate">{tier.label}</span>
                    <Meter value={tiers[tier.id]} max={tierMax} />
                    <span className="w-6 shrink-0 text-right text-label text-fg-3">
                      {formatNumber(tiers[tier.id])}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        </Fold>
      )}

      {stats.gaps > 0 && (
        <Fold
          title="Missing texts"
          tone="warn"
          defaultOpen={!compact}
          summary={<>{stats.gaps} the plan named</>}
        >
          {map.syllabus.gaps.map((gap, index) => {
            const me: BrainSelection = { kind: 'gap', index }
            const current = selection?.kind === 'gap' && selection.index === index
            return (
              <button
                // Two gaps can name the same title for different key concepts.
                key={`${index}:${gap.title}`}
                type="button"
                onClick={() => onSelect(me)}
                {...preview(me)}
                aria-current={current ? 'true' : undefined}
                className={cn(ROW, current && 'bg-raised text-fg')}
              >
                <MarkGlyph mark="gap" className="mx-px text-fg-3" />
                <span className="min-w-0 flex-1 truncate">
                  <span className="italic">{gap.title}</span>
                  {gap.author && <span className="ml-1.5 text-fg-3">{gap.author}</span>}
                </span>
              </button>
            )
          })}
        </Fold>
      )}
    </section>
  )
}

const ROW = cn(
  'flex min-h-(--row-h) w-full items-center gap-2 rounded-row px-1.5 text-left text-xs text-fg-2',
  'transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg',
  'pointer-fine:min-h-7'
)

/** The syllabus in its facets' order; key concepts no facet names come last. */
function syllabusGroups(map: MapResponse): { name: string | null; concepts: MapKeyConcept[] }[] {
  const all = map.syllabus.key_concepts
  const placed = new Set<number>()
  const groups: { name: string | null; concepts: MapKeyConcept[] }[] = []
  for (const facet of map.syllabus.facets ?? []) {
    const concepts = facet.concepts
      .filter((index) => all[index] && !placed.has(index))
      .map((index) => {
        placed.add(index)
        return all[index]
      })
    if (concepts.length) groups.push({ name: facet.name, concepts })
  }
  const rest = all.filter((concept) => !placed.has(concept.index))
  if (rest.length) groups.push({ name: groups.length ? 'Other' : null, concepts: rest })
  return groups
}

/** A headline number. Null is "not recorded" and renders as a dash, never zero. */
function Stat({
  label,
  value,
  compact,
}: {
  label: string
  value: number | null
  compact: boolean
}) {
  return (
    <div
      className={cn('min-w-0 rounded-card bg-raised/60', compact ? 'px-2 py-1.5' : 'px-2.5 py-2')}
    >
      <dt className="truncate text-label tracking-[0.04em] text-fg-3 uppercase">{label}</dt>
      <dd
        className={cn(
          'mt-0.5 truncate leading-tight font-medium text-fg',
          compact ? 'text-sm' : 'text-stat'
        )}
      >
        {formatNumber(value)}
      </dd>
    </div>
  )
}

/** A count against the largest in its group: one ink, a recessive track. */
function Meter({ value, max }: { value: number; max: number }) {
  return (
    <span aria-hidden="true" className="h-1 w-16 shrink-0 overflow-hidden rounded-full bg-raised">
      <span
        className="block h-full rounded-full bg-fg-3"
        style={{ width: `${Math.max(4, (value / max) * 100)}%` }}
      />
    </span>
  )
}

function Key({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span aria-hidden="true" className={cn('h-1 w-3 rounded-full', className)} />
      {children}
    </span>
  )
}

/**
 * A section that folds. No height animation: the syllabus is taller than the
 * ~300px `Collapse` is for, and a section that long should simply appear.
 */
function Fold({
  title,
  summary,
  tone,
  defaultOpen,
  children,
}: {
  title: string
  summary: React.ReactNode
  tone?: 'warn'
  defaultOpen: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  const id = useId()
  return (
    <div>
      <h2>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen((value) => !value)}
          className={cn(
            'flex min-h-(--row-h) w-full items-center gap-1 rounded-row px-1 text-left',
            'transition-colors duration-(--dur-1) hover:bg-raised pointer-fine:min-h-7'
          )}
        >
          <ChevronRight
            aria-hidden="true"
            className={cn(
              'size-3 shrink-0 text-fg-3 transition-transform duration-(--dur-1)',
              open && 'rotate-90'
            )}
          />
          <span
            className={cn(
              'text-label tracking-[0.04em] uppercase',
              tone === 'warn' ? 'text-warn' : 'text-fg-2'
            )}
          >
            {title}
          </span>
          <span className="ml-auto truncate pl-2 text-label text-fg-3">{summary}</span>
        </button>
      </h2>
      {open && (
        <div id={id} className="mt-1">
          {children}
        </div>
      )}
    </div>
  )
}
