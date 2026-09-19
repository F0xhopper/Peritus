import type { ZoomTransform } from 'd3-zoom'

import type { GraphEdge, GraphNode } from '@/lib/api/types'

/**
 * Drawing the concept graph — a pure function of the state handed to it.
 *
 * It lived inside `GraphCanvas`, reading eight refs. Pulling it out is not
 * tidying: this is the only part of the graph with real logic in it — the
 * label collision pass, the alpha ramp that makes the corpus's spine read as
 * the spine, the grid drawn in screen space — and inside the component none of
 * it could be tested. A wrong answer here is a canvas that looks *plausible*,
 * which no pixel-counting assertion notices.
 *
 * Everything it needs arrives in `PaintState`. It reads no refs, no DOM beyond
 * the context it is given, and no clock.
 */

export interface PaintState {
  nodes: GraphNode[]
  edges: GraphEdge[]
  /** `[x0, y0, x1, y1, …]` in node order, as the worker posts them. */
  positions: Float32Array
  /** Node id → its index in `nodes` and in `positions`. */
  indexById: Map<number, number>
  transform: ZoomTransform
  /** CSS pixels, and the device pixel ratio the canvas was sized at. */
  width: number
  height: number
  dpr: number
  selectedId: number | null
  hoveredId: number | null
  /**
   * The node ids the Knowledge page has lit — a key concept's sector, the
   * concepts a kind of source feeds, an answer's citations — or null when
   * nothing is. The graph shares the Map's and the Flow's lighting, so resting
   * on a row of the Overview says the same thing in every view. Optional: the
   * graph drew before there was a page to light it.
   */
  lit?: ReadonlySet<number> | null
  /** How many nodes get a permanent label. Fewer on a small screen. */
  labelBudget: number
  /** Resolved theme colours, read from the canvas's computed style. */
  colours: PaintColours
}

export interface PaintColours {
  expert: string
  fg: string
  fg3: string
  border: string
}

/** What an unlit node drops to while something is lit: the Map's own 15%. */
export const UNLIT = 0.15

/** The grid's pitch, in screen pixels. */
const GRID_STEP = 24

/** Longest label drawn before it is elided. */
const LABEL_MAX_CHARS = 32

export function nodeRadius(degree: number): number {
  return 3 + Math.sqrt(degree) * 1.6
}

/**
 * Degree at or above which a node is always labelled: roughly the top `budget`.
 *
 * Degree, not index, so ties are kept together — labelling four of five nodes
 * that all have the same degree would look arbitrary to a reader who can see
 * they are equally connected.
 */
export function labelThreshold(nodes: GraphNode[], budget: number): number {
  if (nodes.length === 0) return Number.POSITIVE_INFINITY
  const degrees = nodes.map((node) => node.degree).sort((a, b) => b - a)
  return degrees[Math.min(degrees.length - 1, budget - 1)] ?? Number.POSITIVE_INFINITY
}

export function paintGraph(context: CanvasRenderingContext2D, state: PaintState): void {
  const { nodes, positions, transform, width, height, dpr, colours } = state

  context.save()
  context.setTransform(dpr, 0, 0, dpr, 0, 0)
  context.clearRect(0, 0, width, height)

  paintGrid(context, transform, width, height, colours.border)

  context.translate(transform.x, transform.y)
  context.scale(transform.k, transform.k)

  // Positions arrive asynchronously from the worker; a frame before the first
  // tick has nothing to draw and must not read past the end of the buffer.
  if (positions.length < nodes.length * 2) {
    context.restore()
    return
  }

  paintEdges(context, state)
  paintNodes(context, state)
  paintLabels(context, state)

  context.restore()
}

/**
 * The faint dotted grid, in **screen** space.
 *
 * Deliberately not transformed with the graph: scaled into layout space it
 * becomes an unreadable moiré as soon as the reader zooms out.
 */
function paintGrid(
  context: CanvasRenderingContext2D,
  transform: ZoomTransform,
  width: number,
  height: number,
  border: string
): void {
  context.fillStyle = border
  context.globalAlpha = 0.5
  const startX = ((transform.x % GRID_STEP) + GRID_STEP) % GRID_STEP
  const startY = ((transform.y % GRID_STEP) + GRID_STEP) % GRID_STEP
  for (let x = startX; x < width; x += GRID_STEP) {
    for (let y = startY; y < height; y += GRID_STEP) {
      context.fillRect(x, y, 1, 1)
    }
  }
  context.globalAlpha = 1
}

/** Edges first, so nodes sit on top of them. */
function paintEdges(context: CanvasRenderingContext2D, state: PaintState): void {
  const { edges, positions, indexById, transform, colours } = state
  context.strokeStyle = colours.border
  context.lineWidth = 1 / transform.k
  context.beginPath()
  for (const edge of edges) {
    const from = indexById.get(edge.source)
    const to = indexById.get(edge.target)
    // An edge to a node outside the cap draws nothing rather than a line to
    // the origin, which is what an undefined index would produce.
    if (from === undefined || to === undefined) continue
    context.moveTo(positions[from * 2], positions[from * 2 + 1])
    context.lineTo(positions[to * 2], positions[to * 2 + 1])
  }
  context.stroke()
}

function paintNodes(context: CanvasRenderingContext2D, state: PaintState): void {
  const { nodes, positions, transform, selectedId, hoveredId, colours } = state
  const lit = state.lit ?? null
  const maxDegree = nodes.reduce((peak, node) => Math.max(peak, node.degree), 1)

  for (let i = 0; i < nodes.length; i += 1) {
    const node = nodes[i]
    const x = positions[i * 2]
    const y = positions[i * 2 + 1]
    const radius = nodeRadius(node.degree)
    const selected = node.id === selectedId
    const isHovered = node.id === hoveredId

    context.beginPath()
    context.arc(x, y, radius, 0, Math.PI * 2)
    // Alpha by degree: the graph's spine reads as the graph's spine. While
    // something is lit, what is lit is full and the rest falls away — but never
    // the node in hand, which is the reader's own question.
    const resting = 0.35 + (node.degree / maxDegree) * 0.5
    context.globalAlpha =
      selected || isHovered ? 1 : lit === null ? resting : lit.has(node.id) ? 1 : UNLIT
    context.fillStyle = selected ? colours.fg : colours.expert
    context.fill()
    context.globalAlpha = 1

    if (selected) {
      // The ring grows out of the node on selection.
      context.beginPath()
      context.arc(x, y, radius + 4 / transform.k, 0, Math.PI * 2)
      context.strokeStyle = colours.fg
      context.lineWidth = 1.5 / transform.k
      context.stroke()
    }
  }
}

/**
 * The busiest nodes always, plus whatever is hovered or selected.
 *
 * Placed greedily in priority order and skipped when they would collide with a
 * label already drawn, so the canvas never turns into overlapping text. The
 * selected and hovered labels are *forced*: they are the answer to the reader's
 * question, and dropping one for a collision would be worse than the overlap.
 */
function paintLabels(context: CanvasRenderingContext2D, state: PaintState): void {
  const { nodes, positions, transform, selectedId, hoveredId, labelBudget, colours } = state
  const lit = state.lit ?? null
  const threshold = labelThreshold(nodes, labelBudget)
  const k = transform.k

  context.font = `${11 / k}px var(--font-sans, system-ui)`
  context.textAlign = 'center'
  context.textBaseline = 'top'

  const priority = (i: number) =>
    nodes[i].id === selectedId ? 2 : nodes[i].id === hoveredId ? 1 : 0

  const candidates: number[] = []
  for (let i = 0; i < nodes.length; i += 1) {
    const node = nodes[i]
    if (node.id === selectedId || node.id === hoveredId || node.degree >= threshold) {
      candidates.push(i)
    }
  }
  candidates.sort((a, b) => priority(b) - priority(a) || nodes[b].degree - nodes[a].degree)

  const placed: { x0: number; y0: number; x1: number; y1: number }[] = []
  for (const i of candidates) {
    const node = nodes[i]
    const forced = priority(i) > 0
    const text =
      node.label.length > LABEL_MAX_CHARS
        ? `${node.label.slice(0, LABEL_MAX_CHARS - 1).trimEnd()}…`
        : node.label
    const radius = nodeRadius(node.degree)
    const textWidth = context.measureText(text).width
    const x = positions[i * 2]
    const y = positions[i * 2 + 1] + radius + 3 / k
    const box = { x0: x - textWidth / 2, y0: y, x1: x + textWidth / 2, y1: y + 13 / k }
    const collides = placed.some(
      (other) => box.x0 < other.x1 && box.x1 > other.x0 && box.y0 < other.y1 && box.y1 > other.y0
    )
    if (collides && !forced) continue
    placed.push(box)
    context.fillStyle = forced ? colours.fg : colours.fg3
    // A name left at full strength beside a node that has fallen away would
    // still be shouting it.
    context.globalAlpha = forced || lit === null || lit.has(node.id) ? 1 : 0.3
    context.fillText(text, x, y)
  }
  context.globalAlpha = 1
}

/** The theme's colours, with the fallbacks that keep a canvas drawable. */
export function readColours(element: Element): PaintColours {
  const style = getComputedStyle(element)
  const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
  return {
    expert: read('--expert', '#8b7cf6'),
    fg: read('--fg', '#fafafa'),
    fg3: read('--fg-3', '#6b6b73'),
    border: read('--border', '#2e2e2e'),
  }
}
