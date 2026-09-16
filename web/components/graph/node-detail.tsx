'use client'

import { MessageSquare } from 'lucide-react'
import { useMemo } from 'react'

import { ButtonLink } from '@/components/ui/button'
import { cn } from '@/lib/cn'
import { humanise } from '@/lib/format'
import { stashAskDraft } from '@/components/chat/new-chat-composer'
import type { GraphEdge, GraphNode } from '@/lib/api/types'

/**
 * A selected concept.
 *
 * Its neighbours are grouped by edge type, and `contradicts` is listed first
 * and coloured — where sources in this corpus were judged to disagree is the
 * most interesting thing the graph knows, and burying it among `about` edges
 * would waste it.
 *
 * The wording is careful on purpose: "sources in this corpus were judged to
 * disagree", never "contradictions in the literature". The corpus is tens of
 * sources, not the literature.
 */
const EDGE_ORDER = ['contradicts', 'qualifies', 'supports', 'about', 'part_of']

export function NodeDetail({
  node,
  edges,
  nodes,
  slug,
  keyConcepts,
  onFocus,
  limitControl,
}: {
  node: GraphNode
  edges: GraphEdge[]
  nodes: GraphNode[]
  slug: string
  /** The expert's key concepts — the only labels the ledger's concept filter knows. */
  keyConcepts: string[]
  onFocus: (node: GraphNode) => void
  /** The node-limit slider, which lives in this sheet's header below `lg`. */
  limitControl?: React.ReactNode
}) {
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])

  const grouped = useMemo(() => {
    // Keyed by neighbour within each type: the graph can hold an edge each way
    // between the same two concepts (A part_of B and B part_of A), which listed
    // the neighbour twice and gave React two children with one key.
    const groups = new Map<string, Map<number, { other: GraphNode; evidence: number }>>()
    for (const edge of edges) {
      if (edge.source !== node.id && edge.target !== node.id) continue
      const otherId = edge.source === node.id ? edge.target : edge.source
      const other = byId.get(otherId)
      if (!other) continue
      const byNeighbour = groups.get(edge.edge_type) ?? new Map()
      const seen = byNeighbour.get(other.id)
      if (!seen || edge.evidence > seen.evidence) {
        byNeighbour.set(other.id, { other, evidence: edge.evidence })
      }
      groups.set(edge.edge_type, byNeighbour)
    }
    return [...groups.entries()]
      .map(
        ([type, byNeighbour]) =>
          [type, [...byNeighbour.values()].sort((a, b) => b.evidence - a.evidence)] as const
      )
      .sort((a, b) => indexOfType(a[0]) - indexOfType(b[0]))
  }, [edges, node.id, byId])

  return (
    <div className="space-y-4 text-sm">
      {limitControl}

      <div>
        <h3 className="font-medium text-fg">{node.label}</h3>
        <p className="mt-0.5 text-xs text-fg-3">
          {humanise(node.node_type)} · {node.degree} link{node.degree === 1 ? '' : 's'}
        </p>
      </div>

      {grouped.length === 0 ? (
        <p className="text-xs text-fg-3">Nothing links to this concept at the current limit.</p>
      ) : (
        grouped.map(([type, neighbours]) => (
          <div key={type}>
            <p
              className={cn(
                'text-label tracking-[0.04em] uppercase',
                type === 'contradicts' ? 'text-warn' : 'text-fg-3'
              )}
            >
              {LABELS[type] ?? humanise(type)}
            </p>
            <ul className="mt-1 space-y-0.5">
              {neighbours.slice(0, 12).map(({ other, evidence }) => (
                <li key={other.id}>
                  <button
                    type="button"
                    onClick={() => onFocus(other)}
                    className="flex w-full items-center gap-2 rounded-row px-1 py-0.5 text-left text-xs text-fg-2 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
                  >
                    <span className="min-w-0 flex-1 truncate">{other.label}</span>
                    {/* Evidence is a count of distinct sources behind the two
                        sides, not a confidence — labelled as such. */}
                    <span className="shrink-0 text-fg-3" title={`${evidence} sources`}>
                      {evidence}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {neighbours.length > 12 && (
              <p className="mt-0.5 px-1 text-xs text-fg-3">+{neighbours.length - 12} more</p>
            )}
          </div>
        ))
      )}

      <div className="flex flex-wrap gap-2 border-t border-border-soft pt-3">
        {/* Sources record coverage of the *key concepts* only. A graph node is
            usually a finer-grained concept than those, and linking it to the
            ledger's concept filter opened "No sources match this filter" for
            almost every node — so the link is offered only where it can match. */}
        {keyConcepts.some((c) => c.toLowerCase() === node.label.toLowerCase()) && (
          <ButtonLink
            variant="outline"
            size="sm"
            href={`/experts/${slug}/sources?concept=${encodeURIComponent(node.label)}`}
          >
            Sources covering this
          </ButtonLink>
        )}
        <ButtonLink
          variant="ghost"
          size="sm"
          href={`/experts/${slug}#ask`}
          onClick={() => stashAskDraft(slug, `What do the sources say about ${node.label}?`)}
        >
          <MessageSquare className="size-3" />
          Ask about this
        </ButtonLink>
      </div>
    </div>
  )
}

const LABELS: Record<string, string> = {
  contradicts: 'Judged to disagree',
  qualifies: 'Qualifies',
  supports: 'Supports',
  about: 'Claims about this',
  part_of: 'Part of',
}

function indexOfType(type: string): number {
  const index = EDGE_ORDER.indexOf(type)
  return index === -1 ? EDGE_ORDER.length : index
}
