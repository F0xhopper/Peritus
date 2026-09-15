'use client'

import { Columns3, Download, Plus, Table as TableIcon } from 'lucide-react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useState, useTransition } from 'react'

import { stashAskDraft } from '@/components/chat/new-chat-composer'
import { AddSourceDialog } from '@/components/ledger/add-source-dialog'
import { LedgerCards } from '@/components/ledger/ledger-cards'
import { COLUMNS, LedgerTable } from '@/components/ledger/ledger-table'
import { RowDetail } from '@/components/ledger/row-detail'
import { SelectionSection } from '@/components/ledger/selection-section'
import { ContextSlot } from '@/components/shell/context-panel'
import { useShell } from '@/components/shell/shell-context'
import { TopBar } from '@/components/shell/top-bar'
import { Button, buttonStyles } from '@/components/ui/button'
import { Empty } from '@/components/ui/empty'
import { MenuContent, MenuItem, MenuLabel, MenuRoot, MenuTrigger } from '@/components/ui/menu'
import { Notice } from '@/components/ui/notice'
import { Segmented } from '@/components/ui/segmented'
import { Select } from '@/components/ui/select'
import { useBuildEvents } from '@/hooks/use-build-events'
import { useStoredPreference } from '@/hooks/use-stored-preference'
import { cn } from '@/lib/cn'
import { formatPercent, plural } from '@/lib/format'

import type {
  CorpusReport,
  ExpertWithCatalog,
  LedgerSource,
  SelectionBlock,
  SourceDecision,
  SourceSort,
} from '@/lib/api/types'

/**
 * The sources page.
 *
 * Filter and sort are **URL state**, pushed through `startTransition`: the page
 * is a server component re-fetch, so a filtered ledger is a shareable link and
 * the back button works. While the transition is pending the table dims to 60%
 * and keeps its height — no spinner, and no jump when the new rows mount.
 *
 * The table is the `lg`+ form, the same table inside a horizontal scroller at
 * `md`, and a card list below that. All three are in the HTML and toggled with
 * `hidden lg:block`, so the server render is right at every width.
 */
const DEFAULT_COLUMNS = new Set(['title', 'type', 'decision', 'quality', 'relevance', 'reason'])
const COLUMN_PREFERENCE_KEY = 'peritus:ledger-columns'

export function LedgerPage({
  expert,
  report,
  decision,
  sort,
  page,
  pageSize,
  conceptFilter,
  focusSourceId,
  selection = null,
}: {
  expert: ExpertWithCatalog
  report: CorpusReport
  decision: SourceDecision
  sort: SourceSort
  page: number
  pageSize: number
  conceptFilter: string | null
  focusSourceId: number | null
  /** The screening-flow report's selection block; null when the report failed or predates it. */
  selection?: SelectionBlock | null
}) {
  const router = useRouter()
  const pathname = usePathname()
  const params = useSearchParams()
  const { openContext } = useShell()
  const [pending, startTransition] = useTransition()

  const [localSelection, setLocalSelection] = useState<LedgerSource | null>(null)
  const [adding, setAdding] = useState(false)
  const [ingestJob, setIngestJob] = useState<number | null>(null)

  // A per-viewer convenience, so `localStorage` is the right home for it — it
  // never needs to reach another device or the server.
  const parseColumns = useCallback((raw: string) => {
    const keys = JSON.parse(raw) as unknown
    if (!Array.isArray(keys) || keys.length === 0) return null
    const set = new Set(keys.filter((key): key is string => typeof key === 'string'))
    // The title column is the row's identity; without it a row is anonymous.
    set.add('title')
    return set
  }, [])
  const [visible, setVisible] = useStoredPreference(
    COLUMN_PREFERENCE_KEY,
    DEFAULT_COLUMNS,
    parseColumns,
  )

  const toggleColumn = (key: string) => {
    const next = new Set(visible)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    next.add('title')
    setVisible(next, (value) => JSON.stringify([...value]))
  }

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

  // `?concept=` narrows client-side: the API filters by decision and sorts, but
  // has no concept filter, and the page is already bounded at 500 rows.
  const rows = useMemo(() => {
    if (!conceptFilter) return report.sources
    const needle = conceptFilter.toLowerCase()
    return report.sources.filter((source) =>
      source.covered_concepts.some((concept) => concept.toLowerCase() === needle),
    )
  }, [report.sources, conceptFilter])

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
  const unavailable = collectUnavailable(report)

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
                {/* A full-page navigation, so the browser handles the streamed
                    response and the API's own `Content-Disposition` names the
                    file. A fetch would buffer it in memory first. */}
                <MenuItem
                  onClick={() => {
                    window.location.href = `/api/experts/${encodeURIComponent(expert.name)}/sources/export?format=csv&decision=${decision}`
                  }}
                >
                  CSV
                </MenuItem>
                <MenuItem
                  onClick={() => {
                    window.location.href = `/api/experts/${encodeURIComponent(expert.name)}/sources/export?format=ris&decision=${decision}`
                  }}
                >
                  RIS — for Zotero, Covidence, EndNote
                </MenuItem>
              </MenuLabel>
            </MenuContent>
          </MenuRoot>
        }
        overflow={
          <>
            <MenuItem onClick={() => setAdding(true)}>Add a source</MenuItem>
            <MenuItem onClick={() => router.push(`/experts/${expert.name}`)}>Overview</MenuItem>
            <MenuItem onClick={() => router.push(`/experts/${expert.name}/graph`)}>Graph</MenuItem>
          </>
        }
      />

      <div className="scroll-col flex-1">
        <div className="space-y-3 p-3 md:p-4">
          {/* The provenance banner, when older rows genuinely lack fields. */}
          {!report.provenance.complete && (
            <Notice tone="info" title="Some rows are missing provenance">
              {report.provenance.note} Nothing is backfilled — a guessed DOI or a guessed
              full-text method would put a fabrication into the record.
            </Notice>
          )}

          {unavailable.length > 0 && (
            <Notice tone="info" title="Some counts were not recorded">
              <ul className="space-y-1">
                {unavailable.map((reason) => (
                  <li key={reason} className="text-xs">
                    {reason}
                  </li>
                ))}
              </ul>
            </Notice>
          )}

          {ingestJob !== null && (
            <Notice tone="info" title="Reading a new source">
              Peritus is reading and indexing it. It appears in the table when it is done.
            </Notice>
          )}

          {conceptFilter && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-fg-3">Covering</span>
              <span className="rounded-chip bg-expert-soft px-2 py-0.5 text-xs text-expert">
                {conceptFilter}
              </span>
              <button
                type="button"
                onClick={() => navigate({ concept: null })}
                className="text-xs text-fg-3 underline-offset-2 hover:text-fg-2 hover:underline"
              >
                clear
              </button>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Segmented
              label="Decision"
              value={decision}
              onChange={(next) => navigate({ decision: next, page: null })}
              options={[
                { value: 'all', label: 'All', count: report.totals.considered },
                { value: 'accepted', label: 'Kept', count: report.totals.accepted },
                { value: 'rejected', label: 'Dropped', count: report.totals.rejected },
              ]}
            />

            {/* A native select below `lg`, where a sortable header row has no
                room; the headers themselves sort at `lg` and up. */}
            <Select
              aria-label="Sort by"
              value={sort}
              onChange={(event) => navigate({ sort: event.target.value, page: null })}
              className="lg:hidden"
            >
              <option value="decision">Decision</option>
              <option value="quality">Quality</option>
              <option value="relevance">Relevance</option>
              <option value="title">Title</option>
              <option value="type">Type</option>
              <option value="discovered_via">How found</option>
              <option value="added">Added</option>
            </Select>

            <MenuRoot>
              <MenuTrigger
                className={cn(buttonStyles({ variant: 'ghost', size: 'md' }), 'hidden lg:inline-flex')}
              >
                <Columns3 className="size-3.5" />
                Columns
              </MenuTrigger>
              <MenuContent align="start">
                <MenuLabel label="Show">
                  {COLUMNS.map((column) => (
                  <MenuItem
                    key={column.key}
                    closeOnClick={false}
                    disabled={column.key === 'title'}
                    onClick={() => toggleColumn(column.key)}
                  >
                    <span
                      aria-hidden="true"
                      className={cn(
                        'grid size-3.5 place-items-center rounded-[3px] border',
                        visible.has(column.key)
                          ? 'border-expert bg-expert text-accent-fg'
                          : 'border-border',
                      )}
                    >
                      {visible.has(column.key) && '✓'}
                    </span>
                      {column.label}
                    </MenuItem>
                  ))}
                </MenuLabel>
              </MenuContent>
            </MenuRoot>

            <Button
              variant="secondary"
              size="action"
              aria-label="Add a source"
              onClick={() => setAdding(true)}
            >
              <Plus className="size-3.5" />
              <span className="hidden sm:inline">Add a source</span>
            </Button>

            <p className="ml-auto text-xs text-fg-3">
              {formatPercent(report.totals.acceptance_rate, 1)} kept ·{' '}
              {plural(report.by_search.distinct_searches, 'search', 'searches')}
            </p>
          </div>

          {rows.length === 0 ? (
            <Empty icon={TableIcon}>
              {report.totals.considered === 0
                ? 'This expert has no screening record yet — nothing has been searched.'
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
                  visible={visible}
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

          <SelectionSection selection={selection} />

          <p className="pt-2 text-xs leading-relaxed text-fg-3">{report.method_statement}</p>
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
            onAsk={(title) => {
              stashAskDraft(expert.name, `What does “${title}” say?`)
              router.push(`/experts/${expert.name}#ask`)
            }}
            onDeleted={() => {
              setLocalSelection(null)
              navigate({ source: null })
              router.refresh()
            }}
          />
        </ContextSlot>
      )}

      <AddSourceDialog
        slug={expert.name}
        open={adding}
        onOpenChange={setAdding}
        onQueued={(jobId) => setIngestJob(jobId)}
      />
    </div>
  )
}

/**
 * The `*_unavailable_reason` strings the report carries.
 *
 * Surfaced rather than dropped: a count the system does not persist is returned
 * as null *with a reason*, and rendering the gap is the whole point of the
 * convention. A zero here would be a fabrication.
 */
function collectUnavailable(report: CorpusReport): string[] {
  const out: string[] = []
  for (const [key, value] of Object.entries(report as unknown as Record<string, unknown>)) {
    if (key.endsWith('_unavailable_reason') && typeof value === 'string' && value) out.push(value)
  }
  return out
}
