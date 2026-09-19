'use client'

import { GRAPH_LIMITS } from '@/lib/graph/limits'
import { cn } from '@/lib/cn'

/**
 * How many nodes the Graph view draws, busiest first. A range input over fixed
 * stops, driven as well by the arrow keys as by a pointer.
 *
 * Its own file, apart from `graph-tab.tsx`: the page renders one in a node's
 * sheet below `lg`, and importing it from the view would pull d3 and the canvas
 * into the page's bundle — the thing `next/dynamic` is there to prevent.
 */
export function GraphLimit({
  id,
  limit,
  pending = false,
  onLimit,
  className,
}: {
  /** Two of these can be on the page at once: the floating one and the sheet's. */
  id: string
  limit: number
  pending?: boolean
  onLimit: (limit: number) => void
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex items-center gap-2 rounded-row border border-border bg-raised/95 px-3 py-1.5',
        className
      )}
    >
      <label htmlFor={id} className="text-xs text-fg-3">
        Nodes
      </label>
      <input
        id={id}
        type="range"
        min={0}
        max={GRAPH_LIMITS.length - 1}
        step={1}
        value={Math.max(0, (GRAPH_LIMITS as readonly number[]).indexOf(limit))}
        onChange={(event) => onLimit(GRAPH_LIMITS[Number(event.target.value)])}
        className="min-w-0 flex-1 accent-(--fg-2) lg:w-24 lg:flex-none"
      />
      <span
        className={cn('w-10 text-right font-mono text-xs', pending ? 'text-fg-3' : 'text-fg-2')}
      >
        {limit}
      </span>
    </div>
  )
}
