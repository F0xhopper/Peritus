'use client'

import { ArrowDown, ChevronRight } from 'lucide-react'

import { DateText } from '@/components/ui/relative-time'
import { cn } from '@/lib/cn'
import { sourceKind, sourceProvider } from '@/lib/source-kind'
import { hostOf } from '@/lib/format'
import type { LedgerSource, SourceSort } from '@/lib/api/types'

/**
 * The sources, as a table.
 *
 * 28px rows (40px on touch, from `--table-row-h`), a sticky header, and a
 * horizontal scroll container with the title column `sticky left-0` at `md` —
 * a table is one of the three things allowed to scroll sideways, and only
 * inside its own box.
 *
 * **The title gets the width.** It was capped at 22rem inside a table twice
 * that wide, so every real title was cut ("A Virulent Strain of Deformed Wing
 * Virus (DWV) of Hon…") while the middle of the table stood empty — and the
 * host, which shared that truncated cell, survived only on short titles. The
 * host now has its own muted column, because telling a doi.org paper from a
 * blog post is most of what a reader scans this list for.
 *
 * **A row opens a record, and now says so**: the cursor, a trailing chevron and
 * an accessible name. The detail panel used to be discoverable by accident.
 */

export interface Column {
  key: string
  label: string
  /** Only the columns the API can actually sort by are sortable. */
  sort?: SourceSort
  align?: 'left' | 'right'
  /** Hidden below `lg`, where the table is inside a horizontal scroller. */
  wide?: boolean
}

export const COLUMNS: Column[] = [
  { key: 'title', label: 'Source', sort: 'title' },
  { key: 'host', label: 'Where', wide: true },
  { key: 'type', label: 'Kind', sort: 'type' },
  { key: 'added', label: 'Added', sort: 'added', align: 'right', wide: true },
  { key: 'passages', label: 'Passages', align: 'right' },
]

export function LedgerTable({
  sources,
  sort,
  onSort,
  onSelect,
  selectedId,
  pending,
}: {
  sources: LedgerSource[]
  sort: SourceSort
  onSort: (sort: SourceSort) => void
  onSelect: (source: LedgerSource) => void
  selectedId: number | null
  /** True during a sort transition: the table dims rather than spinning. */
  pending: boolean
}) {
  return (
    <div
      className={cn(
        'overflow-x-auto rounded-card bg-panel',
        'transition-opacity duration-(--dur-1)',
        pending && 'opacity-60'
      )}
    >
      <table className="w-full min-w-[560px] table-fixed border-collapse text-sm">
        <colgroup>
          <col />
          <col className="hidden w-40 lg:table-column" />
          <col className="w-28" />
          <col className="hidden w-24 lg:table-column" />
          <col className="w-20" />
          <col className="w-8" />
        </colgroup>
        <thead className="sticky top-0 z-10 bg-panel">
          <tr>
            {COLUMNS.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cn(
                  // `font-normal`: a `<th>` is bold by default, and bold 11px
                  // capitals read as shouting next to the rows beneath.
                  'border-b border-border px-2 py-1.5 text-label font-normal tracking-[0.04em] whitespace-nowrap text-fg-3 uppercase',
                  column.align === 'right' ? 'text-right' : 'text-left',
                  column.wide && 'hidden lg:table-cell',
                  // The title column stays put while the rest scrolls.
                  column.key === 'title' && 'sticky left-0 z-20 bg-panel'
                )}
              >
                {column.sort ? (
                  <button
                    type="button"
                    onClick={() => onSort(column.sort!)}
                    className={cn(
                      // `--icon-btn` tall, so a sort control is reachable on a
                      // touch device: the header text itself is 20px, and a
                      // header that can only be hit with a mouse makes the
                      // table read-only on an iPad.
                      // `uppercase` again: a button does not inherit the
                      // header's text-transform (the UA sheet resets it), so
                      // the sortable headers read "Kind" beside "PASSAGES".
                      'inline-flex h-(--icon-btn) items-center gap-1 uppercase',
                      'transition-colors duration-(--dur-1) hover:text-fg-2',
                      sort === column.sort && 'text-fg-2'
                    )}
                  >
                    {column.label}
                    {sort === column.sort && <ArrowDown className="size-3" aria-hidden="true" />}
                  </button>
                ) : (
                  column.label
                )}
              </th>
            ))}
            <th scope="col" className="border-b border-border">
              <span className="sr-only">Details</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {sources.map((source) => (
            <tr
              key={source.id}
              data-source-id={source.id}
              onClick={() => onSelect(source)}
              // Rows are the way into a source's detail, so they take focus and
              // Enter or Space opens them, as a click does.
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onSelect(source)
                }
              }}
              aria-selected={selectedId === source.id}
              aria-label={`${source.title} — open details`}
              className={cn(
                'group h-(--table-row-h) cursor-pointer transition-colors duration-(--dur-1)',
                'focus-visible:bg-raised focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fg',
                selectedId === source.id ? 'bg-raised' : 'hover:bg-raised'
              )}
            >
              {COLUMNS.map((column) => (
                <td
                  key={column.key}
                  className={cn(
                    'overflow-hidden border-b border-border-soft px-2',
                    column.align === 'right' ? 'text-right' : 'text-left',
                    column.wide && 'hidden lg:table-cell',
                    column.key === 'title' &&
                      cn('sticky left-0 z-10', selectedId === source.id ? 'bg-raised' : 'bg-panel')
                  )}
                >
                  <Cell column={column.key} source={source} />
                </td>
              ))}
              <td className="border-b border-border-soft pr-1.5">
                <ChevronRight
                  aria-hidden="true"
                  className="size-3.5 text-fg-4 transition-colors duration-(--dur-1) group-hover:text-fg-2"
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Cell({ column, source }: { column: string; source: LedgerSource }) {
  switch (column) {
    case 'title':
      return (
        <span className="block truncate text-fg-2" title={source.title}>
          {source.title}
          {source.author && <span className="ml-1.5 text-xs text-fg-3">{source.author}</span>}
        </span>
      )

    case 'host':
      return source.url ? (
        <span className="block truncate text-xs text-fg-3">{hostOf(source.url)}</span>
      ) : (
        <span className="text-fg-4">—</span>
      )

    case 'type':
      // No wrap: "Thought leader" broke onto two lines and doubled its row.
      return (
        <span
          className="block truncate whitespace-nowrap text-fg-3"
          title={`Found via ${sourceProvider(source.source_type)}`}
        >
          {sourceKind(source.source_type)}
        </span>
      )

    case 'added':
      return <DateText iso={source.created_at} className="text-xs text-fg-3" />

    case 'passages':
      return <span className="text-fg-3">{source.passage_count}</span>

    default:
      return null
  }
}
