'use client'

import { ChevronRight, ListTree } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'

import { KindIcon } from '@/components/knowledge/kind-icon'
import { Button } from '@/components/ui/button'
import { Empty } from '@/components/ui/empty'
import { Notice } from '@/components/ui/notice'
import { Skeleton } from '@/components/ui/skeleton'
import type { WorkSections } from '@/hooks/use-expert-outline'
import {
  closeShare,
  isUnstructured,
  locusRange,
  narrowOutline,
  partName,
  readingInWords,
} from '@/lib/brain/outline'
import { keyConceptLabel } from '@/lib/brain/paint'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import type { OutlinePart, OutlineResponse, OutlineSection, OutlineWork } from '@/lib/api/types'

/**
 * The Outline view of the Knowledge page: what the expert holds, in the shape
 * its authors gave it.
 *
 * The Map, the Flow and the Graph draw the expert's *ideas*. None of them can
 * say which works are in it, how far into each one it reads, or which parts it
 * read closely as against merely holds — and that was the thing nobody could
 * see when every long work was being cut at its first tenth
 * (docs/plans/beating-closed-book.md §3.1). This is the view that would have
 * shown it: a work, its parts by heading and locus, and under each part what a
 * build found it to establish.
 *
 * **Read closely / held** is the one distinction drawn, and it is one ink in two
 * shades like every other measure on the page (web/AGENTS.md, "Monochrome") — a
 * held part is not a worse part, so it takes no status colour; it says "Held" in
 * words. Key concepts on a part are counted from the concept graph, so a held
 * part has none: no model ever read it.
 *
 * It is DOM, a list of disclosure buttons, so it works at 360px, under a
 * keyboard and in a screen reader, and scales by scrolling — twelve thousand
 * passages is a few hundred rows here and a hairball anywhere else on the page.
 * A work's section summaries are most of the payload's weight and are read when
 * it is opened (`useOutlineSections`).
 */
export function OutlineView({
  outline,
  error,
  slug,
  litSources,
  keyConcept,
  selectedSourceId,
  filter,
  sections,
  onLoadSections,
  onSelectSource,
  onWatchBuild,
}: {
  /** Null until the first fetch lands. */
  outline: OutlineResponse | null
  error: string | null
  slug: string
  /** The sources the page has lit — a filter, a key concept, a citation — or null. */
  litSources: ReadonlySet<number> | null
  /** The key concept in hand, by index: its parts are marked, the rest recede. */
  keyConcept: number | null
  selectedSourceId: number | null
  /** The page's search text, which narrows the works and parts here. */
  filter: string
  sections: ReadonlyMap<number, WorkSections>
  onLoadSections: (sourceId: number) => void
  onSelectSource: (sourceId: number) => void
  onWatchBuild: () => void
}) {
  // What the reader has opened or shut themselves; anything they have not
  // touched is open when it is the source in hand or the search matched inside
  // it. Derived, so neither of those has to write state to follow a prop — and a
  // work opened by a selection can still be shut.
  const [chosen, setChosen] = useState<ReadonlyMap<number, boolean>>(new Map())
  const rows = useMemo(() => (outline ? narrowOutline(outline, filter) : []), [outline, filter])
  const isOpen = (sourceId: number, byPart: boolean) =>
    chosen.get(sourceId) ?? (selectedSourceId === sourceId || byPart)

  // Whatever is open has its sections fetched. `onLoadSections` is idempotent
  // and sets state only when a request settles.
  const openIds = rows
    .filter((row) => isOpen(row.work.source_id, row.byPart))
    .filter((row) => row.work.parts.some((part) => part.section_count > 0))
    .map((row) => row.work.source_id)
    .join(',')
  useEffect(() => {
    for (const id of openIds.split(',').filter(Boolean)) onLoadSections(Number(id))
  }, [openIds, onLoadSections])

  // The source in hand is scrolled to: chosen from the search or another view,
  // it is rarely in the first screenful.
  useEffect(() => {
    if (selectedSourceId === null || !outline) return
    document
      .querySelector(`[data-outline-work="${selectedSourceId}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  }, [selectedSourceId, outline])

  if (!outline) {
    return error ? (
      <div className="grid h-full place-items-center p-4">
        <Notice tone="bad" title="The outline could not be loaded">
          {error}
        </Notice>
      </div>
    ) : (
      <div className="space-y-2 p-3 md:p-4" aria-busy="true" aria-label="Loading the outline">
        {[0, 1, 2, 3, 4, 5].map((row) => (
          <Skeleton key={row} className="h-14 w-full rounded-card" />
        ))}
      </div>
    )
  }

  if (!outline.computed) {
    return (
      <div className="grid h-full place-items-center p-4">
        <div className="w-full max-w-sm text-center">
          <Empty icon={ListTree}>
            Nothing has been read yet. Each source appears here, part by part, as Peritus reads it.
          </Empty>
          <Button variant="outline" size="md" className="mt-3" onClick={onWatchBuild}>
            Watch the build
          </Button>
        </div>
      </div>
    )
  }

  const { totals } = outline
  return (
    <div className="space-y-3 p-3 md:p-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-3">
        <p>
          {formatNumber(totals.works)} {totals.works === 1 ? 'work' : 'works'} ·{' '}
          {readingInWords(totals, formatNumber)}
        </p>
        {totals.held > 0 && (
          <ul aria-label="What the bars mean" className="flex items-center gap-3 text-label">
            <li className="inline-flex items-center gap-1.5">
              <span aria-hidden="true" className="h-1 w-4 rounded-full bg-fg-2" />
              Read closely
            </li>
            <li className="inline-flex items-center gap-1.5">
              <span aria-hidden="true" className="h-1 w-4 rounded-full bg-fg-4" />
              Held
            </li>
          </ul>
        )}
      </div>

      {(totals.held > 0 || totals.sections > 0) && (
        // Said once, here, rather than under every part that is opened.
        <p className="max-w-prose text-xs text-fg-3">
          {totals.held > 0 &&
            'A part read closely was annotated and mined for concepts. A held part is the rest of a long work: searchable and citable, but no concept was drawn from it. '}
          {totals.sections > 0 &&
            'Open a part for what it establishes — Peritus’s own index of it, not a quotation.'}
        </p>
      )}

      {rows.length === 0 ? (
        <Empty icon={ListTree}>No work or part matches “{filter.trim()}”.</Empty>
      ) : (
        <ul className="space-y-2">
          {rows.map(({ work, parts, byPart }) => (
            <WorkRow
              key={work.source_id}
              work={work}
              parts={parts}
              slug={slug}
              open={isOpen(work.source_id, byPart)}
              dimmed={litSources !== null && !litSources.has(work.source_id)}
              selected={selectedSourceId === work.source_id}
              keyConcept={keyConcept}
              keyConcepts={outline.key_concepts}
              sections={sections.get(work.source_id) ?? null}
              onToggle={() => {
                const next = !isOpen(work.source_id, byPart)
                setChosen((previous) => new Map(previous).set(work.source_id, next))
              }}
              onSelect={() => onSelectSource(work.source_id)}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

function WorkRow({
  work,
  parts,
  slug,
  open,
  dimmed,
  selected,
  keyConcept,
  keyConcepts,
  sections,
  onToggle,
  onSelect,
}: {
  work: OutlineWork
  parts: OutlinePart[]
  slug: string
  open: boolean
  dimmed: boolean
  selected: boolean
  keyConcept: number | null
  keyConcepts: string[]
  sections: WorkSections | null
  onToggle: () => void
  onSelect: () => void
}) {
  const bodyId = `outline-work-${work.source_id}`
  const span = locusRange(work.locus_first, work.locus_last)
  const share = closeShare(work)
  // The loaded parts are the same parts, cut by the same function; they are
  // matched by where they start rather than by position, which a search narrows.
  const loadedBySeq = useMemo(
    () => new Map((sections?.work?.parts ?? []).map((part) => [part.seq_start, part.sections])),
    [sections]
  )

  return (
    <li
      data-outline-work={work.source_id}
      className={cn(
        'rounded-card border bg-panel transition-opacity duration-(--dur-1)',
        selected ? 'border-border' : 'border-border-soft',
        dimmed && 'opacity-45'
      )}
    >
      <div className="flex items-stretch">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={onToggle}
          className="flex min-h-(--row-h) min-w-0 flex-1 items-start gap-2.5 rounded-card px-3 py-2.5 text-left"
        >
          <ChevronRight
            aria-hidden="true"
            className={cn(
              'mt-0.5 size-3.5 shrink-0 text-fg-3 transition-transform duration-(--dur-1)',
              open && 'rotate-90'
            )}
          />
          <KindIcon type={work.kind} className="mt-0.5 text-fg-3" />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm text-fg">{work.title}</span>
            <span className="mt-0.5 block truncate text-xs text-fg-3">
              {[
                work.author,
                span,
                work.held > 0
                  ? `${formatNumber(work.close)} read closely, ${formatNumber(work.held)} held`
                  : `${formatNumber(work.passages)} ${work.passages === 1 ? 'passage' : 'passages'}`,
              ]
                .filter(Boolean)
                .join(' · ')}
            </span>
            {/* Decorative: the line above says the same thing in words. */}
            <span
              aria-hidden="true"
              className="mt-1.5 flex h-1 w-full max-w-64 gap-0.5 overflow-hidden rounded-full"
            >
              {work.close > 0 && (
                <span className="h-full rounded-full bg-fg-2" style={{ flexGrow: share }} />
              )}
              {work.held > 0 && (
                <span className="h-full rounded-full bg-fg-4" style={{ flexGrow: 1 - share }} />
              )}
            </span>
          </span>
        </button>
        <button
          type="button"
          onClick={onSelect}
          className="grid min-h-(--row-h) shrink-0 place-items-center self-start rounded-row px-3 text-xs text-fg-3 transition-colors duration-(--dur-1) hover:text-fg"
        >
          Details<span className="sr-only"> of {work.title}</span>
        </button>
      </div>

      {open && (
        <div id={bodyId} className="border-t border-border-soft px-3 py-2">
          {sections?.error && (
            <p className="py-1 text-xs text-bad">
              What each part establishes could not be loaded. {sections.error}
            </p>
          )}
          {isUnstructured(work) ? (
            <UnstructuredWork
              work={work}
              slug={slug}
              sections={loadedBySeq.get(work.parts[0].seq_start) ?? null}
            />
          ) : (
            <ol className="divide-y divide-border-soft">
              {parts.map((part) => (
                <PartRow
                  key={part.seq_start}
                  part={part}
                  sourceId={work.source_id}
                  slug={slug}
                  keyConcept={keyConcept}
                  keyConcepts={keyConcepts}
                  sections={loadedBySeq.get(part.seq_start) ?? null}
                  failed={Boolean(sections?.error)}
                />
              ))}
            </ol>
          )}
        </div>
      )}
    </li>
  )
}

function PartRow({
  part,
  sourceId,
  slug,
  keyConcept,
  keyConcepts,
  sections,
  failed,
}: {
  part: OutlinePart
  sourceId: number
  slug: string
  keyConcept: number | null
  keyConcepts: string[]
  /** Null while they load, or when none were asked for. */
  sections: OutlineSection[] | null
  failed: boolean
}) {
  const [open, setOpen] = useState(false)
  const { title, place } = partName(part)
  const marked = keyConcept !== null && part.key_concepts.includes(keyConcept)
  const recedes = keyConcept !== null && !marked
  const bodyId = `outline-part-${sourceId}-${part.seq_start}`
  const expandable = part.section_count > 0

  const heading = (
    <>
      <span className={cn('min-w-0 flex-1', recedes && 'opacity-50')}>
        <span className={cn('block text-sm', marked ? 'text-fg' : 'text-fg-2')}>
          {title ?? 'Untitled part'}
        </span>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-fg-3">
          {place && <span>{place}</span>}
          <span>
            {formatNumber(part.passages)} {part.passages === 1 ? 'passage' : 'passages'}
          </span>
          {part.held && <span>Held</span>}
          {part.key_concepts.map((index) => (
            <span
              key={index}
              className={cn(
                'rounded-chip px-1.5 py-px text-label',
                index === keyConcept ? 'bg-fg text-bg' : 'bg-expert-soft text-expert'
              )}
            >
              {keyConceptLabel(keyConcepts[index] ?? '')}
            </span>
          ))}
        </span>
      </span>
    </>
  )

  return (
    <li className="py-1">
      <div className="flex items-start gap-1">
        {expandable ? (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setOpen((value) => !value)}
            className="flex min-h-(--row-h) min-w-0 flex-1 items-start gap-2 rounded-row py-1.5 text-left"
          >
            <ChevronRight
              aria-hidden="true"
              className={cn(
                'mt-1 size-3 shrink-0 text-fg-3 transition-transform duration-(--dur-1)',
                open && 'rotate-90'
              )}
            />
            {heading}
          </button>
        ) : (
          <div className="flex min-h-(--row-h) min-w-0 flex-1 items-start gap-2 py-1.5">
            <span aria-hidden="true" className="size-3 shrink-0" />
            {heading}
          </div>
        )}
        <ReadLink slug={slug} sourceId={sourceId} passageId={part.passage_id} what={title} />
      </div>

      {open && expandable && (
        <div id={bodyId} className="pb-2 pl-5">
          {sections ? (
            <SectionList sections={sections} slug={slug} sourceId={sourceId} />
          ) : failed ? null : (
            <div
              className="space-y-1.5"
              aria-busy="true"
              aria-label="Loading what this part establishes"
            >
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-5/6" />
            </div>
          )}
        </div>
      )}
    </li>
  )
}

/** A source with no headings and no loci: its sections, if a build wrote any, and nothing else. */
function UnstructuredWork({
  work,
  slug,
  sections,
}: {
  work: OutlineWork
  slug: string
  sections: OutlineSection[] | null
}) {
  const part = work.parts[0]
  if (part.section_count === 0) {
    return (
      <p className="flex flex-wrap items-center justify-between gap-2 py-1.5 text-xs text-fg-3">
        This source has no headings to outline.
        <ReadLink slug={slug} sourceId={work.source_id} passageId={part.passage_id} what={null} />
      </p>
    )
  }
  return sections ? (
    <div className="py-1.5">
      <SectionList sections={sections} slug={slug} sourceId={work.source_id} />
    </div>
  ) : (
    <div
      className="space-y-1.5 py-2"
      aria-busy="true"
      aria-label="Loading what this source establishes"
    >
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-5/6" />
    </div>
  )
}

function SectionList({
  sections,
  slug,
  sourceId,
}: {
  sections: OutlineSection[]
  slug: string
  sourceId: number
}) {
  return (
    <ol className="space-y-2.5">
      {sections.map((section) => (
        <SectionItem
          key={section.seq_start}
          section={section}
          only={sections.length === 1}
          href={`/experts/${slug}/sources/${sourceId}/read?at=${section.passage_id}`}
        />
      ))}
    </ol>
  )
}

/** Past this a summary is folded to three lines: a real one runs to a dozen. */
const SUMMARY_FOLD_CHARS = 260

function SectionItem({
  section,
  only,
  href,
}: {
  section: OutlineSection
  /** A part's only section is the part: its place and count are on the row above. */
  only: boolean
  href: string
}) {
  const [full, setFull] = useState(false)
  const long = section.summary.length > SUMMARY_FOLD_CHARS
  const place = locusRange(section.locus_first, section.locus_last)
  return (
    <li className="text-xs leading-relaxed text-fg-2">
      <p className={cn('max-w-prose', long && !full && 'line-clamp-3')}>{section.summary}</p>
      <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-fg-3">
        {!only && place && <span>{place}</span>}
        {!only && (
          <span>
            {formatNumber(section.passages)} {section.passages === 1 ? 'passage' : 'passages'}
          </span>
        )}
        {long && (
          <button
            type="button"
            aria-expanded={full}
            onClick={() => setFull((value) => !value)}
            className="underline decoration-border underline-offset-2 hover:text-fg"
          >
            {full ? 'Less' : 'More'}
          </button>
        )}
        <Link href={href} className="underline decoration-border underline-offset-2 hover:text-fg">
          Read it
        </Link>
      </p>
    </li>
  )
}

function ReadLink({
  slug,
  sourceId,
  passageId,
  what,
}: {
  slug: string
  sourceId: number
  passageId: number
  what: string | null
}) {
  return (
    <Link
      href={`/experts/${slug}/sources/${sourceId}/read?at=${passageId}`}
      className="grid min-h-(--row-h) shrink-0 place-items-center rounded-row px-2 text-xs text-fg-3 transition-colors duration-(--dur-1) hover:text-fg"
    >
      <span>
        Read<span className="sr-only"> {what ?? 'this source'}</span>
      </span>
    </Link>
  )
}
