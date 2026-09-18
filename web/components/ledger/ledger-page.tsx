'use client'

import { Download, Plus, Table as TableIcon, X } from 'lucide-react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useEffect, useMemo, useState, useTransition } from 'react'

import { AddSourceDialog } from '@/components/ledger/add-source-dialog'
import { canManage } from '@/lib/access'
import { LedgerCards } from '@/components/ledger/ledger-cards'
import { LedgerTable } from '@/components/ledger/ledger-table'
import { RowDetail } from '@/components/ledger/row-detail'
import { ContextSlot } from '@/components/shell/context-panel'
import { useShell } from '@/components/shell/shell-context'
import { TopBar } from '@/components/shell/top-bar'
import { Button, buttonStyles } from '@/components/ui/button'
import { Empty } from '@/components/ui/empty'
import { MenuContent, MenuItem, MenuLabel, MenuRoot, MenuTrigger } from '@/components/ui/menu'
import { Input } from '@/components/ui/input'
import { Notice } from '@/components/ui/notice'
import { Select } from '@/components/ui/select'
import { useBuildEvents } from '@/hooks/use-build-events'
import { useStartChat } from '@/hooks/use-start-chat'
import { cn } from '@/lib/cn'
import { hostOf } from '@/lib/format'

import type { CorpusReport, ExpertWithCatalog, LedgerSource, SourceSort } from '@/lib/api/types'

/**
 * The sources page: the sources this expert answers from.
 *
 * Sort is **URL state**, pushed through `startTransition`: the page is a server
 * component re-fetch, so a sorted list is a shareable link and the back button
 * works. While the transition is pending the table dims to 60% and keeps its
 * height — no spinner, and no jump when the new rows mount.
 *
 * The table is the `md`+ form and a card list below that. Both are in the HTML
 * and toggled with `hidden md:block`, so the server render is right at every
 * width.
 */
export function LedgerPage({
  expert,
  report,
  sort,
  page,
  pageSize,
  conceptFilter,
  focusSourceId,
}: {
  expert: ExpertWithCatalog
  report: CorpusReport
  sort: SourceSort
  page: number
  pageSize: number
  conceptFilter: string | null
  focusSourceId: number | null
}) {
  const router = useRouter()
  const pathname = usePathname()
  const params = useSearchParams()
  const { openContext } = useShell()
  const [pending, startTransition] = useTransition()

  const [localSelection, setLocalSelection] = useState<LedgerSource | null>(null)
  const [adding, setAdding] = useState(false)
  // Client-side over the loaded page, like the sidebar's chat filter. A Pro
  // build keeps up to sixty sources and the only way to find one was to read
  // the list.
  const [filter, setFilter] = useState('')
  const { start: startChat, starting: startingChat } = useStartChat(expert.name)
  // A viewer reads the list but cannot add to it or remove from it.
  const owner = canManage(expert)
  const [ingestJob, setIngestJob] = useState<number | null>(null)

  const navigate = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params.toString())
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key)
      else next.set(key, value)
    }
    startTransition(() => router.push(`${pathname}?${next}`, { scroll: false }))
  }

  // Waits for the worker to finish an ingest, then refreshes so the new row
  // appears — the same durable event stream the build page tails.
  useBuildEvents(ingestJob !== null ? expert.name : null, {
    onTerminal: () => {
      setIngestJob(null)
      router.refresh()
    },
  })

  // `?concept=` narrows client-side: the API filters and sorts, but has no
  // concept filter, and the page is already bounded at 500 rows. The text
  // filter runs after it, over title, author and host — the three things
  // somebody looking for one source actually remembers.
  const rows = useMemo(() => {
    const concept = conceptFilter?.toLowerCase()
    const needle = filter.trim().toLowerCase()
    return report.sources.filter((source) => {
      if (concept && !source.covered_concepts.some((c) => c.toLowerCase() === concept)) return false
      if (!needle) return true
      const host = source.url ? (hostOf(source.url) ?? '') : ''
      return `${source.title} ${source.author ?? ''} ${host}`.toLowerCase().includes(needle)
    })
  }, [report.sources, conceptFilter, filter])

  // A row deep-linked from a citation (`?source=<id>`) shows its detail on
  // arrival. Derived rather than copied into state by an effect: a click sets
  // the local selection, and until then the URL is the selection.
  const selected =
    localSelection ??
    (focusSourceId === null
      ? null
      : (report.sources.find((source) => source.id === focusSourceId) ?? null))

  const select = (source: LedgerSource) => {
    setLocalSelection(source)
    openContext()
  }

  // …and is scrolled to, or the detail panel describes a row the reader
  // cannot see: a cited source is rarely in the first screenful.
  useEffect(() => {
    if (focusSourceId === null) return
    document
      .querySelector(`tr[data-source-id="${focusSourceId}"]`)
      ?.scrollIntoView({ block: 'center' })
  }, [focusSourceId])

  const total = report.page.total_matching ?? report.sources.length
  const lastPage = Math.max(1, Math.ceil(total / pageSize))

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <TopBar
        expert={expert}
        title="Sources"
        action={
          <MenuRoot>
            {/* Styled with the button classes rather than composed onto our
                `Button` through `render`: Base UI's trigger and our own button
                wrapper both want to own the element, and the direct form is
                one component instead of three. */}
            <MenuTrigger
              aria-label="Export the sources"
              className={cn(buttonStyles({ variant: 'outline', size: 'action' }), 'shrink-0')}
            >
              <Download className="size-3.5" />
              {/* The label is hidden below `sm`, so without the `aria-label`
                  this button has no accessible name at all on a phone. */}
              <span className="hidden sm:inline">Export</span>
            </MenuTrigger>
            <MenuContent>
              <MenuLabel label="Download the sources">
                {/* Not a navigation at all: the response is a file with its own
                    `Content-Disposition`, and handing it to the browser is what
                    downloads it. `router.push` would try to render it as a page,
                    and a fetch would buffer the whole export in memory first —
                    which is why the lint rule is disabled rather than obeyed. */}
                <MenuItem
                  onClick={() => {
                    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- a file download, not a page
                    window.location.href = `/api/experts/${encodeURIComponent(expert.name)}/sources/export?format=csv&decision=accepted`
                  }}
                >
                  CSV
                </MenuItem>
                <MenuItem
                  onClick={() => {
                    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- a file download, not a page
                    window.location.href = `/api/experts/${encodeURIComponent(expert.name)}/sources/export?format=ris&decision=accepted`
                  }}
                >
                  RIS — for Zotero, Covidence, EndNote
                </MenuItem>
                <MenuItem
                  onClick={() => {
                    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- a file download, not a page
                    window.location.href = `/api/experts/${encodeURIComponent(expert.name)}/sources/export?format=bibtex&decision=accepted`
                  }}
                >
                  BibTeX — for LaTeX
                </MenuItem>
              </MenuLabel>
            </MenuContent>
          </MenuRoot>
        }
        overflow={
          <>
            {/* Not *Add a source*: it is a button in the toolbar below, and a
                menu is for what is not already on screen. */}
            <MenuItem onClick={() => router.push(`/experts/${expert.name}`)}>Overview</MenuItem>
            <MenuItem onClick={() => router.push(`/experts/${expert.name}/graph`)}>
              Concepts
            </MenuItem>
          </>
        }
      />

      <div className="scroll-col flex-1">
        <div className="space-y-3 p-3 md:p-4">
          {ingestJob !== null && (
            <Notice tone="info" title="Reading a new source">
              Peritus is reading and indexing it. It appears in the table when it is done.
            </Notice>
          )}

          {conceptFilter && (
            // The count is the filtered one. It used to read "16 sources" over
            // a table of six, because the toolbar's number came from the report
            // page while the filtering happened here.
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
              <span className="text-fg-3">
                {rows.length} of {total} {total === 1 ? 'source' : 'sources'} cover
              </span>
              <span className="inline-flex items-center gap-1 rounded-chip bg-expert-soft py-0.5 pr-1 pl-2 text-xs text-expert">
                {conceptFilter}
                <button
                  type="button"
                  onClick={() => navigate({ concept: null })}
                  aria-label="Show every source"
                  className="grid size-4 place-items-center rounded-chip transition-colors duration-(--dur-1) hover:bg-expert/20"
                >
                  <X className="size-3" />
                </button>
              </span>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            {/* From twenty rows, where reading the list stops being a way to
                find one. The sidebar uses the same threshold for chats. */}
            {report.sources.length >= 20 && (
              <Input
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Filter sources"
                aria-label="Filter sources"
                className="w-full text-xs sm:w-56"
              />
            )}

            {/* A native select below `lg`, where a sortable header row has no
                room; the headers themselves sort at `lg` and up. The options
                say "Sort:" because the closed select shows only its value —
                "Title" alone read as a filter or a column name. */}
            <Select
              aria-label="Sort by"
              value={sort}
              onChange={(event) => navigate({ sort: event.target.value, page: null })}
              className="lg:hidden"
            >
              <option value="title">Sort: Title</option>
              <option value="type">Sort: Kind</option>
              <option value="added">Sort: Added</option>
            </Select>

            {owner && (
              // The word is visible from 360px — a bare `+` said nothing about
              // what it added — while the accessible name stays the full one.
              <Button
                variant="secondary"
                size="action"
                aria-label="Add a source"
                onClick={() => setAdding(true)}
              >
                <Plus className="size-3.5" />
                {/* One text node for the flex gap to sit beside, or "Add" and
                    "a source" were two flex items and read "Add  a source". */}
                <span>
                  Add<span className="hidden sm:inline"> a source</span>
                </span>
              </Button>
            )}

            <p className="ml-auto text-xs text-fg-3">
              {filter.trim() && `${rows.length} of `}
              {total} {total === 1 ? 'source' : 'sources'}
            </p>
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
                  onSort={(next) => navigate({ sort: next, page: null })}
                  onSelect={select}
                  selectedId={selected?.id ?? null}
                  pending={pending}
                />
              </div>
              <div className="md:hidden">
                <LedgerCards
                  sources={rows}
                  onSelect={select}
                  selectedId={selected?.id ?? null}
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
                onClick={() => navigate({ page: String(page - 1) })}
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
                onClick={() => navigate({ page: String(page + 1) })}
              >
                Next
              </Button>
            </div>
          )}
        </div>
      </div>

      {selected && (
        <ContextSlot
          title="Source"
          open
          onClose={() => {
            setLocalSelection(null)
            if (focusSourceId !== null) navigate({ source: null })
          }}
        >
          <RowDetail
            source={selected}
            slug={expert.name}
            owner={owner}
            asking={startingChat}
            onAsk={(title) => void startChat(`What does “${title}” say?`)}
            onDeleted={
              owner
                ? () => {
                    setLocalSelection(null)
                    navigate({ source: null })
                    router.refresh()
                  }
                : undefined
            }
          />
        </ContextSlot>
      )}

      {owner && (
        <AddSourceDialog
          slug={expert.name}
          open={adding}
          onOpenChange={setAdding}
          onQueued={(jobId) => setIngestJob(jobId)}
        />
      )}
    </div>
  )
}
