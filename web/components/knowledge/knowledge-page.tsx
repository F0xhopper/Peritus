'use client'

import { Download, Network, Plus, X } from 'lucide-react'
import dynamic from 'next/dynamic'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from 'react'

import type { BrainCanvasHandle } from '@/components/brain/brain-canvas'
import { ListView } from '@/components/knowledge/list-view'
import { ConceptPanel, GapPanel, KeyConceptPanel, SourcePanel } from '@/components/knowledge/panels'
import { AddSourceDialog } from '@/components/ledger/add-source-dialog'
import { ContextSlot } from '@/components/shell/context-panel'
import { useShell } from '@/components/shell/shell-context'
import { TopBar } from '@/components/shell/top-bar'
import { Button, buttonStyles } from '@/components/ui/button'
import { Empty } from '@/components/ui/empty'
import { Input } from '@/components/ui/input'
import { MenuContent, MenuItem, MenuLabel, MenuRoot, MenuTrigger } from '@/components/ui/menu'
import { Notice } from '@/components/ui/notice'
import { Segmented } from '@/components/ui/segmented'
import { useBuildEvents } from '@/hooks/use-build-events'
import { toast } from 'sonner'
import { useMediaQuery } from '@/hooks/use-media-query'
import { useStartChat } from '@/hooks/use-start-chat'
import { canManage } from '@/lib/access'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import {
  litBy,
  litByCitations,
  parseCited,
  selectionFromParams,
  selectionKey,
  selectionParams,
  type BrainSelection,
} from '@/lib/brain/selection'
import { keyConceptLabel } from '@/lib/brain/paint'
import { additionSummary, removalCost } from '@/lib/brain/grow'
import type { CorpusReport, ExpertWithCatalog, MapResponse, SourceSort } from '@/lib/api/types'

export type KnowledgeView = 'map' | 'list'

/**
 * The map's code — d3, the painter, the worker — is loaded only where the Map
 * is shown. Bundled with the page it delayed hydration of the List, which is
 * the whole page on a phone, and a tap on a row landed before anything listened.
 */
const BrainCanvas = dynamic(
  () => import('@/components/brain/brain-canvas').then((module) => module.BrainCanvas),
  { ssr: false }
)

/**
 * The Knowledge page: one expert's syllabus, concepts and sources, as a Map and
 * as a List (docs/plans/expert-brain.md, phase 5). It replaced the Sources and
 * Concepts pages, which did not connect: the concept panel's only bridge to
 * the sources matched a node label against a key concept, which happened for no
 * node in any expert.
 *
 * **The selection is URL state and both views share it** — `?source=`,
 * `?node=`, `?concept=` (a key concept by label; the Overview's links already
 * use it, and in the List it still narrows the table) and `?gap=`. Switching
 * view keeps it. It is written with the History API rather than the router:
 * Next keeps `useSearchParams` in step with `pushState`/`replaceState`, and a
 * router push here would re-fetch the expert, the list and the map on every
 * click. Sort, page and `?expand=` do need the server, and go through it.
 *
 * **Which view at first paint** is the one decision the server cannot make. With
 * no `?view=`, both are in the HTML — the Map from `lg` with a fine pointer, the
 * List otherwise — toggled by CSS (web/AGENTS.md: `useMediaQuery` may not decide
 * what renders). The canvas does nothing while it has no size, so the hidden
 * one costs nothing.
 */
export function KnowledgePage({
  expert,
  report,
  map,
  sort,
  page,
  pageSize,
  expand,
}: {
  expert: ExpertWithCatalog
  report: CorpusReport
  map: MapResponse
  sort: SourceSort
  page: number
  pageSize: number
  expand: number | null
}) {
  const router = useRouter()
  const pathname = usePathname()
  const params = useSearchParams()
  const { openContext } = useShell()
  const [pending, startTransition] = useTransition()
  const { start: startChat, starting: startingChat } = useStartChat(expert.name)
  const owner = canManage(expert)
  const canvas = useRef<BrainCanvasHandle | null>(null)

  const [query, setQuery] = useState('')
  const [adding, setAdding] = useState(false)
  const [addPrefill, setAddPrefill] = useState<AddPrefill | null>(null)
  const openAdd = (prefill: AddPrefill | null = null) => {
    setAddPrefill(prefill)
    setAdding(true)
  }
  // A source being read in: drawn as a breathing square at the foot of the
  // orbit, filled once its passages are embedded, and replaced by the real one
  // when the ingest finishes (expert-brain-interactive.md, G2).
  const [ingest, setIngest] = useState<{
    jobId: number
    title: string
    embedded: boolean
    before: MapResponse
  } | null>(null)
  const landingFrom = useRef<MapResponse | null>(null)

  const viewParam = params.get('view')
  const view: KnowledgeView | null = viewParam === 'map' || viewParam === 'list' ? viewParam : null
  // Behaviour only — which view a panel's "Show in …" offers, whether a
  // selection pans the map. What renders is decided in CSS below.
  const wideAndFine = useMediaQuery('(min-width: 1024px) and (pointer: fine)')
  const shown: KnowledgeView = view ?? (wideAndFine ? 'map' : 'list')

  const selection = selectionFromParams(params, map)
  const selected = selectionKey(selection)
  const citedParam = params.get('cited')
  const lit = useMemo(() => {
    if (selection) return litBy(map, selection)
    const cited = parseCited(citedParam)
    return cited.length ? litByCitations(map, cited) : null
    // `selected` is the selection's identity; the object is new every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, selected, citedParam])
  const cited = !selection && citedParam !== null && lit !== null

  // ── the URL ───────────────────────────────────────────────────────────────

  const writeParams = useCallback(
    (changes: Record<string, string | null>, mode: 'push' | 'replace' = 'replace') => {
      const next = new URLSearchParams(window.location.search)
      for (const [key, value] of Object.entries(changes)) {
        if (value === null) next.delete(key)
        else next.set(key, value)
      }
      const search = next.toString()
      const url = search ? `${pathname}?${search}` : pathname
      if (mode === 'push') window.history.pushState(null, '', url)
      else window.history.replaceState(null, '', url)
    },
    [pathname]
  )

  /** Server data: sort, page, a sector expanded. */
  const navigate = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params.toString())
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key)
      else next.set(key, value)
    }
    startTransition(() => router.push(`${pathname}?${next}`, { scroll: false }))
  }

  const select = (next: BrainSelection | null, options: { focus?: boolean } = {}) => {
    writeParams({ ...selectionParams(next, map), cited: null })
    if (next) {
      openContext()
      if (options.focus && shown === 'map') canvas.current?.focus(next)
    }
  }

  const setView = (next: KnowledgeView) => writeParams({ view: next }, 'push')

  // The map the canvas draws: the expert's, plus a source still being read.
  const drawnMap = useMemo<MapResponse>(() => {
    if (!ingest) return map
    return {
      ...map,
      sources: [
        ...map.sources,
        {
          id: -ingest.jobId,
          title: ingest.title,
          author: null,
          kind: 'upload',
          tier: ingest.embedded ? 'secondary' : null,
          passage_count: 0,
          tags: [],
          pending: !ingest.embedded,
        },
      ],
    }
  }, [map, ingest])

  // After an ingest the page re-reads the map; when it lands, say what changed.
  // Worth having in both motion modes, and more than the product said before.
  useEffect(() => {
    const from = landingFrom.current
    if (!from || from === map) return
    landingFrom.current = null
    const summary = additionSummary(from, map)
    if (summary) toast.success(summary)
  }, [map])

  // ── search ────────────────────────────────────────────────────────────────

  const findMatches = useCallback(
    (text: string): { selection: BrainSelection; label: string; kind: string }[] => {
      const needle = text.trim().toLowerCase()
      if (!needle) return []
      const keys = map.syllabus.key_concepts
        .filter((k) => k.label.toLowerCase().includes(needle))
        .slice(0, 3)
        .map((k) => ({
          selection: { kind: 'keyConcept', index: k.index } as BrainSelection,
          label: k.label,
          kind: 'Key concept',
        }))
      const concepts = map.concepts
        .filter((c) => c.label.toLowerCase().includes(needle))
        .sort((a, b) => b.source_ids.length - a.source_ids.length)
        .slice(0, 5)
        .map((c) => ({
          selection: { kind: 'concept', id: c.id } as BrainSelection,
          label: c.label,
          kind: 'Concept',
        }))
      const sources = map.sources
        .filter((s) => `${s.title} ${s.author ?? ''}`.toLowerCase().includes(needle))
        .slice(0, 4)
        .map((s) => ({
          selection: { kind: 'source', id: s.id } as BrainSelection,
          label: s.title,
          kind: 'Source',
        }))
      return [...keys, ...concepts, ...sources]
    },
    [map]
  )
  const matches = useMemo(() => findMatches(query), [findMatches, query])
  const [searchOpen, setSearchOpen] = useState(false)

  const choose = (next: BrainSelection) => {
    select(next, { focus: true })
    setSearchOpen(false)
    if (shown === 'map') setQuery('')
  }

  // ── panel ─────────────────────────────────────────────────────────────────

  const ask = (text: string) => void startChat(text)
  const selectedLedger =
    selection?.kind === 'source'
      ? (report.sources.find((source) => source.id === selection.id) ?? null)
      : null

  // In the List a key concept is a filter — the chip over the table — not a
  // panel. On a phone the panel is a modal sheet over the very rows it would
  // explain, and closing it cleared the filter the reader had come for.
  const panelFor = selection?.kind === 'keyConcept' && shown === 'list' ? null : selection
  const panel = panelFor ? (
    panelFor.kind === 'source' ? (
      <SourcePanel
        sourceId={panelFor.id}
        ledger={selectedLedger}
        map={map}
        slug={expert.name}
        owner={owner}
        asking={startingChat}
        onAsk={(title) => ask(`What does “${title}” say?`)}
        onDeleted={
          owner
            ? () => {
                select(null)
                router.refresh()
              }
            : undefined
        }
        removalCost={removalCost(map, panelFor.id)}
        onSelect={(next) => select(next, { focus: true })}
      />
    ) : panelFor.kind === 'concept' ? (
      <ConceptPanel
        conceptId={panelFor.id}
        map={map}
        slug={expert.name}
        asking={startingChat}
        onAsk={ask}
        onSelect={(next) => select(next, { focus: true })}
      />
    ) : panelFor.kind === 'keyConcept' ? (
      <KeyConceptPanel
        index={panelFor.index}
        map={map}
        view={shown}
        asking={startingChat}
        onAsk={ask}
        onShowInList={() => writeParams({ view: 'list' }, 'push')}
        onShowOnMap={() => {
          writeParams({ view: 'map' }, 'push')
          canvas.current?.focus(panelFor)
        }}
        onExpand={
          map.computed && expand !== panelFor.index
            ? () => navigate({ expand: String(panelFor.index), view: 'map' })
            : null
        }
        onAdd={
          owner
            ? () =>
                openAdd({
                  context: `Prompted by ${map.syllabus.key_concepts[panelFor.index]?.label}. Peritus reads what you add and decides what it covers.`,
                })
            : null
        }
        onSelect={(next) => select(next, { focus: true })}
      />
    ) : (
      <GapPanel
        index={panelFor.index}
        map={map}
        owner={owner}
        onAdd={() => {
          const gap = map.syllabus.gaps[panelFor.index]
          openAdd({
            title: gap?.title,
            context: gap
              ? `For the missing text: ${gap.title}${gap.author ? ` (${gap.author})` : ''}. Peritus reads what you add and decides what it covers.`
              : undefined,
          })
        }}
        onSelect={(next) => select(next, { focus: true })}
      />
    )
  ) : null

  const panelTitle =
    selection?.kind === 'source'
      ? 'Source'
      : selection?.kind === 'concept'
        ? 'Concept'
        : selection?.kind === 'keyConcept'
          ? 'Key concept'
          : 'Missing text'

  // ── layout ────────────────────────────────────────────────────────────────

  const mapClass =
    view === 'map' ? 'block' : view === 'list' ? 'hidden' : 'hidden pointer-fine:lg:block'
  const listClass =
    view === 'list' ? 'block' : view === 'map' ? 'hidden' : 'block pointer-fine:lg:hidden'
  const conceptFilter =
    selection?.kind === 'keyConcept'
      ? (map.syllabus.key_concepts[selection.index]?.label ?? null)
      : params.get('concept')
  const expandedLabel =
    expand !== null && map.syllabus.key_concepts[expand]
      ? keyConceptLabel(map.syllabus.key_concepts[expand].label)
      : null
  const totalSources = report.page.total_matching ?? report.sources.length

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <TopBar
        expert={expert}
        title="Knowledge"
        action={
          <MenuRoot>
            {/* The button classes directly: Base UI's trigger and our button
                wrapper both want to own the element. */}
            <MenuTrigger
              aria-label="Export the sources"
              className={cn(buttonStyles({ variant: 'outline', size: 'action' }), 'shrink-0')}
            >
              <Download className="size-3.5" />
              <span className="hidden sm:inline">Export</span>
            </MenuTrigger>
            <MenuContent>
              <MenuLabel label="Download the sources">
                {(['csv', 'ris', 'bibtex'] as const).map((format) => (
                  <MenuItem
                    key={format}
                    onClick={() => {
                      // A file download, not a page: the response carries its
                      // own `Content-Disposition`.
                      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- a file download
                      window.location.href = `/api/experts/${encodeURIComponent(expert.name)}/sources/export?format=${format}&decision=accepted`
                    }}
                  >
                    {format === 'csv'
                      ? 'CSV'
                      : format === 'ris'
                        ? 'RIS — for Zotero, Covidence, EndNote'
                        : 'BibTeX — for LaTeX'}
                  </MenuItem>
                ))}
              </MenuLabel>
            </MenuContent>
          </MenuRoot>
        }
        overflow={
          <MenuItem onClick={() => router.push(`/experts/${expert.name}`)}>Overview</MenuItem>
        }
      />

      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border-soft px-3 py-2 md:px-4">
        <h1 className="sr-only">Knowledge</h1>
        <ViewToggle view={view} onChange={setView} />

        <div className="relative order-last w-full sm:order-none sm:w-64">
          <Input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setSearchOpen(true)
            }}
            onFocus={() => {
              setSearchOpen(true)
              canvas.current?.engage()
            }}
            onKeyDown={(event) => {
              canvas.current?.engage()
              // Matched from the field's current value, not the `matches` this
              // render closed over: typed quickly, Enter would otherwise act on
              // the previous query's results.
              if (event.key === 'Enter') {
                const first = findMatches(event.currentTarget.value)[0]
                if (first) choose(first.selection)
              }
              if (event.key === 'Escape') setSearchOpen(false)
            }}
            onBlur={() => setTimeout(() => setSearchOpen(false), 150)}
            placeholder="Find a source or concept"
            aria-label="Find a source or concept"
            className="w-full text-xs"
          />
          {searchOpen && matches.length > 0 && (
            <ul className="absolute top-full right-0 left-0 z-20 mt-1 overflow-hidden rounded-card border border-border bg-raised shadow-lg shadow-black/25">
              {matches.map((match) => (
                <li key={selectionKey(match.selection)}>
                  <button
                    type="button"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => choose(match.selection)}
                    className="flex h-(--row-h) w-full items-center gap-2 px-2 text-left text-sm text-fg-2 transition-colors duration-(--dur-1) hover:bg-border hover:text-fg"
                  >
                    <span className="min-w-0 flex-1 truncate">{match.label}</span>
                    <span className="shrink-0 text-xs text-fg-3">{match.kind}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {owner && (
          <Button
            variant="secondary"
            size="action"
            aria-label="Add a source"
            onClick={() => openAdd()}
          >
            <Plus className="size-3.5" />
            <span>
              Add<span className="hidden sm:inline"> a source</span>
            </span>
          </Button>
        )}

        <p className="ml-auto text-xs text-fg-3">
          {formatNumber(totalSources)} {totalSources === 1 ? 'source' : 'sources'}
          {map.computed && map.totals.concepts !== null && (
            <span
              className={
                view === 'map'
                  ? undefined
                  : view === 'list'
                    ? 'hidden'
                    : 'hidden pointer-fine:lg:inline'
              }
            >
              {' · '}
              {formatNumber(map.totals.concepts_shown)} of {formatNumber(map.totals.concepts)}{' '}
              concepts
            </span>
          )}
        </p>
      </div>

      {ingest && (
        <IngestWatcher
          key={ingest.jobId}
          slug={expert.name}
          onEmbedded={() =>
            setIngest((current) =>
              current && !current.embedded ? { ...current, embedded: true } : current
            )
          }
          onFinished={(failure) => {
            if (failure) toast.error(failure)
            else landingFrom.current = ingest.before
            setIngest(null)
            router.refresh()
          }}
        />
      )}

      {ingest !== null && (
        <div className="shrink-0 px-3 pt-3 md:px-4">
          <Notice tone="info" title="Reading a new source">
            Peritus is reading and indexing it. It appears here when it is done.
          </Notice>
        </div>
      )}

      <div className={cn('relative min-h-0 flex-1', mapClass)}>
        {view === 'list' ? null : !map.computed && map.sources.length === 0 ? (
          <div className="grid h-full place-items-center p-4">
            <div className="w-full max-w-sm text-center">
              <Empty icon={Network}>
                Nothing to map yet. The syllabus and the sources appear here as the build finds
                them, and concepts once they are extracted.
              </Empty>
              <Button
                variant="outline"
                size="md"
                className="mt-3"
                onClick={() => router.push(`/experts/${expert.name}/build`)}
              >
                Watch the build
              </Button>
            </div>
          </div>
        ) : (
          <>
            <BrainCanvas
              map={drawnMap}
              onDropFile={owner ? (file) => openAdd({ file }) : undefined}
              expert={expert}
              selection={selection}
              lit={lit}
              cited={cited}
              onSelect={(next) => select(next)}
              handleRef={canvas}
            />
            {!map.computed && (
              <p className="pointer-events-none absolute right-3 bottom-3 left-3 mx-auto w-fit max-w-full rounded-row bg-panel/90 px-2 py-1 text-center text-xs text-fg-3">
                Concepts are still being extracted. This expert may already be answering questions.
              </p>
            )}
            {cited && (
              <div className="absolute top-3 left-3 flex items-center gap-1 rounded-row bg-panel/90 py-1 pr-1 pl-2 text-xs text-fg-2">
                The sources one answer cited
                <button
                  type="button"
                  aria-label="Stop showing the answer's sources"
                  onClick={() => writeParams({ cited: null })}
                  className="grid size-(--icon-btn-sm) place-items-center rounded-chip text-fg-3 hover:bg-raised hover:text-fg"
                >
                  <X className="size-3" />
                </button>
              </div>
            )}
            {expandedLabel && (
              <div className="absolute top-3 right-3 flex items-center gap-1 rounded-row bg-panel/90 py-1 pr-1 pl-2 text-xs text-fg-2">
                Every concept in {expandedLabel}
                <button
                  type="button"
                  aria-label="Show the shared concepts only"
                  onClick={() => navigate({ expand: null })}
                  className="grid size-(--icon-btn-sm) place-items-center rounded-chip text-fg-3 hover:bg-raised hover:text-fg"
                >
                  <X className="size-3" />
                </button>
              </div>
            )}
          </>
        )}
      </div>

      <div className={cn('scroll-col min-h-0 flex-1', listClass)}>
        <ListView
          report={report}
          sort={sort}
          page={page}
          pageSize={pageSize}
          conceptFilter={conceptFilter}
          filter={shown === 'list' ? query : ''}
          selectedId={selection?.kind === 'source' ? selection.id : null}
          pending={pending}
          onSelect={(source) => select({ kind: 'source', id: source.id })}
          onClearConcept={() => writeParams({ concept: null })}
          onNavigate={navigate}
        />
      </div>

      {panel && (
        <ContextSlot title={panelTitle} snapPoints={[0.45, 0.92]} open onClose={() => select(null)}>
          {panel}
        </ContextSlot>
      )}

      {owner && (
        <AddSourceDialog
          slug={expert.name}
          open={adding}
          onOpenChange={setAdding}
          prefill={addPrefill}
          onQueued={(jobId, title) => setIngest({ jobId, title, embedded: false, before: map })}
        />
      )}
    </div>
  )
}

/**
 * Map | List. With no `?view=` the active option depends on the device, which
 * only CSS knows at first paint — so both forms are rendered and one is hidden.
 */
function ViewToggle({
  view,
  onChange,
}: {
  view: KnowledgeView | null
  onChange: (view: KnowledgeView) => void
}) {
  const options = [
    { value: 'map' as const, label: 'Map' },
    { value: 'list' as const, label: 'List' },
  ]
  if (view) return <Segmented label="View" options={options} value={view} onChange={onChange} />
  return (
    <>
      <Segmented
        label="View"
        options={options}
        value="map"
        onChange={onChange}
        className="hidden pointer-fine:lg:inline-flex"
      />
      <Segmented
        label="View"
        options={options}
        value="list"
        onChange={onChange}
        className="pointer-fine:lg:hidden"
      />
    </>
  )
}

type AddPrefill = { title?: string; context?: string; file?: File | null }

/**
 * Tails one ingest job. Keyed by the job, because `useBuildEvents` stops for
 * good at a terminal event: a second source added from the same page would
 * otherwise never be watched.
 */
function IngestWatcher({
  slug,
  onEmbedded,
  onFinished,
}: {
  slug: string
  onEmbedded: () => void
  onFinished: (failure: string | null) => void
}) {
  const { state } = useBuildEvents(slug, {
    refreshOnTerminal: false,
    onTerminal: (final) => {
      onFinished(
        final.terminal?.kind === 'done'
          ? null
          : (final.terminal?.message ?? 'That source could not be read.')
      )
    },
  })
  const embedded = state.rows.some(
    (row) => (row.raw as { type?: string })?.type === 'upload_embedded'
  )
  useEffect(() => {
    if (embedded) onEmbedded()
  }, [embedded, onEmbedded])
  return null
}
