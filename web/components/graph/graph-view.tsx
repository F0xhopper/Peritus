'use client'

import { Network, Search } from 'lucide-react'
import Link from 'next/link'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useMemo, useRef, useState, useTransition } from 'react'

import { GraphCanvas, type GraphCanvasHandle } from '@/components/graph/graph-canvas'
import { NodeDetail } from '@/components/graph/node-detail'
import { ContextSlot } from '@/components/shell/context-panel'
import { useShell } from '@/components/shell/shell-context'
import { TopBar } from '@/components/shell/top-bar'
import { Button } from '@/components/ui/button'
import { Empty } from '@/components/ui/empty'
import { Input } from '@/components/ui/input'
import { MenuItem } from '@/components/ui/menu'
import { Notice } from '@/components/ui/notice'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'

import type { ExpertWithCatalog, GraphNode, GraphResponse } from '@/lib/api/types'

/**
 * The knowledge graph.
 *
 * **`computed: false` is never an empty canvas.** The graph is extracted a
 * whole stage after the corpus becomes searchable, so an expert can be
 * answering questions with nothing here yet — and drawing an empty canvas in
 * that state would say "this corpus has no concepts", which is the opposite of
 * the truth. It gets the full-centre "still building" state instead.
 *
 * The node limit is URL state, like the ledger's filters, so a particular view
 * of the graph is a link. Changing it re-fetches and reheats; existing nodes
 * keep their positions rather than the layout starting over.
 */
const LIMITS = [100, 200, 400, 800, 1500]

export function GraphView({
  expert,
  graph,
  limit,
}: {
  expert: ExpertWithCatalog
  graph: GraphResponse
  limit: number
}) {
  const router = useRouter()
  const pathname = usePathname()
  const params = useSearchParams()
  const { openContext } = useShell()
  const [pending, startTransition] = useTransition()

  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [query, setQuery] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const canvas = useRef<GraphCanvasHandle | null>(null)

  const search = useCallback(
    (text: string): GraphNode[] => {
      const needle = text.trim().toLowerCase()
      if (!needle) return []
      return graph.nodes.filter((node) => node.label.toLowerCase().includes(needle)).slice(0, 8)
    },
    [graph.nodes],
  )

  const matches = useMemo(() => search(query), [search, query])

  const setLimit = (next: number) => {
    const search = new URLSearchParams(params.toString())
    search.set('limit', String(next))
    startTransition(() => router.push(`${pathname}?${search}`, { scroll: false }))
  }

  const focus = (node: GraphNode) => {
    setSelected(node)
    canvas.current?.focusNode(node.id)
    openContext()
    setQuery('')
    setSearchOpen(false)
  }

  if (!graph.computed) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <TopBar expert={expert} title="Graph" />
        <div className="scroll-col flex flex-1 items-center justify-center p-4">
          <div className="w-full max-w-sm text-center">
            <Empty icon={Network}>
              The concept graph is still being extracted. It runs a stage after the corpus becomes
              searchable, so this expert may already be answering questions.
            </Empty>
            <p className="mt-1 text-xs text-fg-3">
              Readiness: {expert.readiness.replace('_', '-')}
            </p>
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
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <TopBar
        expert={expert}
        title="Graph"
        // The concept search is this page's search; the palette stays on ⌘K.
        hideSearch
        action={
          <Button
            variant="ghost"
            size="icon"
            aria-label="Search concepts"
            onClick={() => setSearchOpen((value) => !value)}
            className="lg:hidden"
          >
            <Search className="size-4" />
          </Button>
        }
        overflow={
          <>
            <MenuItem onClick={() => router.push(`/experts/${expert.name}`)}>Overview</MenuItem>
            <MenuItem onClick={() => router.push(`/experts/${expert.name}/sources`)}>
              Sources
            </MenuItem>
          </>
        }
      />

      <div className="relative min-h-0 flex-1">
        <GraphCanvas
          nodes={graph.nodes}
          edges={graph.edges}
          selectedId={selected?.id ?? null}
          onSelect={(node) => {
            setSelected(node)
            if (node) openContext()
          }}
          onHover={() => {
            /* the canvas paints its own hover label */
          }}
          handleRef={canvas}
        />

        {/* Floating search, top-left from `lg`; a top-bar icon below. */}
        <div
          className={cn(
            'absolute top-3 left-3 w-56',
            searchOpen ? 'block' : 'hidden lg:block',
          )}
        >
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              // Matched from the field's **current value**, not from the
              // `matches` this render closed over. Type quickly and press Enter
              // before React has re-rendered — which is a normal speed, and is
              // what a keystroke replayed by a test does every time — and the
              // handler still held the previous query's results, so Enter
              // selected the wrong node or nothing at all.
              if (event.key === 'Enter') {
                const first = search(event.currentTarget.value)[0]
                if (first) focus(first)
              }
              if (event.key === 'Escape') setSearchOpen(false)
            }}
            placeholder="Find a concept"
            aria-label="Find a concept"
            className="bg-raised/95"
          />
          {matches.length > 0 && (
            <ul className="mt-1 overflow-hidden rounded-card border border-border bg-raised shadow-lg shadow-black/25">
              {matches.map((node) => (
                <li key={node.id}>
                  <button
                    type="button"
                    onClick={() => focus(node)}
                    className="flex h-(--row-h) w-full items-center gap-2 px-2 text-left text-sm text-fg-2 transition-colors duration-(--dur-1) hover:bg-border hover:text-fg"
                  >
                    <span className="min-w-0 flex-1 truncate">{node.label}</span>
                    <span className="shrink-0 text-xs text-fg-3">{node.degree}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* The limit slider, top-right from `lg`. Below that it lives in the
            node sheet's header, where the canvas is full-bleed. */}
        <div className="absolute top-3 right-3 hidden items-center gap-2 rounded-row bg-raised/95 px-2 py-1.5 lg:flex">
          <label htmlFor="graph-limit" className="text-xs text-fg-3">
            Nodes
          </label>
          <input
            id="graph-limit"
            type="range"
            min={0}
            max={LIMITS.length - 1}
            step={1}
            value={Math.max(0, LIMITS.indexOf(limit))}
            onChange={(event) => setLimit(LIMITS[Number(event.target.value)])}
            className="w-24 accent-[var(--expert)]"
          />
          <span className={cn('w-10 text-right font-mono text-xs', pending ? 'text-fg-3' : 'text-fg-2')}>
            {limit}
          </span>
        </div>

        <div className="pointer-events-none absolute bottom-3 left-3 rounded-row bg-panel/90 px-2 py-1 text-xs text-fg-3">
          {formatNumber(graph.nodes.length)} of {formatNumber(graph.total_nodes)} concepts ·{' '}
          {formatNumber(graph.edges.length)} links
          {graph.truncated && (
            <span className="ml-1.5 text-fg-3">busiest first</span>
          )}
        </div>

        {graph.nodes.length === 0 && (
          <div className="absolute inset-0 grid place-items-center p-4">
            <Notice tone="info" title="No concepts at this limit">
              The graph is computed but returned nothing — try a larger limit.
            </Notice>
          </div>
        )}
      </div>

      <ContextSlot
        title="Concept"
        snapPoints={[0.4, 0.92]}
        open={selected !== null}
        onClose={() => setSelected(null)}
      >
        {selected ? (
          <NodeDetail
            node={selected}
            edges={graph.edges}
            nodes={graph.nodes}
            slug={expert.name}
            keyConcepts={expert.key_concepts}
            onFocus={(node) => focus(node)}
            limitControl={
              <div className="flex items-center gap-2 lg:hidden">
                <label htmlFor="graph-limit-sheet" className="text-xs text-fg-3">
                  Nodes
                </label>
                <input
                  id="graph-limit-sheet"
                  type="range"
                  min={0}
                  max={LIMITS.length - 1}
                  step={1}
                  value={Math.max(0, LIMITS.indexOf(limit))}
                  onChange={(event) => setLimit(LIMITS[Number(event.target.value)])}
                  className="min-w-0 flex-1 accent-[var(--expert)]"
                />
                <span className="w-10 text-right font-mono text-xs text-fg-2">{limit}</span>
              </div>
            }
          />
        ) : (
          <p className="text-sm text-fg-3">
            Select a concept to see what its sources say about it, and{' '}
            <Link
              href={`/experts/${expert.name}/sources`}
              className="text-fg underline underline-offset-2"
            >
              which sources
            </Link>{' '}
            say it.
          </p>
        )}
      </ContextSlot>
    </div>
  )
}
