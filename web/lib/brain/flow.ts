import type { ConceptDepth, MapResponse } from '@/lib/api/types'

/**
 * The Flow view's layout: sources, the syllabus and the concepts as three
 * columns, read left to right — what was read, what it was read *for*, and what
 * came out of it.
 *
 * The radial map (`lib/brain/layout.ts`) is a picture of the whole; it answers
 * "how big, how dense, where are the holes". It cannot answer "which sources
 * stand behind this key concept" without a click, because forty dendrites
 * crossing a disc are a texture, not a set of lines anyone can follow. This
 * layout gives the three relations the payload holds one straight reading each:
 *
 * - a source is **tagged** with key concepts, at a depth     (left → middle)
 * - a concept **sits in** a key concept's sector              (middle → right)
 * - a concept was **extracted from** sources                  (left ⇢ right, drawn
 *   only for the thing in hand — every such pair at once is the hairball again)
 *
 * **One band per key concept.** A source stands in the band of the key concept
 * it covers most deeply, so its strongest link is short and level and only its
 * lesser tags cross bands. That is what keeps a forty-source expert legible and
 * a four-hundred-source one merely long.
 *
 * Pure and deterministic, like the radial layout: the same map gives the same
 * bands, byte for byte. Only `y` is decided here. The columns' `x` depends on
 * the container's width and is the component's business ({@link flowColumns}).
 */

export const FLOW = {
  /** A facet's heading above its first band. */
  facetH: 30,
  bandPad: 10,
  bandGap: 8,
  /** The key concept's card: two lines of label over its coverage bar. Real
   *  labels run long ("Being, essence, and existence (act/potency)"); at 60 the
   *  second line was cut off by the bar. */
  nodeH: 70,
  /** Concepts shown per band until it is expanded. */
  conceptsPerBand: 4,
  minWidth: 640,
} as const

const DEPTH_RANK: Record<ConceptDepth, number> = { sets_out: 3, treats: 2, mentions: 1 }
const TIER_RANK: Record<string, number> = { primary: 0, secondary: 1, tertiary: 2 }

export interface FlowOptions {
  /** A row's height: 26 with a mouse, 44 under a thumb. */
  rowH: number
  /** Bands showing every concept in their sector, by key (`null` is the foot). */
  expanded?: ReadonlySet<number | null>
  /** A concept that must be shown even if its band would have folded it away. */
  pinnedConcept?: number | null
}

export type FlowItem =
  | {
      kind: 'source'
      id: number
      band: number
      y: number
      /** How deeply it covers its own band's key concept. */
      depth: ConceptDepth | null
    }
  | { kind: 'gap'; index: number; band: number; y: number }
  | { kind: 'concept'; id: number; band: number; y: number }
  | { kind: 'more'; band: number; y: number; hidden: number; expanded: boolean }

export interface FlowBand {
  /** The key concept's index, or null for the foot: what is outside the syllabus. */
  key: number | null
  top: number
  height: number
  /** The centre of the key concept's card. */
  nodeY: number
}

export interface FlowLink {
  kind: 'tag' | 'member'
  keyConcept: number
  /** `tag`: the source. */
  sourceId?: number
  depth?: ConceptDepth
  /**
   * `tag`: whether this is the source's own band — its deepest tag, the short
   * level link. The rest cross bands, and a real expert's sources carry three
   * or four tags each: drawn at full weight they are the hairball again, so at
   * rest they are only a trace, and light in full with whatever is in hand.
   */
  home?: boolean
  /** `member`: the concept. */
  conceptId?: number
  /** Left end and right end. */
  y1: number
  y2: number
}

export interface FlowLayout {
  height: number
  facets: { name: string; y: number }[]
  bands: FlowBand[]
  items: FlowItem[]
  links: FlowLink[]
  /** Row centres, for the evidence arcs and for scrolling a selection into view. */
  sourceY: Map<number, number>
  conceptY: Map<number, number>
  gapY: Map<number, number>
}

/** The key concept a source stands beside: its deepest tag, lowest index on a tie. */
export function homeKeyConcept(tags: { key_concept: number; depth: ConceptDepth }[]): {
  key: number
  depth: ConceptDepth
} | null {
  let best: { key: number; depth: ConceptDepth } | null = null
  for (const tag of tags) {
    if (
      best === null ||
      DEPTH_RANK[tag.depth] > DEPTH_RANK[best.depth] ||
      (DEPTH_RANK[tag.depth] === DEPTH_RANK[best.depth] && tag.key_concept < best.key)
    ) {
      best = { key: tag.key_concept, depth: tag.depth }
    }
  }
  return best
}

export function flowLayout(map: MapResponse, options: FlowOptions): FlowLayout {
  const { rowH } = options
  const expanded = options.expanded ?? new Set<number | null>()
  const keyConcepts = map.syllabus.key_concepts

  // ── the order of the bands: by facet, then whatever no facet names ─────────
  const order: { key: number; facet: string | null }[] = []
  const placed = new Set<number>()
  for (const facet of map.syllabus.facets ?? []) {
    for (const index of facet.concepts) {
      if (index < 0 || index >= keyConcepts.length || placed.has(index)) continue
      placed.add(index)
      order.push({ key: index, facet: facet.name })
    }
  }
  keyConcepts.forEach((_concept, index) => {
    if (!placed.has(index)) order.push({ key: index, facet: null })
  })

  // ── who stands in which band ──────────────────────────────────────────────
  const sourcesIn = new Map<number | null, { id: number; depth: ConceptDepth | null }[]>()
  const push = <K, V>(into: Map<K, V[]>, key: K, value: V) => {
    const list = into.get(key)
    if (list) list.push(value)
    else into.set(key, [value])
  }
  const sourceById = new Map(map.sources.map((source) => [source.id, source]))
  for (const source of map.sources) {
    if (source.pending) continue
    const home = homeKeyConcept(source.tags.filter((tag) => tag.key_concept < keyConcepts.length))
    push(sourcesIn, home?.key ?? null, { id: source.id, depth: home?.depth ?? null })
  }
  for (const list of sourcesIn.values()) {
    list.sort((a, b) => {
      const depth = (b.depth ? DEPTH_RANK[b.depth] : 0) - (a.depth ? DEPTH_RANK[a.depth] : 0)
      if (depth) return depth
      const sa = sourceById.get(a.id)!
      const sb = sourceById.get(b.id)!
      const tier = (TIER_RANK[sa.tier ?? ''] ?? 3) - (TIER_RANK[sb.tier ?? ''] ?? 3)
      return tier || sa.title.localeCompare(sb.title) || a.id - b.id
    })
  }

  const gapsIn = new Map<number | null, number[]>()
  map.syllabus.gaps.forEach((gap, index) => {
    const key =
      gap.key_concept !== null && gap.key_concept < keyConcepts.length ? gap.key_concept : null
    push(gapsIn, key, index)
  })

  const conceptsIn = new Map<number | null, number[]>()
  const conceptById = new Map(map.concepts.map((concept) => [concept.id, concept]))
  for (const concept of [...map.concepts].sort(
    (a, b) =>
      b.source_ids.length - a.source_ids.length ||
      b.degree - a.degree ||
      a.label.localeCompare(b.label) ||
      a.id - b.id
  )) {
    const key =
      concept.key_concept !== null && concept.key_concept < keyConcepts.length
        ? concept.key_concept
        : null
    push(conceptsIn, key, concept.id)
  }

  // ── stack the bands ───────────────────────────────────────────────────────
  const layout: FlowLayout = {
    height: 0,
    facets: [],
    bands: [],
    items: [],
    links: [],
    sourceY: new Map(),
    conceptY: new Map(),
    gapY: new Map(),
  }
  let y = 0
  let lastFacet: string | null | undefined

  const foot =
    sourcesIn.has(null) || gapsIn.has(null) || conceptsIn.has(null)
      ? [{ key: null as number | null, facet: 'Outside the syllabus' as string | null }]
      : []

  for (const { key, facet } of [...order, ...foot]) {
    if (facet !== lastFacet) {
      lastFacet = facet
      if (facet !== null) {
        layout.facets.push({ name: facet, y })
        y += FLOW.facetH
      }
    }

    const sources = sourcesIn.get(key) ?? []
    const gaps = gapsIn.get(key) ?? []
    const every = conceptsIn.get(key) ?? []
    const open = expanded.has(key)
    const leftRows = sources.length + gaps.length
    // A band its sources have already made tall shows concepts down to the same
    // foot: the rows cost no height, and a lane of eleven sources beside four
    // concepts and a gap read as if the sector were thin. One row is kept for
    // "+n more".
    const folded = Math.max(FLOW.conceptsPerBand, leftRows - 1)
    const shown = open ? [...every] : every.slice(0, folded)
    const pinned = options.pinnedConcept ?? null
    if (pinned !== null && !shown.includes(pinned) && every.includes(pinned)) shown.push(pinned)
    const hidden = every.length - shown.length
    const more = hidden > 0 || (open && every.length > folded)

    const rightRows = shown.length + (more ? 1 : 0)
    const inner = Math.max(leftRows * rowH, rightRows * rowH, FLOW.nodeH)
    const height = inner + FLOW.bandPad * 2
    const band = layout.bands.length
    const nodeY = y + height / 2
    layout.bands.push({ key, top: y, height, nodeY })

    // Each column's block is centred in the band, so a short column fans
    // evenly about the card rather than hanging from its top.
    let rowY = nodeY - (leftRows * rowH) / 2 + rowH / 2
    for (const source of sources) {
      layout.items.push({ kind: 'source', id: source.id, band, y: rowY, depth: source.depth })
      layout.sourceY.set(source.id, rowY)
      rowY += rowH
    }
    for (const index of gaps) {
      layout.items.push({ kind: 'gap', index, band, y: rowY })
      layout.gapY.set(index, rowY)
      rowY += rowH
    }

    rowY = nodeY - (rightRows * rowH) / 2 + rowH / 2
    for (const id of shown) {
      layout.items.push({ kind: 'concept', id, band, y: rowY })
      layout.conceptY.set(id, rowY)
      rowY += rowH
    }
    if (more) layout.items.push({ kind: 'more', band, y: rowY, hidden, expanded: open })

    y += height + FLOW.bandGap
  }
  layout.height = Math.max(0, y - FLOW.bandGap)

  // ── the links ─────────────────────────────────────────────────────────────
  // Ports are spread along the card's edge in the order of what they join, so
  // links into one card never cross each other on the way in.
  const bandOf = new Map(layout.bands.map((band) => [band.key, band]))
  const span = FLOW.nodeH - 20

  const incoming = new Map<
    number,
    { sourceId: number; depth: ConceptDepth; y: number; home: boolean }[]
  >()
  const homeOf = new Map(
    layout.items.flatMap((item) =>
      item.kind === 'source' ? [[item.id, layout.bands[item.band].key] as const] : []
    )
  )
  for (const source of map.sources) {
    const from = layout.sourceY.get(source.id)
    if (from === undefined) continue
    for (const tag of source.tags) {
      if (!bandOf.has(tag.key_concept)) continue
      push(incoming, tag.key_concept, {
        sourceId: source.id,
        depth: tag.depth,
        y: from,
        home: homeOf.get(source.id) === tag.key_concept,
      })
    }
  }
  // In band order, not the payload's: the links' order is their paint order,
  // and the same map must stack the same way however the API listed it.
  for (const band of layout.bands) {
    const key = band.key
    const list = key === null ? undefined : incoming.get(key)
    if (key === null || !list) continue
    list.sort((a, b) => a.y - b.y || a.sourceId - b.sourceId)
    list.forEach((link, i) => {
      layout.links.push({
        kind: 'tag',
        keyConcept: key,
        sourceId: link.sourceId,
        depth: link.depth,
        home: link.home,
        y1: link.y,
        y2: band.nodeY - span / 2 + ((i + 0.5) * span) / list.length,
      })
    })
  }

  for (const band of layout.bands) {
    if (band.key === null) continue
    const index = layout.bands.indexOf(band)
    const members = layout.items.filter(
      (item): item is Extract<FlowItem, { kind: 'concept' }> =>
        item.kind === 'concept' && item.band === index
    )
    members.forEach((item, i) => {
      // A pinned concept can stand in a band whose key concept is not its own
      // only if the payload disagrees with itself; it is drawn, never linked.
      if (conceptById.get(item.id)?.key_concept !== band.key) return
      layout.links.push({
        kind: 'member',
        keyConcept: band.key as number,
        conceptId: item.id,
        y1: band.nodeY - span / 2 + ((i + 0.5) * span) / members.length,
        y2: item.y,
      })
    })
  }

  return layout
}

// ── x ───────────────────────────────────────────────────────────────────────

export interface FlowColumns {
  width: number
  source: { x: number; w: number }
  node: { x: number; w: number }
  concept: { x: number; w: number }
}

/**
 * The three columns and the two channels the links cross, for a container
 * `width` wide. Below {@link FLOW.minWidth} the diagram keeps that width and
 * scrolls inside its own box — a diagram, like a table, is allowed to.
 */
export function flowColumns(width: number): FlowColumns {
  const total = Math.max(Math.floor(width), FLOW.minWidth)
  const pad = 12
  const channel = Math.round(Math.min(132, Math.max(56, total * 0.1)))
  const node = Math.round(Math.min(232, Math.max(168, total * 0.22)))
  const free = total - pad * 2 - channel * 2 - node
  const source = Math.round(free * 0.56)
  const concept = free - source
  const nodeX = pad + source + channel
  return {
    width: total,
    source: { x: pad, w: source },
    node: { x: nodeX, w: node },
    concept: { x: nodeX + node + channel, w: concept },
  }
}

/** A level S-curve between two columns. */
export function flowPath(x1: number, y1: number, x2: number, y2: number): string {
  const bend = (x2 - x1) / 2
  const r = (n: number) => Math.round(n * 10) / 10
  return `M${r(x1)},${r(y1)}C${r(x1 + bend)},${r(y1)} ${r(x2 - bend)},${r(y2)} ${r(x2)},${r(y2)}`
}
