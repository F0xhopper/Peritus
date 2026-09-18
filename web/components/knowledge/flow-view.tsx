'use client'

import { useEffect, useMemo, useRef, useState } from 'react'

import { CoverageBar, coverageMax } from '@/components/knowledge/coverage-bar'
import { KindIcon, MarkGlyph, tierMark } from '@/components/knowledge/kind-icon'
import { coverageInWords } from '@/components/knowledge/panels'
import { useMediaQuery, usePrefersReducedMotion } from '@/hooks/use-media-query'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import { FLOW, flowColumns, flowLayout, flowPath, type FlowLink } from '@/lib/brain/flow'
import { litBy, selectionKey, type BrainSelection, type Lit } from '@/lib/brain/selection'
import { sourceKind } from '@/lib/source-kind'
import type { MapResponse } from '@/lib/api/types'

/**
 * The Flow view: what was read, what it was read for, and what came out of it,
 * as three columns with the links between them (`lib/brain/flow.ts`).
 *
 * Everything on it is a button in the DOM — which is the other reason it
 * exists. The Map is a canvas a screen reader cannot enter and a keyboard
 * cannot walk; this is the same selection, the same panels and the same
 * lighting (`litBy`) in a form that can be tabbed through and read out.
 *
 * **Hover is a preview of select.** Resting on a row lights exactly what
 * selecting it would, plus the one relation that is never drawn at rest: the
 * dashed arcs from a concept straight to the sources it was extracted from
 * (or from a source to its concepts). All of them at once would be the hairball
 * this view was built to replace.
 *
 * Loaded with `next/dynamic` and no server render: a row is 26px under a mouse
 * and 44px under a thumb, the columns' `x` comes from the container's width,
 * and neither is knowable on the server (web/AGENTS.md: `useMediaQuery` may
 * not decide what renders *at first paint* — here there is no first paint to
 * get wrong).
 */
export function FlowView({
  map,
  selection,
  lit,
  onSelect,
}: {
  map: MapResponse
  selection: BrainSelection | null
  /** What the page says is lit: a selection, an answer's citations, a filter. */
  lit: Lit | null
  onSelect: (selection: BrainSelection | null) => void
}) {
  const scroller = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const [hover, setHover] = useState<BrainSelection | null>(null)
  const [expanded, setExpanded] = useState<ReadonlySet<number | null>>(() => new Set())
  const coarse = useMediaQuery('(pointer: coarse)')
  const reducedMotion = usePrefersReducedMotion()
  const rowH = coarse ? 44 : 26

  useEffect(() => {
    const node = scroller.current
    if (!node) return
    const measure = () => setWidth(node.clientWidth)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  const pinnedConcept = selection?.kind === 'concept' ? selection.id : null
  const layout = useMemo(
    () => flowLayout(map, { rowH, expanded, pinnedConcept }),
    [map, rowH, expanded, pinnedConcept]
  )
  const columns = useMemo(() => flowColumns(width), [width])
  const max = useMemo(() => coverageMax(map.syllabus.key_concepts), [map])

  const sources = useMemo(() => new Map(map.sources.map((s) => [s.id, s])), [map])
  const concepts = useMemo(() => new Map(map.concepts.map((c) => [c.id, c])), [map])

  const hoverKey = selectionKey(hover)
  const hoverLit = useMemo(
    () => litBy(map, hover),
    // `hoverKey` is the hover's identity; the object is new on every event.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [map, hoverKey]
  )
  const shownLit = hoverLit ?? lit
  const active = hover ?? selection
  const selected = selectionKey(selection)

  // A selection made elsewhere — the search, the Overview, a panel's row — is
  // brought into view. One made here is already under the pointer, and is left
  // where it is. **Once per selection**: the layout also changes when a band is
  // unfolded, and that must not drag the view back to whatever is selected. And
  // not before the diagram is measured, when there is nothing to scroll.
  const broughtIntoView = useRef<string | null>(null)
  const measured = width > 0
  useEffect(() => {
    const node = scroller.current
    if (!selection) broughtIntoView.current = null
    if (!node || !selection || !measured || broughtIntoView.current === selected) return
    broughtIntoView.current = selected
    const y =
      selection.kind === 'source'
        ? layout.sourceY.get(selection.id)
        : selection.kind === 'concept'
          ? layout.conceptY.get(selection.id)
          : selection.kind === 'gap'
            ? layout.gapY.get(selection.index)
            : layout.bands.find((band) => band.key === selection.index)?.nodeY
    if (y === undefined) return
    const top = y + HEADER_H
    if (top > node.scrollTop + HEADER_H + rowH && top < node.scrollTop + node.clientHeight - rowH) {
      return
    }
    node.scrollTo({
      top: Math.max(0, top - node.clientHeight / 2),
      behavior: reducedMotion ? 'auto' : 'smooth',
    })
    // `selected` is the selection's identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, layout, rowH, reducedMotion, measured])

  // The relation never drawn at rest: a concept and the sources that say it.
  const arcs = useMemo(() => {
    if (!active) return []
    const pairs: { key: string; y1: number; y2: number }[] = []
    if (active.kind === 'concept') {
      const to = layout.conceptY.get(active.id)
      if (to === undefined) return []
      for (const id of concepts.get(active.id)?.source_ids ?? []) {
        const from = layout.sourceY.get(id)
        if (from !== undefined) pairs.push({ key: `${id}:${active.id}`, y1: from, y2: to })
      }
    } else if (active.kind === 'source') {
      const from = layout.sourceY.get(active.id)
      if (from === undefined) return []
      for (const [id, to] of layout.conceptY) {
        if (concepts.get(id)?.source_ids.includes(active.id)) {
          pairs.push({ key: `${active.id}:${id}`, y1: from, y2: to })
        }
      }
    }
    return pairs.slice(0, 48)
  }, [active, layout, concepts])

  const dim = (isLit: boolean) => (shownLit && !isLit ? 'opacity-35' : undefined)
  const preview = (next: BrainSelection | null) => ({
    onPointerEnter: (event: React.PointerEvent) => {
      if (event.pointerType === 'mouse') setHover(next)
    },
    onPointerLeave: () => setHover(null),
    onFocus: () => setHover(next),
    onBlur: () => setHover(null),
  })

  const sourceRight = columns.source.x + columns.source.w
  const nodeRight = columns.node.x + columns.node.w
  const shownConcepts = layout.conceptY.size

  return (
    <div
      ref={scroller}
      className="h-full overflow-auto overscroll-contain"
      // A click on the ground clears the selection, as it does on the Map. The
      // lanes and the links take no pointer events, so the ground is whatever
      // is not a row.
      onClick={(event) => {
        if (event.target === event.currentTarget) onSelect(null)
      }}
    >
      {width > 0 && (
        <div style={{ width: columns.width }}>
          <div
            className="sticky top-0 z-20 bg-bg text-label tracking-[0.04em] text-fg-3 uppercase"
            style={{ height: HEADER_H }}
          >
            <ColumnTitle x={columns.source.x} w={columns.source.w} align="right">
              Sources <span className="text-fg-4">{formatNumber(layout.sourceY.size)}</span>
            </ColumnTitle>
            <ColumnTitle x={columns.node.x} w={columns.node.w} align="centre">
              Syllabus
            </ColumnTitle>
            <ColumnTitle x={columns.concept.x} w={columns.concept.w} align="left">
              Concepts{' '}
              <span className="text-fg-4">
                {formatNumber(shownConcepts)}
                {map.totals.concepts !== null && ` of ${formatNumber(map.totals.concepts)}`}
              </span>
            </ColumnTitle>
          </div>

          <div
            className="relative"
            style={{ height: layout.height + 24 }}
            onClick={(event) => {
              if (event.target === event.currentTarget) onSelect(null)
            }}
          >
            {/* The lanes: a surface step, not a rule (web/AGENTS.md, "Colour"). */}
            {layout.bands.map((band, index) => (
              <div
                key={band.key ?? 'foot'}
                aria-hidden="true"
                className={cn(
                  'pointer-events-none absolute right-1.5 left-1.5 rounded-card transition-colors duration-(--dur-1)',
                  band.key !== null && shownLit?.keyConcepts.has(band.key)
                    ? 'bg-panel'
                    : index % 2 === 0
                      ? 'bg-panel/45'
                      : 'bg-panel/20'
                )}
                style={{ top: band.top, height: band.height }}
              />
            ))}

            <svg
              aria-hidden="true"
              className="pointer-events-none absolute top-0 left-0"
              width={columns.width}
              height={layout.height}
              fill="none"
            >
              {layout.links.map((link) => (
                <LinkPath
                  key={`${link.kind}:${link.sourceId ?? link.conceptId}:${link.keyConcept}`}
                  link={link}
                  d={
                    link.kind === 'tag'
                      ? flowPath(sourceRight + PORT, link.y1, columns.node.x, link.y2)
                      : flowPath(nodeRight, link.y1, columns.concept.x - PORT, link.y2)
                  }
                  lit={shownLit ? linkIsLit(link, shownLit) : null}
                />
              ))}
              {arcs.map((arc) => (
                <path
                  key={arc.key}
                  d={flowPath(sourceRight + PORT, arc.y1, columns.concept.x - PORT, arc.y2)}
                  stroke="var(--fg)"
                  strokeWidth={1}
                  strokeDasharray="3 4"
                  opacity={0.55}
                />
              ))}
            </svg>

            {/* A facet's name runs wider than the card it stands over ("Natural
                Theology and Anthropology"), so it takes both channels too — on
                a patch of ground, because links cross behind it. */}
            {layout.facets.map((facet) => (
              <p
                key={facet.name}
                className="absolute z-10 flex justify-center"
                style={{
                  top: facet.y + FLOW.facetH - 21,
                  left: columns.source.x + columns.source.w,
                  width: columns.concept.x - (columns.source.x + columns.source.w),
                }}
              >
                <span className="max-w-full truncate rounded-chip bg-bg px-2 text-label tracking-[0.04em] text-fg-3 uppercase">
                  {facet.name}
                </span>
              </p>
            ))}

            {layout.bands.map((band) => {
              if (band.key === null) return null
              const concept = map.syllabus.key_concepts[band.key]
              if (!concept) return null
              const key: BrainSelection = { kind: 'keyConcept', index: band.key }
              const isSelected = selected === selectionKey(key)
              return (
                <button
                  key={band.key}
                  type="button"
                  onClick={() => onSelect(key)}
                  {...preview(key)}
                  aria-pressed={isSelected}
                  title={coverageInWords(concept.sources, concept.depth_counts)}
                  className={cn(
                    'absolute z-10 flex flex-col justify-between rounded-card px-2.5 py-2 text-left',
                    'transition-[background-color,opacity] duration-(--dur-1)',
                    'outline-offset-2 focus-visible:outline-2 focus-visible:outline-fg',
                    isSelected ? 'bg-border' : 'bg-raised hover:bg-border',
                    dim(shownLit?.keyConcepts.has(band.key) ?? false)
                  )}
                  style={{
                    top: band.nodeY - FLOW.nodeH / 2,
                    left: columns.node.x,
                    width: columns.node.w,
                    height: FLOW.nodeH,
                  }}
                >
                  <span className="line-clamp-2 text-xs leading-4 font-medium text-fg">
                    {concept.label}
                  </span>
                  <span className="flex items-center gap-2">
                    <CoverageBar concept={concept} max={max} />
                    <span className="shrink-0 text-label text-fg-3">
                      {concept.met ? (
                        formatNumber(concept.sources)
                      ) : (
                        <span className="text-warn">{formatNumber(concept.sources)} · short</span>
                      )}
                    </span>
                  </span>
                </button>
              )
            })}

            {layout.items.map((item) => {
              const top = item.y - rowH / 2
              if (item.kind === 'source') {
                const source = sources.get(item.id)
                if (!source) return null
                const me: BrainSelection = { kind: 'source', id: item.id }
                const isSelected = selected === selectionKey(me)
                return (
                  <button
                    key={`s${item.id}`}
                    type="button"
                    onClick={() => onSelect(me)}
                    {...preview(me)}
                    aria-pressed={isSelected}
                    className={cn(
                      ROW,
                      'justify-end pr-1 pl-2',
                      isSelected ? 'bg-raised text-fg' : 'text-fg-2 hover:bg-raised hover:text-fg',
                      dim(shownLit?.sources.has(item.id) ?? false)
                    )}
                    style={{ top, left: columns.source.x, width: columns.source.w, height: rowH }}
                  >
                    <span className="min-w-0 truncate" title={source.title}>
                      {source.title}
                    </span>
                    <span className="sr-only">
                      , {sourceKind(source.kind)}
                      {source.tier ? `, ${source.tier} source` : ''}
                    </span>
                    <KindIcon type={source.kind} className="text-fg-3" />
                    <MarkGlyph mark={tierMark(source.tier)} className="size-2.5" />
                  </button>
                )
              }
              if (item.kind === 'gap') {
                const gap = map.syllabus.gaps[item.index]
                if (!gap) return null
                const me: BrainSelection = { kind: 'gap', index: item.index }
                const isSelected = selected === selectionKey(me)
                return (
                  <button
                    key={`g${item.index}`}
                    type="button"
                    onClick={() => onSelect(me)}
                    {...preview(me)}
                    aria-pressed={isSelected}
                    className={cn(
                      ROW,
                      'justify-end pr-1 pl-2 text-fg-3',
                      isSelected ? 'bg-raised' : 'hover:bg-raised hover:text-fg-2',
                      dim(shownLit?.gaps.has(item.index) ?? false)
                    )}
                    style={{ top, left: columns.source.x, width: columns.source.w, height: rowH }}
                  >
                    <span className="shrink-0 text-label tracking-[0.04em] text-warn uppercase">
                      Missing
                    </span>
                    <span className="min-w-0 truncate italic" title={gap.title}>
                      {gap.title}
                    </span>
                    <MarkGlyph mark="gap" className="size-2.5 text-fg-3" />
                  </button>
                )
              }
              if (item.kind === 'concept') {
                const concept = concepts.get(item.id)
                if (!concept) return null
                const me: BrainSelection = { kind: 'concept', id: item.id }
                const isSelected = selected === selectionKey(me)
                const count = concept.source_ids.length
                return (
                  <button
                    key={`c${item.id}`}
                    type="button"
                    onClick={() => onSelect(me)}
                    {...preview(me)}
                    aria-pressed={isSelected}
                    className={cn(
                      ROW,
                      'pr-2 pl-1',
                      isSelected ? 'bg-raised text-fg' : 'text-fg-2 hover:bg-raised hover:text-fg',
                      dim(shownLit?.concepts.has(item.id) ?? false)
                    )}
                    style={{ top, left: columns.concept.x, width: columns.concept.w, height: rowH }}
                  >
                    <MarkGlyph
                      mark={concept.disputes > 0 ? 'disputed' : 'concept'}
                      className="size-2.5"
                    />
                    <span className="min-w-0 flex-1 truncate" title={concept.label}>
                      {concept.label}
                    </span>
                    {concept.disputes > 0 && <span className="sr-only">, judged in dispute</span>}
                    <span
                      className="shrink-0 text-label text-fg-3"
                      title={`${count} ${count === 1 ? 'source' : 'sources'}`}
                    >
                      {count}
                    </span>
                  </button>
                )
              }
              const band = layout.bands[item.band]
              return (
                <button
                  key={`m${item.band}`}
                  type="button"
                  onClick={() =>
                    setExpanded((current) => {
                      const next = new Set(current)
                      if (next.has(band.key)) next.delete(band.key)
                      else next.add(band.key)
                      return next
                    })
                  }
                  aria-expanded={item.expanded}
                  className={cn(ROW, 'pr-2 pl-5 text-fg-3 hover:bg-raised hover:text-fg-2')}
                  style={{ top, left: columns.concept.x, width: columns.concept.w, height: rowH }}
                >
                  {item.expanded ? 'Show fewer' : `+${formatNumber(item.hidden)} more`}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

const HEADER_H = 32
/** The gap between a row's edge and where its link starts: room for the mark. */
const PORT = 2

const ROW = cn(
  'absolute flex items-center gap-1.5 rounded-row text-left text-xs',
  'transition-[background-color,color,opacity] duration-(--dur-1)',
  'outline-offset-[-2px] focus-visible:outline-2 focus-visible:outline-fg'
)

function ColumnTitle({
  x,
  w,
  align,
  children,
}: {
  x: number
  w: number
  align: 'left' | 'centre' | 'right'
  children: React.ReactNode
}) {
  return (
    <p
      className={cn(
        'absolute bottom-1.5 truncate px-1',
        align === 'right' ? 'text-right' : align === 'centre' ? 'text-center' : 'text-left'
      )}
      style={{ left: x, width: w }}
    >
      {children}
    </p>
  )
}

function linkIsLit(link: FlowLink, lit: Lit): boolean {
  if (!lit.keyConcepts.has(link.keyConcept)) return false
  return link.kind === 'tag'
    ? lit.sources.has(link.sourceId ?? -1)
    : lit.concepts.has(link.conceptId ?? -1)
}

/**
 * One link. Weight is depth: a source that sets a key concept out is a firm
 * line, one that treats it a lighter one, a mention barely there. `lit` is null
 * when nothing is lit, which is the resting picture.
 */
function LinkPath({ link, d, lit }: { link: FlowLink; d: string; lit: boolean | null }) {
  const depth =
    link.kind === 'member'
      ? { width: 1, rest: 0.28 }
      : link.depth === 'sets_out'
        ? { width: 1.75, rest: 0.5 }
        : link.depth === 'treats'
          ? { width: 1.1, rest: 0.32 }
          : { width: 0.75, rest: 0.18 }
  // A tag that crosses bands is a trace at rest (see `FlowLink.home`).
  const crossing = link.kind === 'tag' && !link.home
  const weight = crossing ? { width: depth.width * 0.8, rest: depth.rest * 0.3 } : depth
  return (
    <path
      d={d}
      pathLength={1}
      className="flow-link"
      stroke={lit ? 'var(--fg)' : 'var(--fg-3)'}
      strokeWidth={lit ? weight.width + 0.25 : weight.width}
      opacity={lit === null ? weight.rest : lit ? 0.9 : 0.07}
    />
  )
}
