'use client'

import {
  Download,
  Maximize,
  Minus,
  Network,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  X,
} from 'lucide-react'
import dynamic from 'next/dynamic'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from 'react'

import type { BrainCanvasHandle } from '@/components/brain/brain-canvas'
import type { GraphCanvasHandle } from '@/components/graph/graph-canvas'
import { NodeDetail } from '@/components/graph/node-detail'
import { GraphLimit } from '@/components/knowledge/graph-limit'
import { KindIcon, MarkGlyph, type MapMark } from '@/components/knowledge/kind-icon'
import { ListView } from '@/components/knowledge/list-view'
import { KnowledgeOverview, type OverviewPreview } from '@/components/knowledge/overview'
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
import { useExpertGraph } from '@/hooks/use-expert-graph'
import { useExpertOutline, useOutlineSections } from '@/hooks/use-expert-outline'
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
import { describeFilter, litByFilter, parseTier, type SourceFilter } from '@/lib/brain/overview'
import { parseGraphLimit } from '@/lib/graph/limits'
import { parseSourceKindId } from '@/lib/source-kind'
import type {
  CorpusReport,
  ExpertWithCatalog,
  GraphNode,
  MapResponse,
  SourceSort,
} from '@/lib/api/types'

export type KnowledgeView = 'map' | 'flow' | 'graph' | 'outline' | 'list'

const VIEWS: readonly KnowledgeView[] = ['map', 'flow', 'graph', 'outline', 'list']

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
 * The Flow view is client-only for a different reason: its rows are sized by
 * the pointer and its columns by the container, and the server knows neither.
 */
const FlowView = dynamic(
  () => import('@/components/knowledge/flow-view').then((module) => module.FlowView),
  { ssr: false }
)

/** And the Graph view's — d3-force, the quadtree, its worker — only where it is opened. */
const GraphTab = dynamic(
  () => import('@/components/knowledge/graph-tab').then((module) => module.GraphTab),
  { ssr: false }
)

/**
 * The Outline is DOM and small, and is still loaded apart: it is only ever asked
 * for, and everything bundled with the page is paid for before the List — the
 * whole page on a phone — can answer a tap.
 */
const OutlineView = dynamic(
  () => import('@/components/knowledge/outline-view').then((module) => module.OutlineView),
  { ssr: false }
)

/**
 * The Knowledge page: one expert's syllabus, concepts and sources, as a Map, a
 * Flow, a Graph, an Outline and a List, beside an Overview of them
 * (docs/plans/expert-brain.md, phase 5). It replaced the Sources and
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
  const view: KnowledgeView | null = VIEWS.find((name) => name === viewParam) ?? null
  // Behaviour only — which view a panel's "Show in …" offers, whether a
  // selection pans the map. What renders is decided in CSS below.
  const wideAndFine = useMediaQuery('(min-width: 1024px) and (pointer: fine)')
  const shown: KnowledgeView = view ?? (wideAndFine ? 'map' : 'list')

  const selection = selectionFromParams(params, map)
  const selected = selectionKey(selection)
  const citedParam = params.get('cited')
  const kindParam = params.get('kind')
  const tierParam = params.get('tier')
  const filter = useMemo<SourceFilter>(
    () => ({ kind: parseSourceKindId(kindParam), tier: parseTier(tierParam) }),
    [kindParam, tierParam]
  )
  // What resting on a row of the Overview would light, before it is chosen.
  const [preview, setPreview] = useState<OverviewPreview | null>(null)
  const previewKey = !preview
    ? null
    : preview.kind === 'filter'
      ? `filter:${preview.filter.kind}:${preview.filter.tier}`
      : selectionKey(preview)

  const citedLit = useMemo(() => {
    const ids = parseCited(citedParam)
    return ids.length ? litByCitations(map, ids) : null
  }, [map, citedParam])
  // One thing is lit at a time, and the more deliberate act wins: something
  // selected, then an answer's citations, then what the pointer rests on in the
  // Overview, then the standing filter.
  const lit = useMemo(() => {
    if (selection) return litBy(map, selection)
    if (citedLit) return citedLit
    if (preview) {
      return preview.kind === 'filter' ? litByFilter(map, preview.filter) : litBy(map, preview)
    }
    return litByFilter(map, filter)
    // `selected` and `previewKey` are identities; the objects are new every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, selected, citedLit, previewKey, filter])
  const cited = !selection && citedLit !== null
  const [overviewOpen, setOverviewOpen] = useState(true)

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
    // The row that was being previewed may be about to leave the page — at `xl`
    // the Overview gives its column to the panel — and a row that unmounts under
    // the pointer never says the pointer left.
    setPreview(null)
    // One thing is open at a time: a node of the Graph, or a selection.
    if (next) setGraphNode(null)
    writeParams({ ...selectionParams(next, map), cited: null })
    if (next) {
      openContext()
      if (options.focus && shown === 'map') canvas.current?.focus(next)
      // A concept chosen from the search or a panel is centred on the Graph too,
      // where the Graph draws it.
      if (shown === 'graph' && next.kind === 'concept') graphCanvas.current?.focusNode(next.id)
    }
  }

  const setView = (next: KnowledgeView) => writeParams({ view: next }, 'push')

  // ── the graph ─────────────────────────────────────────────────────────────

  // Fetched when the Graph view is first opened, never before: up to fifteen
  // hundred nodes that the other three views do not draw.
  const limit = parseGraphLimit(params.get('limit'))
  const graphState = useExpertGraph(expert.name, limit, view === 'graph')
  const graphCanvas = useRef<GraphCanvasHandle | null>(null)
  /**
   * The Graph's own selection, beside the page's. A node there is a concept
   * **or a claim**, and the page's selection — and the map's concept endpoint
   * behind its panel — knows only concepts. So the Graph keeps its original
   * panel (`NodeDetail`), and whichever of the two was opened last is the one
   * that shows.
   */
  const [graphNode, setGraphNode] = useState<GraphNode | null>(null)
  const selectGraphNode = (node: GraphNode | null, options: { focus?: boolean } = {}) => {
    setGraphNode(node)
    if (!node) return
    setPreview(null)
    writeParams({ ...selectionParams(null, map), cited: null })
    openContext()
    if (options.focus) graphCanvas.current?.focusNode(node.id)
  }
  // The concepts the page has lit, which are the Graph's node ids too.
  const graphLit = lit?.concepts ?? null

  // ── the outline ───────────────────────────────────────────────────────────

  // Fetched when the Outline is first opened, like the Graph: works, parts and
  // how each was read. What each part establishes is read a work at a time.
  const outlineState = useExpertOutline(expert.name, view === 'outline')
  const outlineSections = useOutlineSections(expert.name)

  const setFilter = (next: SourceFilter) => {
    setPreview(null)
    writeParams({ kind: next.kind, tier: next.tier })
  }

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

  const graphNodes = shown === 'graph' ? (graphState.graph?.nodes ?? null) : null
  const findMatches = useCallback(
    (text: string): SearchMatch[] => {
      const needle = text.trim().toLowerCase()
      if (!needle) return []
      const keys = map.syllabus.key_concepts
        .filter((k) => k.label.toLowerCase().includes(needle))
        .slice(0, 3)
        .map((k) => ({
          key: `key:${k.index}`,
          selection: { kind: 'keyConcept', index: k.index } as BrainSelection,
          label: k.label,
          kind: 'Key concept',
        }))
      // On the Graph the concepts are the Graph's own nodes — more of them than
      // the Map draws, and claims among them — and choosing one opens it there.
      const concepts: SearchMatch[] = graphNodes
        ? graphNodes
            .filter((node) => node.label.toLowerCase().includes(needle))
            .slice(0, 6)
            .map((node) => ({
              key: `graph:${node.id}`,
              selection: { kind: 'concept', id: node.id } as BrainSelection,
              label: node.label,
              kind: node.node_type === 'claim' ? 'Claim' : 'Concept',
              node,
            }))
        : map.concepts
            .filter((c) => c.label.toLowerCase().includes(needle))
            .sort((a, b) => b.source_ids.length - a.source_ids.length)
            .slice(0, 5)
            .map((c) => ({
              key: `concept:${c.id}`,
              selection: { kind: 'concept', id: c.id } as BrainSelection,
              label: c.label,
              kind: 'Concept',
            }))
      const sources = map.sources
        .filter((s) => `${s.title} ${s.author ?? ''}`.toLowerCase().includes(needle))
        .slice(0, 4)
        .map((s) => ({
          key: `source:${s.id}`,
          selection: { kind: 'source', id: s.id } as BrainSelection,
          label: s.title,
          kind: 'Source',
          type: s.kind,
        }))
      return [...keys, ...concepts, ...sources]
    },
    [map, graphNodes]
  )
  const matches = useMemo(() => findMatches(query), [findMatches, query])
  const [searchOpen, setSearchOpen] = useState(false)

  const choose = (match: SearchMatch) => {
    if (match.node) selectGraphNode(match.node, { focus: true })
    else select(match.selection, { focus: true })
    setSearchOpen(false)
    // In the List the text goes on narrowing the rows; elsewhere it has done
    // its job — in the Outline too, where what was chosen opens and is scrolled
    // to, and a narrowed list around it would hide where it sits.
    if (shown !== 'list') setQuery('')
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
        view={shown === 'list' ? 'list' : 'map'}
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

  const graphPanel =
    shown === 'graph' && graphNode && graphState.graph ? (
      <NodeDetail
        node={graphNode}
        edges={graphState.graph.edges}
        nodes={graphState.graph.nodes}
        slug={expert.name}
        keyConcepts={expert.key_concepts}
        onFocus={(node) => selectGraphNode(node, { focus: true })}
        onAsk={ask}
        asking={startingChat}
        onShowOnMap={
          map.concepts.some((concept) => concept.id === graphNode.id)
            ? () => {
                const id = graphNode.id
                writeParams({ view: 'map' }, 'push')
                select({ kind: 'concept', id })
                canvas.current?.focus({ kind: 'concept', id })
              }
            : null
        }
        limitControl={
          <GraphLimit
            id="graph-limit-sheet"
            limit={limit}
            pending={graphState.pending}
            onLimit={(next) => writeParams({ limit: String(next) })}
            className="bg-transparent px-0 lg:hidden"
          />
        }
      />
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

  const mapClass = view === 'map' ? 'block' : view ? 'hidden' : 'hidden pointer-fine:lg:block'
  const listClass = view === 'list' ? 'block' : view ? 'hidden' : 'block pointer-fine:lg:hidden'
  // Nothing found yet: no syllabus, no sources, no concepts.
  const nothingYet = !map.computed && map.sources.length === 0
  const hasOverview = map.sources.length > 0 || map.syllabus.key_concepts.length > 0
  const filterLabel = describeFilter(filter)
  const overview = (compact: boolean) => (
    <KnowledgeOverview
      map={map}
      selection={selection}
      filter={filter}
      compact={compact}
      onSelect={(next) => select(next, { focus: true })}
      onFilter={setFilter}
      onPreview={compact ? undefined : setPreview}
    />
  )
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

        {/* It gives way before the row wraps: with the panel open beside it the
            toolbar is 760px, and a second row pushed the map down on every
            selection. */}
        <div className="relative order-last w-full sm:order-none sm:w-auto sm:max-w-64 sm:min-w-40 sm:flex-1">
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
                if (first) choose(first)
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
                <li key={match.key}>
                  <button
                    type="button"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => choose(match)}
                    className="flex h-(--row-h) w-full items-center gap-2 px-2 text-left text-sm text-fg-2 transition-colors duration-(--dur-1) hover:bg-border hover:text-fg"
                  >
                    {match.selection.kind === 'source' ? (
                      <KindIcon type={match.type} className="text-fg-3" />
                    ) : (
                      <MarkGlyph
                        mark={match.selection.kind === 'keyConcept' ? 'keyConcept' : 'concept'}
                        className="mx-px text-fg-3"
                      />
                    )}
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

        {filterLabel && (
          <span className="inline-flex h-(--row-h) items-center gap-1 rounded-row bg-expert-soft pr-1 pl-2.5 text-xs text-expert">
            {filter.kind && <KindIcon kind={filter.kind} className="size-3" />}
            {filterLabel}
            <button
              type="button"
              onClick={() => setFilter({ kind: null, tier: null })}
              aria-label="Show every source"
              className="grid size-(--icon-btn-sm) place-items-center rounded-chip transition-colors duration-(--dur-1) hover:bg-expert/20 pointer-fine:size-5"
            >
              <X className="size-3" />
            </button>
          </span>
        )}

        <p className="ml-auto text-xs text-fg-3">
          {formatNumber(totalSources)} {totalSources === 1 ? 'source' : 'sources'}
          {map.computed && map.totals.concepts !== null && (
            <span
              className={
                view === 'list' || view === 'graph' || view === 'outline'
                  ? 'hidden'
                  : view
                    ? undefined
                    : 'hidden pointer-fine:lg:inline'
              }
            >
              {' · '}
              {formatNumber(map.totals.concepts_shown)} of {formatNumber(map.totals.concepts)}{' '}
              concepts
            </span>
          )}
        </p>

        {hasOverview && (
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={overviewOpen ? 'Hide the overview' : 'Show the overview'}
            aria-pressed={overviewOpen}
            onClick={() => {
              setPreview(null)
              setOverviewOpen((open) => !open)
            }}
            className="hidden lg:inline-flex"
          >
            {overviewOpen ? (
              <PanelRightClose className="size-3.5" />
            ) : (
              <PanelRightOpen className="size-3.5" />
            )}
          </Button>
        )}
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

      <div className="flex min-h-0 flex-1">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className={cn('relative min-h-0 flex-1', mapClass)}>
            {/* Only where the Map can show: asked for, or the CSS-decided default. */}
            {view !== null && view !== 'map' ? null : nothingYet ? (
              <NothingYet onWatch={() => router.push(`/experts/${expert.name}/build`)} />
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
                  <p className="pointer-events-none absolute right-3 bottom-14 left-3 mx-auto w-fit max-w-full rounded-row border border-border-soft bg-panel/90 px-3 py-1 text-center text-xs text-fg-3">
                    Concepts are still being extracted. This expert may already be answering
                    questions.
                  </p>
                )}
                {cited && <CitedChip onClear={() => writeParams({ cited: null })} />}
                {expandedLabel && (
                  <div className="absolute top-3 right-3 flex items-center gap-1 rounded-row border border-border-soft bg-panel/90 py-1 pr-1 pl-3 text-xs text-fg-2">
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
                <MapLegend disputed={map.concepts.some((concept) => concept.disputes > 0)} />
                <div className="absolute right-3 bottom-3 flex items-center gap-0.5 rounded-row border border-border-soft bg-panel/90 p-0.5">
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Zoom out"
                    onClick={() => canvas.current?.zoomBy(1 / 1.5)}
                  >
                    <Minus className="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Zoom in"
                    onClick={() => canvas.current?.zoomBy(1.5)}
                  >
                    <Plus className="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Fit the whole map"
                    onClick={() => canvas.current?.reset()}
                  >
                    <Maximize className="size-3.5" />
                  </Button>
                </div>
              </>
            )}
          </div>

          {view === 'graph' && (
            <div className="relative min-h-0 flex-1">
              <GraphTab
                graph={graphState.graph}
                error={graphState.error}
                pending={graphState.pending}
                limit={limit}
                selectedId={graphNode?.id ?? null}
                lit={graphLit}
                onLimit={(next) => writeParams({ limit: String(next) })}
                onSelect={(node) => selectGraphNode(node)}
                onWatchBuild={() => router.push(`/experts/${expert.name}/build`)}
                handleRef={graphCanvas}
              />
            </div>
          )}

          {view === 'flow' && (
            <div className="relative min-h-0 flex-1">
              {nothingYet ? (
                <NothingYet onWatch={() => router.push(`/experts/${expert.name}/build`)} />
              ) : (
                <>
                  <FlowView
                    map={map}
                    selection={selection}
                    lit={lit}
                    onSelect={(next) => select(next)}
                  />
                  {cited && <CitedChip bottom onClear={() => writeParams({ cited: null })} />}
                </>
              )}
            </div>
          )}

          {view === 'outline' && (
            <div className="scroll-col min-h-0 flex-1">
              <OutlineView
                outline={outlineState.outline}
                error={outlineState.error}
                slug={expert.name}
                litSources={lit?.sources ?? null}
                keyConcept={selection?.kind === 'keyConcept' ? selection.index : null}
                selectedSourceId={selection?.kind === 'source' ? selection.id : null}
                filter={query}
                sections={outlineSections.loaded}
                onLoadSections={outlineSections.load}
                onSelectSource={(id) => select({ kind: 'source', id })}
                onWatchBuild={() => router.push(`/experts/${expert.name}/build`)}
              />
            </div>
          )}

          <div className={cn('scroll-col min-h-0 flex-1', listClass)}>
            {/* Below `lg` there is no column to stand in, so the Overview folds
                above the sources it summarises. */}
            {hasOverview && (
              <div className="px-3 pt-3 md:px-4 md:pt-4 lg:hidden">
                <div className="rounded-card border border-border-soft bg-panel p-3">
                  {overview(true)}
                </div>
              </div>
            )}
            <ListView
              report={report}
              sort={sort}
              page={page}
              pageSize={pageSize}
              conceptFilter={conceptFilter}
              sourceFilter={filter}
              filter={shown === 'list' ? query : ''}
              selectedId={selection?.kind === 'source' ? selection.id : null}
              pending={pending}
              onSelect={(source) => select({ kind: 'source', id: source.id })}
              onClearConcept={() => writeParams({ concept: null })}
              onNavigate={navigate}
            />
          </div>
        </div>

        {/* The Overview stands where a selection's panel opens. From `xl` that
            panel is an inline column of the same width, so the two swap and
            the view between them keeps its size; at `lg` the panel is an
            overlay and simply covers it. */}
        {hasOverview && overviewOpen && (
          <div
            className={cn(
              'scroll-col hidden w-72 shrink-0 border-l border-border-soft bg-bg p-4 lg:block xl:w-context',
              (panel || graphPanel) && 'xl:hidden'
            )}
          >
            {overview(false)}
          </div>
        )}
      </div>

      {graphPanel ? (
        <ContextSlot
          title={graphNode?.node_type === 'claim' ? 'Claim' : 'Concept'}
          snapPoints={[0.4, 0.92]}
          open
          onClose={() => setGraphNode(null)}
        >
          {graphPanel}
        </ContextSlot>
      ) : (
        panel && (
          <ContextSlot
            title={panelTitle}
            snapPoints={[0.45, 0.92]}
            open
            onClose={() => select(null)}
          >
            {panel}
          </ContextSlot>
        )
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

function NothingYet({ onWatch }: { onWatch: () => void }) {
  return (
    <div className="grid h-full place-items-center p-4">
      <div className="w-full max-w-sm text-center">
        <Empty icon={Network}>
          Nothing to map yet. The syllabus and the sources appear here as the build finds them, and
          concepts once they are extracted.
        </Empty>
        <Button variant="outline" size="md" className="mt-3" onClick={onWatch}>
          Watch the build
        </Button>
      </div>
    </div>
  )
}

function CitedChip({ onClear, bottom = false }: { onClear: () => void; bottom?: boolean }) {
  return (
    <div
      className={cn(
        'absolute left-3 flex items-center gap-1 rounded-row border border-border-soft bg-panel/90 py-1 pr-1 pl-3 text-xs text-fg-2',
        // The Flow's column titles are pinned to its top edge.
        bottom ? 'bottom-3' : 'top-3'
      )}
    >
      The sources one answer cited
      <button
        type="button"
        aria-label="Stop showing the answer's sources"
        onClick={onClear}
        className="grid size-(--icon-btn-sm) place-items-center rounded-chip text-fg-3 hover:bg-raised hover:text-fg"
      >
        <X className="size-3" />
      </button>
    </div>
  )
}

/**
 * What the map's marks mean. It used to be learned by clicking: nothing on the
 * page said that a square was a source, that a filled one was a primary text,
 * or that the one orange ring was a dispute. Hidden below `sm`, where the map
 * is a secondary view and the row would cover a third of it.
 */
const LEGEND: { mark: MapMark; label: string }[] = [
  { mark: 'keyConcept', label: 'Key concept' },
  { mark: 'concept', label: 'Concept' },
  { mark: 'primary', label: 'Primary source' },
  { mark: 'secondary', label: 'Secondary' },
  { mark: 'gap', label: 'Missing text' },
]

function MapLegend({ disputed }: { disputed: boolean }) {
  return (
    <ul
      aria-label="What the map's marks mean"
      className="pointer-events-none absolute bottom-3 left-3 hidden max-w-[calc(100%-9rem)] flex-wrap items-center gap-x-3 gap-y-1 rounded-row border border-border-soft bg-panel/90 px-3 py-1.5 text-label text-fg-3 sm:flex"
    >
      {LEGEND.map((item) => (
        <li key={item.mark} className="inline-flex items-center gap-1">
          <MarkGlyph mark={item.mark} className="size-2.5" />
          {item.label}
        </li>
      ))}
      {disputed && (
        <li className="inline-flex items-center gap-1">
          <MarkGlyph mark="disputed" className="size-2.5" />
          In dispute
        </li>
      )}
    </ul>
  )
}

/**
 * Map | Flow | Graph | Outline | List. With no `?view=` the active option depends on the device, which
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
    { value: 'flow' as const, label: 'Flow' },
    { value: 'graph' as const, label: 'Graph' },
    { value: 'outline' as const, label: 'Outline' },
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

/** One row of the search's results. */
interface SearchMatch {
  key: string
  selection: BrainSelection
  label: string
  kind: string
  /** A source's fetcher key, for its icon. */
  type?: string
  /** A node of the Graph: chosen, it opens there rather than as a selection. */
  node?: GraphNode
}

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
