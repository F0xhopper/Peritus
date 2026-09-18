'use client'

import { Table as TableIcon, X } from 'lucide-react'
import { useEffect, useMemo } from 'react'

import { LedgerCards } from '@/components/ledger/ledger-cards'
import { LedgerTable } from '@/components/ledger/ledger-table'
import { Button } from '@/components/ui/button'
import { Empty } from '@/components/ui/empty'
import { Select } from '@/components/ui/select'
import { hostOf } from '@/lib/format'
import { isFiltering, passesFilter, type SourceFilter } from '@/lib/brain/overview'
import type { CorpusReport, LedgerSource, SourceSort } from '@/lib/api/types'

/**
 * The List view of the Knowledge page: the sources this expert answers from.
 *
 * Today's Sources table, kept whole. Find, sort, export, add and remove are its
 * job, it is the form that works at 360px, and it is the accessible form of
 * the page — the map is a canvas a screen reader cannot enter
 * (docs/plans/expert-brain.md, "What not to do").
 *
 * Sort and page are URL state pushed through a transition, so a sorted list is
 * a link; the table dims while the server re-renders rather than spinning. The
 * table is the `md`+ form and a card list below it, both in the HTML.
 */
export function ListView({
  report,
  sort,
  page,
  pageSize,
  conceptFilter,
  sourceFilter,
  filter,
  selectedId,
  pending,
  onSelect,
  onClearConcept,
  onNavigate,
}: {
  report: CorpusReport
  sort: SourceSort
  page: number
  pageSize: number
  /** A key concept's label: only the sources that cover it. */
  conceptFilter: string | null
  /** The Overview's kind and tier filter; its chip is in the page's toolbar. */
  sourceFilter: SourceFilter
  /** The page's search text, which narrows the rows here. */
  filter: string
  selectedId: number | null
  pending: boolean
  onSelect: (source: LedgerSource) => void
  onClearConcept: () => void
  onNavigate: (changes: Record<string, string | null>) => void
}) {
  // `?concept=` narrows client-side: the API filters and sorts, but has no
  // concept filter, and the page is already bounded. The text filter runs
  // after it, over title, author and host — the three things somebody looking
  // for one source actually remembers.
  const rows = useMemo(() => {
    const concept = conceptFilter?.toLowerCase()
    const needle = filter.trim().toLowerCase()
    return report.sources.filter((source) => {
      if (concept && !source.covered_concepts.some((c) => c.toLowerCase() === concept)) return false
      if (!passesFilter({ type: source.source_type, tier: source.source_tier }, sourceFilter)) {
        return false
      }
      if (!needle) return true
      const host = source.url ? (hostOf(source.url) ?? '') : ''
      return `${source.title} ${source.author ?? ''} ${host}`.toLowerCase().includes(needle)
    })
  }, [report.sources, conceptFilter, sourceFilter, filter])

  // A selected row is scrolled to, or the panel describes a row the reader
  // cannot see: a cited source is rarely in the first screenful.
  useEffect(() => {
    if (selectedId === null) return
    document
      .querySelector(`tr[data-source-id="${selectedId}"]`)
      ?.scrollIntoView({ block: 'center' })
  }, [selectedId])

  const total = report.page.total_matching ?? report.sources.length
  const lastPage = Math.max(1, Math.ceil(total / pageSize))

  return (
    <div className="space-y-3 p-3 md:p-4">
      {(conceptFilter || isFiltering(sourceFilter)) && (
        // The count is the filtered one: it used to read "16 sources" over a
        // table of six. Both filters narrow the loaded page, so past one page
        // the sentence says so rather than implying it counted them all.
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <span className="text-fg-3">
            {rows.length} of{' '}
            {lastPage > 1
              ? `the ${report.sources.length} sources on this page`
              : `${total} ${total === 1 ? 'source' : 'sources'}`}{' '}
            {conceptFilter ? 'cover' : 'match'}
          </span>
          {conceptFilter && (
            <span className="inline-flex items-center gap-1 rounded-chip bg-expert-soft py-0.5 pr-1 pl-2 text-xs text-expert">
              {conceptFilter}
              <button
                type="button"
                onClick={onClearConcept}
                aria-label="Stop narrowing by this key concept"
                className="grid size-4 place-items-center rounded-chip transition-colors duration-(--dur-1) hover:bg-expert/20"
              >
                <X className="size-3" />
              </button>
            </span>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 lg:hidden">
        {/* A native select below `lg`, where a sortable header row has no
            room; the headers themselves sort at `lg` and up. */}
        <Select
          aria-label="Sort by"
          value={sort}
          onChange={(event) => onNavigate({ sort: event.target.value, page: null })}
        >
          <option value="title">Sort: Title</option>
          <option value="type">Sort: Kind</option>
          <option value="added">Sort: Added</option>
        </Select>
      </div>

      {rows.length === 0 ? (
        <Empty icon={TableIcon}>
          {total === 0
            ? 'This expert has no sources yet — nothing has been searched.'
            : 'No sources match this filter.'}
        </Empty>
      ) : (
        <>
          <div className="hidden md:block">
            <LedgerTable
              sources={rows}
              sort={sort}
              onSort={(next) => onNavigate({ sort: next, page: null })}
              onSelect={onSelect}
              selectedId={selectedId}
              pending={pending}
            />
          </div>
          <div className="md:hidden">
            <LedgerCards
              sources={rows}
              onSelect={onSelect}
              selectedId={selectedId}
              pending={pending}
            />
          </div>
        </>
      )}

      {lastPage > 1 && (
        <div className="flex items-center justify-between gap-2 text-sm">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1 || pending}
            onClick={() => onNavigate({ page: String(page - 1) })}
          >
            Previous
          </Button>
          <span className="text-xs text-fg-3">
            Page {page} of {lastPage} · {total} sources
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= lastPage || pending}
            onClick={() => onNavigate({ page: String(page + 1) })}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  )
}
