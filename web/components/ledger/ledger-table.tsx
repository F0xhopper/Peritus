'use client'

import { ArrowDown } from 'lucide-react'

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
 */

export interface Column {
  key: string
  label: string
  /** Only the columns the API can actually sort by are sortable. */
  sort?: SourceSort
  align?: 'left' | 'right'
}

export const COLUMNS: Column[] = [
  { key: 'title', label: 'Source', sort: 'title' },
  { key: 'type', label: 'Kind', sort: 'type' },
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
      <table className="w-full min-w-[420px] border-collapse text-sm">
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
              className={cn(
                'h-(--table-row-h) cursor-default transition-colors duration-(--dur-1)',
                'focus-visible:bg-raised focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fg',
                selectedId === source.id ? 'bg-raised' : 'hover:bg-raised'
              )}
            >
              {COLUMNS.map((column) => (
                <td
                  key={column.key}
                  className={cn(
                    'border-b border-border-soft px-2',
                    column.align === 'right' ? 'text-right' : 'text-left',
                    column.key === 'title' &&
                      cn('sticky left-0 z-10', selectedId === source.id ? 'bg-raised' : 'bg-panel')
                  )}
                >
                  <Cell column={column.key} source={source} />
                </td>
              ))}
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
        <span className="block max-w-[22rem] truncate text-fg-2" title={source.title}>
          {source.title}
          {source.url && <span className="ml-1.5 text-xs text-fg-3">{hostOf(source.url)}</span>}
        </span>
      )

    case 'type':
      // No wrap: "Thought leader" broke onto two lines and doubled its row.
      return (
        <span
          className="whitespace-nowrap text-fg-3"
          title={`Found via ${sourceProvider(source.source_type)}`}
        >
          {sourceKind(source.source_type)}
        </span>
      )

    case 'passages':
      return <span className="text-fg-3">{source.passage_count}</span>

    default:
      return null
  }
}
