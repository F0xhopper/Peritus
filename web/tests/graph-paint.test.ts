import { zoomIdentity } from 'd3-zoom'
import { describe, expect, it, vi } from 'vitest'

import { labelThreshold, nodeRadius, paintGraph, type PaintState, UNLIT } from '@/lib/graph/paint'
import type { GraphEdge, GraphNode } from '@/lib/api/types'

/**
 * Drawing the concept graph.
 *
 * Untestable until it was pulled out of the component, and worth testing now
 * because every failure here is *plausible on screen*: a label dropped for a
 * collision that was not one, an edge drawn to the origin because a node was
 * outside the cap, a hovered node that does not come forward. The Playwright
 * test counts opaque pixels, which catches a blank canvas and nothing else.
 *
 * The canvas context is a recorder. What is asserted is the sequence of
 * drawing calls, which is the thing that actually differs between a correct
 * graph and a wrong one.
 */

/** A 2D context that records every call and property set on it. */
function recorder() {
  const calls: { op: string; args: unknown[] }[] = []
  const set: Record<string, unknown[]> = {}
  const context = new Proxy(
    {},
    {
      get(_target, prop: string) {
        if (prop === 'measureText') {
          // Deterministic metrics: 6px per character at scale 1, which is close
          // enough to a real font for the collision geometry to be meaningful.
          return (text: string) => ({ width: text.length * 6 })
        }
        return (...args: unknown[]) => {
          calls.push({ op: prop, args })
        }
      },
      set(_target, prop: string, value: unknown) {
        ;(set[prop] ??= []).push(value)
        return true
      },
    }
  ) as CanvasRenderingContext2D

  return {
    context,
    calls,
    set,
    ops: (name: string) => calls.filter((c) => c.op === name),
    /** Every string passed to `fillText`, in the order it was drawn. */
    labels: () => calls.filter((c) => c.op === 'fillText').map((c) => c.args[0] as string),
  }
}

function node(id: number, label: string, degree: number): GraphNode {
  return { id, label, degree, node_type: 'concept' } as GraphNode
}

function state(overrides: Partial<PaintState> = {}): PaintState {
  const nodes = overrides.nodes ?? [node(1, 'Virtue', 4), node(2, 'Fate', 2), node(3, 'Logos', 1)]
  return {
    nodes,
    edges: [],
    positions: new Float32Array(nodes.flatMap((_, i) => [i * 200, i * 200])),
    indexById: new Map(nodes.map((n, i) => [n.id, i])),
    transform: zoomIdentity,
    width: 800,
    height: 600,
    dpr: 1,
    selectedId: null,
    hoveredId: null,
    labelBudget: 12,
    colours: { expert: '#111', fg: '#fff', fg3: '#888', border: '#333' },
    ...overrides,
  }
}

describe('a frame before the worker has posted anything', () => {
  it('clears and returns rather than reading past the end of the buffer', () => {
    // Positions arrive asynchronously; the first frame usually has none.
    const rec = recorder()
    paintGraph(rec.context, state({ positions: new Float32Array(0) }))

    expect(rec.ops('clearRect')).toHaveLength(1)
    expect(rec.ops('arc')).toHaveLength(0)
    // Still balanced: an unbalanced save would leak the transform into the
    // next frame and progressively skew the whole graph.
    expect(rec.ops('save')).toHaveLength(1)
    expect(rec.ops('restore')).toHaveLength(1)
  })
})

describe('edges', () => {
  it('draws one line per edge', () => {
    const edges: GraphEdge[] = [
      { source: 1, target: 2, evidence: 3 } as GraphEdge,
      { source: 2, target: 3, evidence: 1 } as GraphEdge,
    ]
    const rec = recorder()
    paintGraph(rec.context, state({ edges }))

    expect(rec.ops('moveTo')).toHaveLength(2)
    expect(rec.ops('lineTo')).toHaveLength(2)
  })

  it('draws nothing for an edge pointing outside the node cap', () => {
    // The graph endpoint caps nodes; an edge to one that was cut must not be
    // drawn to the origin, which is what an undefined index would produce.
    const edges: GraphEdge[] = [{ source: 1, target: 999, evidence: 3 } as GraphEdge]
    const rec = recorder()
    paintGraph(rec.context, state({ edges }))

    expect(rec.ops('moveTo')).toHaveLength(0)
    expect(rec.ops('lineTo')).toHaveLength(0)
  })
})

describe('nodes', () => {
  it('draws one circle per node, sized by degree', () => {
    const rec = recorder()
    paintGraph(rec.context, state())

    const radii = rec.ops('arc').map((c) => c.args[2] as number)
    expect(radii).toHaveLength(3)
    // Busier nodes are bigger, which is the only thing carrying degree visually.
    expect(radii[0]).toBeGreaterThan(radii[2])
    expect(radii[0]).toBeCloseTo(nodeRadius(4))
  })

  it('brings the selected node fully forward and rings it', () => {
    const rec = recorder()
    paintGraph(rec.context, state({ selectedId: 3 }))

    // Three node circles plus the selection ring.
    expect(rec.ops('arc')).toHaveLength(4)
    // The dimmest node (degree 1) is at full alpha because it is selected.
    expect(rec.set.globalAlpha).toContain(1)
  })

  it('dims a quiet node relative to a busy one', () => {
    const rec = recorder()
    paintGraph(rec.context, state())

    const alphas = (rec.set.globalAlpha as number[]).filter((a) => a !== 1)
    expect(Math.max(...alphas)).toBeGreaterThan(Math.min(...alphas))
  })
})

describe('labels', () => {
  it('labels the busiest nodes up to the budget', () => {
    const nodes = [node(1, 'A', 9), node(2, 'B', 5), node(3, 'C', 1)]
    const rec = recorder()
    paintGraph(rec.context, state({ nodes, labelBudget: 2 }))

    expect(rec.labels()).toEqual(['A', 'B'])
  })

  it('always labels the hovered node, however quiet it is', () => {
    // It is the answer to what the reader is pointing at.
    const nodes = [node(1, 'A', 9), node(2, 'B', 5), node(3, 'C', 1)]
    const rec = recorder()
    paintGraph(rec.context, state({ nodes, labelBudget: 1, hoveredId: 3 }))

    expect(rec.labels()).toContain('C')
  })

  it('draws the selected label first, so a collision never drops it', () => {
    const nodes = [node(1, 'A', 9), node(2, 'B', 5), node(3, 'C', 1)]
    const rec = recorder()
    paintGraph(rec.context, state({ nodes, labelBudget: 3, selectedId: 3 }))

    expect(rec.labels()[0]).toBe('C')
  })

  it('skips a label that would overlap one already drawn', () => {
    // Two nodes on top of each other: the second label has nowhere to go.
    const nodes = [node(1, 'Alpha', 9), node(2, 'Beta', 5)]
    const rec = recorder()
    paintGraph(
      rec.context,
      state({ nodes, positions: new Float32Array([100, 100, 100, 100]), labelBudget: 5 })
    )

    expect(rec.labels()).toEqual(['Alpha'])
  })

  it('elides a very long label rather than letting it span the canvas', () => {
    const nodes = [node(1, 'A'.repeat(80), 9)]
    const rec = recorder()
    paintGraph(rec.context, state({ nodes, positions: new Float32Array([0, 0]) }))

    const [label] = rec.labels()
    expect(label).toHaveLength(32)
    expect(label.endsWith('…')).toBe(true)
  })
})

describe('labelThreshold', () => {
  it('keeps tied degrees together rather than cutting arbitrarily', () => {
    // Four nodes at degree 5 and a budget of 2: labelling two of four equally
    // connected nodes would look arbitrary to a reader who can see they match.
    const nodes = [node(1, 'A', 5), node(2, 'B', 5), node(3, 'C', 5), node(4, 'D', 5)]
    expect(labelThreshold(nodes, 2)).toBe(5)
  })

  it('is unreachable for an empty graph, so nothing is labelled', () => {
    expect(labelThreshold([], 5)).toBe(Number.POSITIVE_INFINITY)
  })

  it('handles a budget larger than the graph', () => {
    expect(labelThreshold([node(1, 'A', 3)], 50)).toBe(3)
  })
})

describe('the grid', () => {
  it('is drawn in screen space, so zooming out does not turn it into moiré', () => {
    const rec = recorder()
    const zoomedOut = zoomIdentity.scale(0.2)
    paintGraph(rec.context, state({ transform: zoomedOut }))

    // Same pitch at any scale: the dot count depends on the canvas, not `k`.
    const atRest = recorder()
    paintGraph(atRest.context, state())
    expect(rec.ops('fillRect').length).toBe(atRest.ops('fillRect').length)
  })

  it('scrolls with the pan, so it reads as a surface rather than an overlay', () => {
    const rec = recorder()
    paintGraph(rec.context, state({ transform: zoomIdentity.translate(7, 11) }))

    const first = rec.ops('fillRect')[0].args as number[]
    expect(first[0]).toBeCloseTo(7)
    expect(first[1]).toBeCloseTo(11)
  })
})

describe('the device pixel ratio', () => {
  it('is applied as the base transform, so a retina canvas is not half-size', () => {
    const rec = recorder()
    paintGraph(rec.context, state({ dpr: 2 }))

    expect(rec.ops('setTransform')[0].args).toEqual([2, 0, 0, 2, 0, 0])
  })
})

describe('nodeRadius', () => {
  it('grows sublinearly, so one hub does not dwarf the graph', () => {
    // Linear scaling put a degree-40 node at forty times the area of a leaf.
    expect(nodeRadius(100) / nodeRadius(1)).toBeLessThan(5)
    expect(nodeRadius(4)).toBeGreaterThan(nodeRadius(1))
  })
})

describe('it is a pure function of its state', () => {
  it('reads no clock, no DOM and no globals', () => {
    // If it did, the Playwright canvas assertions would be the only net under
    // it — and they cannot see anything subtler than a blank canvas.
    const now = vi.spyOn(Date, 'now')
    const rec = recorder()
    paintGraph(rec.context, state())
    expect(now).not.toHaveBeenCalled()
    now.mockRestore()
  })

  it('draws the same calls twice for the same state', () => {
    const a = recorder()
    const b = recorder()
    paintGraph(a.context, state({ selectedId: 2, hoveredId: 1 }))
    paintGraph(b.context, state({ selectedId: 2, hoveredId: 1 }))
    expect(b.calls).toEqual(a.calls)
  })
})

describe("the Knowledge page's lighting", () => {
  /** The `globalAlpha` in force at each node's fill, in node order. */
  const fillAlphas = (overrides: Partial<PaintState>) => {
    const alphas: number[] = []
    let alpha = 1
    const context = new Proxy(
      {},
      {
        get(_target, prop: string) {
          if (prop === 'measureText') return (text: string) => ({ width: text.length * 6 })
          if (prop === 'fill') return () => alphas.push(alpha)
          return () => undefined
        },
        set(_target, prop: string, value: unknown) {
          if (prop === 'globalAlpha') alpha = value as number
          return true
        },
      }
    ) as CanvasRenderingContext2D
    paintGraph(context, state(overrides))
    return alphas
  }

  it('leaves the resting picture alone when nothing is lit', () => {
    expect(fillAlphas({ lit: null })).toEqual(fillAlphas({}))
    // Alpha by degree: the busiest node is the brightest.
    const [virtue, fate, logos] = fillAlphas({})
    expect(virtue).toBeGreaterThan(fate)
    expect(fate).toBeGreaterThan(logos)
  })

  it('shows what is lit in full and lets the rest fall away', () => {
    // Node 2 is lit: a key concept's sector, the concepts a kind of source feeds.
    expect(fillAlphas({ lit: new Set([2]) })).toEqual([UNLIT, 1, UNLIT])
  })

  it('never dims the node in hand, lit or not', () => {
    expect(fillAlphas({ lit: new Set([2]), selectedId: 1 })[0]).toBe(1)
    expect(fillAlphas({ lit: new Set([2]), hoveredId: 3 })[2]).toBe(1)
  })

  it('lights nothing — not everything — for an empty set', () => {
    // A filter no source passes lights nothing, which is the true answer.
    expect(fillAlphas({ lit: new Set() })).toEqual([UNLIT, UNLIT, UNLIT])
  })
})
