'use client'

import { Network } from 'lucide-react'

import { GraphCanvas, type GraphCanvasHandle } from '@/components/graph/graph-canvas'
import { GraphLimit } from '@/components/knowledge/graph-limit'
import { Button } from '@/components/ui/button'
import { Empty } from '@/components/ui/empty'
import { Notice } from '@/components/ui/notice'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import type { GraphNode, GraphResponse } from '@/lib/api/types'

/**
 * The Graph view: the concept graph the product had before the Map — every
 * concept and claim as a node, every relation between them as a link, laid out
 * by force.
 *
 * It came back because it answers a question none of the other three can. The
 * Map is the syllabus's picture, the Flow is what stands behind each key
 * concept, the List is the sources; this is **how the ideas themselves hold
 * together** — which claims are about which concept, which were judged to
 * disagree — with no syllabus imposed on it. It also draws claims, which
 * nothing else on the page does.
 *
 * **`computed: false` is never an empty canvas.** The graph is extracted a
 * stage after the expert can answer, and an empty canvas there would say "this
 * expert has no concepts", the opposite of the truth.
 *
 * The node limit is URL state (`?limit=`), so a particular view of the graph is
 * a link. Moving it reheats the layout in place rather than starting it over.
 *
 * Loaded with `next/dynamic`: d3's force simulation, quadtree and the worker
 * are this view's alone, and bundled with the page they would delay the List's
 * hydration (web/AGENTS.md).
 */
export function GraphTab({
  graph,
  error,
  pending,
  limit,
  selectedId,
  lit,
  onLimit,
  onSelect,
  onWatchBuild,
  handleRef,
}: {
  /** Null until the first fetch lands. */
  graph: GraphResponse | null
  error: string | null
  /** True while a fetch is out: the first, or a new limit's. */
  pending: boolean
  limit: number
  selectedId: number | null
  /** The node ids the page has lit — a key concept's sector, a filter — or null. */
  lit: ReadonlySet<number> | null
  onLimit: (limit: number) => void
  onSelect: (node: GraphNode | null) => void
  onWatchBuild: () => void
  handleRef: React.RefObject<GraphCanvasHandle | null>
}) {
  if (!graph) {
    return error ? (
      <div className="grid h-full place-items-center p-4">
        <Notice tone="bad" title="The graph could not be loaded">
          {error}
        </Notice>
      </div>
    ) : (
      <div className="h-full p-3 md:p-4" aria-busy="true" aria-label="Loading the graph">
        <Skeleton className="h-full w-full rounded-card" />
      </div>
    )
  }

  if (!graph.computed) {
    return (
      <div className="grid h-full place-items-center p-4">
        <div className="w-full max-w-sm text-center">
          <Empty icon={Network}>
            The concept graph is still being extracted. It runs a stage after the sources become
            searchable, so this expert may already be answering questions.
          </Empty>
          <Button variant="outline" size="md" className="mt-3" onClick={onWatchBuild}>
            Watch the build
          </Button>
        </div>
      </div>
    )
  }

  return (
    <>
      <GraphCanvas
        nodes={graph.nodes}
        edges={graph.edges}
        selectedId={selectedId}
        lit={lit}
        onSelect={onSelect}
        onHover={() => {
          /* the canvas paints its own hover label */
        }}
        handleRef={handleRef}
        // The layout is dimmed, not blanked, while a new limit's nodes load.
        className={cn('transition-opacity duration-(--dur-1)', pending && 'opacity-60')}
      />

      {/* From `lg`. Below it the slider is in the node's sheet, where the
          canvas is full-bleed and a floating control would sit under a thumb. */}
      <div className="absolute top-3 right-3 hidden lg:block">
        <GraphLimit id="graph-limit" limit={limit} pending={pending} onLimit={onLimit} />
      </div>

      <p className="pointer-events-none absolute bottom-3 left-3 max-w-[calc(100%-1.5rem)] rounded-row border border-border-soft bg-panel/90 px-3 py-1 text-xs text-fg-3">
        {formatNumber(graph.nodes.length)} of {formatNumber(graph.total_nodes)} concepts ·{' '}
        {formatNumber(graph.edges.length)} links
        {graph.truncated && <span className="ml-1.5">busiest first</span>}
      </p>

      {error && (
        <div className="absolute right-3 bottom-3 max-w-xs">
          <Notice tone="bad" title="That limit could not be loaded">
            {error}
          </Notice>
        </div>
      )}

      {graph.nodes.length === 0 && (
        <div className="absolute inset-0 grid place-items-center p-4">
          <Notice tone="info" title="No concepts at this limit">
            The graph is computed but returned nothing — try a larger limit.
          </Notice>
        </div>
      )}
    </>
  )
}
