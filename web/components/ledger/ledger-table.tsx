'use client'

import { ArrowDown } from 'lucide-react'

import { Chip } from '@/components/ui/chip'
import { cn } from '@/lib/cn'
import { describeDiscovery, describeTextRead, sourceKind, sourceProvider } from '@/lib/source-kind'
import { formatScore, hostOf, truncate } from '@/lib/format'
import type { LedgerSource, SourceSort } from '@/lib/api/types'

/**
 * The ledger, as a table.
 *
 * Every source the corpus was built from **and every source it rejected**, with
 * the reason. The rejected half is a first-class view, not a debug panel: the
 * excluded sources are the evidence that the included ones were selected, and
 * nothing else in the product makes that argument.
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
  /** Dropped first when the table is narrow. */
  optional?: boolean
}

export const COLUMNS: Column[] = [
  { key: 'title', label: 'Source' },
  { key: 'type', label: 'Kind', sort: 'type' },
  { key: 'decision', label: 'Decision', sort: 'decision' },
  { key: 'quality', label: 'Quality', sort: 'quality', align: 'right' },
  { key: 'relevance', label: 'Relevance', sort: 'relevance', align: 'right' },
  { key: 'reason', label: 'Why', optional: true },
  { key: 'discovered', label: 'How found', sort: 'discovered_via', optional: true },
  { key: 'text', label: 'Text read', optional: true },
  { key: 'passages', label: 'Passages', align: 'right', optional: true },
]

export function LedgerTable({
  sources,
  sort,
  onSort,
  onSelect,
  selectedId,
  visible,
  pending,
}: {
  sources: LedgerSource[]
  sort: SourceSort
  onSort: (sort: SourceSort) => void
  onSelect: (source: LedgerSource) => void
  selectedId: number | null
  /** Column keys to render, from the column picker. */
  visible: Set<string>
  /** True during a filter transition: the table dims rather than spinning. */
  pending: boolean
}) {
  const columns = COLUMNS.filter((column) => visible.has(column.key))

  return (
    <div
      className={cn(
        'overflow-x-auto rounded-card bg-panel',
        'transition-opacity duration-(--dur-1)',
        pending && 'opacity-60'
      )}
    >
      <table className="w-full min-w-[720px] border-collapse text-sm">
        <thead className="sticky top-0 z-10 bg-panel">
          <tr>
            {columns.map((column) => (
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
                      // the sortable headers read "Decision" beside "SOURCE".
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
              {columns.map((column) => (
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

    case 'decision':
      // A filled chip, which the design reserves for exactly this column and
      // citation markers.
      return source.decision === 'accepted' ? (
        <Chip tone="ok">Kept</Chip>
      ) : (
        <Chip tone="bad">Dropped</Chip>
      )

    case 'quality':
      return <ScoreCell value={source.quality_score} />

    case 'relevance':
      return <ScoreCell value={source.relevance_score} />

    case 'reason':
      // Null on every kept row by contract — a kept source has no reason to be
      // dropped. An empty cell says that; a dash read as missing data.
      return source.drop_reason ? (
        <span className="block max-w-[18rem] truncate text-xs text-fg-3" title={source.drop_reason}>
          {source.drop_reason}
        </span>
      ) : source.decision === 'accepted' ? null : (
        <span className="text-fg-3">—</span>
      )

    case 'discovered':
      return source.discovered_via ? (
        <span className="text-xs text-fg-3" title={source.discovered_via}>
          {truncate(describeDiscovery(source.discovered_via), 32)}
        </span>
      ) : (
        <span className="text-fg-3">—</span>
      )

    case 'text':
      if (!source.full_text_method) return <span className="text-fg-3">—</span>
      // "abstract" means the source was judged, and is answering questions, on
      // its abstract alone. That is the first thing a reviewer asks about a
      // corpus, so it is coloured rather than buried.
      return source.full_text_method === 'abstract' ? (
        <span className="text-xs text-warn">Abstract only</span>
      ) : (
        <span className="text-xs text-fg-3">{describeTextRead(source.full_text_method)}</span>
      )

    case 'passages':
      return <span className="text-fg-3">{source.passage_count}</span>

    default:
      return null
  }
}

/**
 * A score plus a 4px inline bar.
 *
 * The bar fills with a `scaleX` transform on first paint only — a re-sort or a
 * filter change is instant, because animating two hundred bars on every
 * interaction is noise, not feedback.
 */
function ScoreCell({ value }: { value: number | null }) {
  if (value === null) return <span className="text-fg-3">—</span>
  return <span className="font-mono text-xs text-fg-2">{formatScore(value)}</span>
}
