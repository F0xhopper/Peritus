'use client'

import { Fragment } from 'react'

import { PopoverContent, PopoverRoot, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/cn'
import { truncate } from '@/lib/format'
import type { Citation } from '@/lib/api/types'

/**
 * Inline `[n]` markers, resolved against the citation list.
 *
 * A marker the answer invented — one pointing past the end of the passage list
 * — is rendered as **plain text, never as a link**. The API tells us which ones
 * those are (`dangling_citations`), and dressing a fabricated reference up as a
 * citation is the single worst thing this component could do.
 *
 * At `lg` and up a marker previews its passage in a popover on hover; below
 * that, tapping it opens the passage panel as a sheet — the hover affordance's
 * tap form, not an extra feature.
 */
const MARKER = /\[(\d{1,3})\]/g

export function CitedText({
  text,
  citations,
  dangling,
  onSelect,
  selected,
}: {
  text: string
  citations: Citation[]
  dangling: number[]
  onSelect: (citation: Citation) => void
  selected: number | null
}) {
  const byNumber = new Map(citations.map((citation) => [citation.n, citation]))
  const danglingSet = new Set(dangling)

  const parts: React.ReactNode[] = []
  let cursor = 0
  let key = 0

  for (const match of text.matchAll(MARKER)) {
    const index = match.index ?? 0
    if (index > cursor) parts.push(text.slice(cursor, index))
    const n = Number(match[1])
    const citation = byNumber.get(n)

    if (citation && !danglingSet.has(n)) {
      parts.push(
        <CitationChip
          key={`c${key++}`}
          citation={citation}
          onSelect={onSelect}
          selected={selected === n}
        />,
      )
    } else {
      // Either not in the list at all, or explicitly flagged as dangling. The
      // explanation is a tap away as well as a hover, so it exists on touch.
      parts.push(<DanglingMarker key={`d${key++}`} marker={match[0]} />)
    }
    cursor = index + match[0].length
  }
  if (cursor < text.length) parts.push(text.slice(cursor))

  return (
    <>
      {parts.map((part, index) => (
        <Fragment key={index}>{part}</Fragment>
      ))}
    </>
  )
}

/**
 * The per-answer numbering: each valid passage number, in the order the answer
 * first cites it, becomes 1, 2, 3. Passage indices are the retrieval order, so a
 * two-citation answer used to show [1] and [3] and invite "where is 2?".
 */
export function numberCitations(content: string, citations: Citation[]): Citation[] {
  const known = new Set(citations.map((citation) => citation.n))
  const order: number[] = []
  for (const match of content.matchAll(MARKER)) {
    const n = Number(match[1])
    if (known.has(n) && !order.includes(n)) order.push(n)
  }
  const display = new Map(order.map((n, index) => [n, index + 1]))
  let next = order.length
  return citations
    .map((citation) => ({ ...citation, display: display.get(citation.n) ?? ++next }))
    .sort((a, b) => (a.display ?? 0) - (b.display ?? 0))
}

function CitationChip({
  citation,
  onSelect,
  selected,
}: {
  citation: Citation
  onSelect: (citation: Citation) => void
  selected: boolean
}) {
  const shown = citation.display ?? citation.n
  const chip = (
    <button
      type="button"
      onClick={(event) => {
        onSelect(citation)
        // Below `lg` the passage opens as a bottom sheet over the lower half of
        // the screen. Bring the chip to the top of the transcript first, so the
        // sentence it supports stays readable above the sheet rather than
        // disappearing behind it.
        if (window.matchMedia('(max-width: 1023px)').matches) {
          const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
          event.currentTarget.scrollIntoView({ block: 'start', behavior: still ? 'auto' : 'smooth' })
        }
      }}
      aria-label={`Citation ${shown}: ${citation.label}`}
      aria-pressed={selected}
      className={cn(
        // The visible chip sits in the line of text; on a coarse pointer the
        // `before:` box extends the tap target to the chip-height token without
        // prying the lines apart.
        'relative mx-0.5 inline-flex h-[1.15rem] min-w-[1.15rem] shrink-0 scroll-mt-20 items-center justify-center rounded-[5px] px-1',
        'align-[0.2em] font-mono text-[0.7em] leading-none font-medium',
        "before:absolute before:inset-x-[-4px] before:top-1/2 before:h-(--chip-h) before:-translate-y-1/2 before:content-['']",
        'transition-colors duration-(--dur-1)',
        selected
          ? 'bg-fg text-bg'
          : 'bg-raised text-fg ring-1 ring-border ring-inset hover:bg-border',
      )}
    >
      {shown}
    </button>
  )

  return (
    <PopoverRoot>
      {/* The popover only exists from `lg` up — `PopoverContent` is hidden
          below that — so on a phone the click handler above is the whole
          interaction and opens the passage sheet. */}
      {/* `chip` is already a native <button>, so no `nativeButton` override:
          passing one would put role="button" on an element that has it. */}
      <PopoverTrigger render={chip} />
      <PopoverContent side="top" className="hidden lg:block">
        <p className="text-xs text-fg-3">Passage {shown}</p>
        <p className="mt-1 text-sm text-fg-2">{truncate(citation.label, 240)}</p>
      </PopoverContent>
    </PopoverRoot>
  )
}

/** An invented marker: plain text, with a tap-or-hover explanation. */
function DanglingMarker({ marker }: { marker: string }) {
  return (
    <PopoverRoot>
      <PopoverTrigger
        render={
          <button
            type="button"
            title="This reference resolves to nothing"
            className="text-fg-3 underline decoration-dotted underline-offset-2"
          >
            {marker}
          </button>
        }
      />
      <PopoverContent side="top">
        <p className="max-w-60 text-xs text-fg-2">
          The answer wrote this reference, but it points to no passage it was given — so there is
          nothing to open. Treat the sentence as unsupported.
        </p>
      </PopoverContent>
    </PopoverRoot>
  )
}

/** The numbered list under an answer, for anyone not hovering anything. */
export function CitationList({
  citations,
  onSelect,
  selected,
  className,
}: {
  citations: Citation[]
  onSelect: (citation: Citation) => void
  selected: number | null
  className?: string
}) {
  if (citations.length === 0) return null
  return (
    <ol className={cn('space-y-1', className)}>
      {citations.map((citation) => (
        <li key={citation.n} className="flex gap-2 text-xs">
          <button
            type="button"
            onClick={() => onSelect(citation)}
            className={cn(
              'flex min-w-0 flex-1 gap-2 text-left transition-colors duration-(--dur-1)',
              selected === citation.n ? 'text-fg' : 'text-fg-3 hover:text-fg-2',
            )}
          >
            <span className="shrink-0 font-mono text-fg-2">[{citation.display ?? citation.n}]</span>
            <span className="min-w-0 flex-1">{citation.label}</span>
          </button>
        </li>
      ))}
    </ol>
  )
}
