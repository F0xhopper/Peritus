import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Force,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force'

import type { ConceptDepth, MapResponse } from '@/lib/api/types'

/**
 * Where everything on the expert's map sits — a pure function of the payload.
 *
 * docs/plans/expert-brain.md, phase 3. The map is layered, and only the middle
 * layer is simulated:
 *
 * - the **nucleus** at the origin;
 * - the **syllabus ring** at {@link RING}: key concepts at fixed angles, grouped
 *   by facet, with a small gap between facets. They never float — a syllabus
 *   that lands somewhere new on each visit cannot be learned;
 * - the **cloud** between {@link CLOUD_IN} and {@link CLOUD_OUT}: concept nodes,
 *   each pulled gently toward its key concept's angle;
 * - the **orbit** at {@link ORBIT}: sources at the weighted circular mean of the
 *   key concepts they cover, relaxed along the ring so none overlap, and the
 *   gaps (texts named and never found) at their key concept's angle.
 *
 * Whatever belongs to no key concept — unassigned concepts, untagged sources, a
 * missing work named for nothing — shares one neutral arc at the **foot** of
 * the map. It is reserved only when something needs it.
 *
 * **Deterministic, byte for byte.** Nothing reads a clock or `Math.random`:
 * starting positions come from a hash of the id and `d3-force` seeds its own
 * jiggle from a fixed LCG. The same payload always gives the same map, which is
 * what makes the map learnable — and it is asserted in `tests/brain-layout.test.ts`.
 *
 * Units are layout units, independent of the canvas: the view fits the whole
 * map with a zoom transform, so a resize never re-runs any of this.
 */

export const RING = 170
export const CLOUD_IN = 215
export const CLOUD_OUT = 325
export const ORBIT = 385
/** Where a facet's name sits: on its sector's bisector, just outside the orbit. */
const FACET_LABEL = ORBIT + 16
/** Straight down, in canvas coordinates (y grows downward). */
export const FOOT = Math.PI / 2
/** The neutral arc's width, when anything needs it. */
const FOOT_SPAN = 0.75
/** The space between two facets' sectors, in key-concept slots. */
const FACET_GAP = 0.8
/**
 * How hard a concept is pulled toward its key concept's angle. Gentle on
 * purpose: the hand-check put the assignment at 79% right (expert-brain.md,
 * "Phase 0 — measured"), and a node a sector off where a reader would put it
 * costs little when the pull only leans it that way.
 */
const ANGULAR_PULL = 0.035
/** The cloud's band is a wall, not a suggestion. */
const BAND_STRENGTH = 0.35
const TICKS = 300

/** Depth weights for a source's angle (sets_out 3, treats 2, mentions 1). */
const DEPTH_WEIGHT: Record<ConceptDepth, number> = { sets_out: 3, treats: 2, mentions: 1 }

export interface KeyConceptPlace {
  index: number
  angle: number
  x: number
  y: number
  r: number
}

export interface FacetPlace {
  name: string
  angle: number
  x: number
  y: number
  /** The first and last key-concept angles of the sector. */
  from: number
  to: number
}

export interface OrbitPlace {
  angle: number
  x: number
  y: number
  /** Side of the square, in layout units. */
  size: number
}

export interface BrainLayout {
  keyConcepts: KeyConceptPlace[]
  facets: FacetPlace[]
  /** In `map.sources` order. */
  sources: OrbitPlace[]
  /** In `map.syllabus.gaps` order. */
  gaps: OrbitPlace[]
  /** `[x0, y0, x1, y1, …]` in `map.concepts` order. */
  concepts: Float32Array
  /** Whether the neutral arc at the foot is in use. */
  foot: boolean
}

export function keyConceptRadius(sources: number): number {
  return Math.min(17, 7 + 2.2 * Math.sqrt(Math.max(0, sources)))
}

export function sourceSize(passages: number, tier: string | null): number {
  const size = Math.min(20, 6 + 1.4 * Math.sqrt(Math.max(0, passages)))
  return tier === 'tertiary' ? size * 0.75 : size
}

export function conceptRadius(sourceCount: number): number {
  return 2.2 + Math.min(3, Math.sqrt(Math.max(0, sourceCount - 1)) * 1.1)
}

export function computeLayout(map: MapResponse): BrainLayout {
  const keyCount = map.syllabus.key_concepts.length
  const untaggedSources = map.sources.some(
    (source) => !source.tags.some((tag) => tag.key_concept < keyCount)
  )
  const foot =
    keyCount === 0 ||
    untaggedSources ||
    map.syllabus.gaps.some((gap) => gap.key_concept === null) ||
    map.concepts.some((concept) => concept.key_concept === null)

  const { angles, slot, facets } = ringAngles(map, foot)

  const keyConcepts = map.syllabus.key_concepts.map((concept, index) => {
    const angle = angles[index]
    return {
      index,
      angle,
      x: Math.cos(angle) * RING,
      y: Math.sin(angle) * RING,
      r: keyConceptRadius(concept.sources),
    }
  })

  const orbit = orbitPlaces(map, angles)
  const concepts = cloud(map, angles, slot)

  return {
    keyConcepts,
    facets: facets.map((facet) => {
      const angle = facet.from + angleBetween(facet.from, facet.to) / 2
      return {
        ...facet,
        angle,
        // Outside the orbit, clear of the key concepts' own labels.
        x: Math.cos(angle) * FACET_LABEL,
        y: Math.sin(angle) * FACET_LABEL,
      }
    }),
    sources: orbit.sources,
    gaps: orbit.gaps,
    concepts,
    foot,
  }
}

/**
 * The key concepts' angles, facet by facet, clockwise from just past the foot.
 *
 * A key concept no facet names is placed after the facets, in stored order —
 * which is also every key concept of an expert planned before facets existed.
 */
function ringAngles(
  map: MapResponse,
  foot: boolean
): { angles: number[]; slot: number; facets: Omit<FacetPlace, 'angle' | 'x' | 'y'>[] } {
  const count = map.syllabus.key_concepts.length
  const groups: { name: string | null; members: number[] }[] = []
  const placed = new Set<number>()
  for (const facet of map.syllabus.facets ?? []) {
    const members = facet.concepts.filter((i) => i >= 0 && i < count && !placed.has(i))
    members.forEach((i) => placed.add(i))
    if (members.length) groups.push({ name: facet.name, members })
  }
  const rest = [...Array(count).keys()].filter((i) => !placed.has(i))
  if (rest.length) groups.push({ name: null, members: rest })

  const span = Math.PI * 2 - (foot ? FOOT_SPAN : 0)
  // Gaps between sectors; with no foot the last sector also meets the first.
  const gapCount = groups.length > 1 ? groups.length - (foot ? 1 : 0) : 0
  const slot = count ? span / (count + gapCount * FACET_GAP) : span
  const start = FOOT + (foot ? FOOT_SPAN / 2 : slot / 2)

  const angles = new Array<number>(count).fill(0)
  const facets: Omit<FacetPlace, 'angle' | 'x' | 'y'>[] = []
  let cursor = 0
  groups.forEach((group, g) => {
    if (g > 0) cursor += FACET_GAP
    const first = cursor
    for (const index of group.members) {
      angles[index] = normalise(start + (cursor + 0.5) * slot)
      cursor += 1
    }
    if (group.name !== null && (map.syllabus.facets?.length ?? 0) > 1) {
      facets.push({
        name: group.name,
        from: normalise(start + (first + 0.5) * slot),
        to: normalise(start + (cursor - 0.5) * slot),
      })
    }
  })
  return { angles, slot, facets }
}

/** Sources and gaps on the orbit, each at its desired angle, relaxed apart. */
function orbitPlaces(
  map: MapResponse,
  angles: number[]
): { sources: OrbitPlace[]; gaps: OrbitPlace[] } {
  const items = [
    ...map.sources.map((source) => ({
      desired: sourceAngle(source.tags, angles),
      size: sourceSize(source.passage_count, source.tier),
      key: source.id,
    })),
    ...map.syllabus.gaps.map((gap, i) => ({
      desired:
        gap.key_concept !== null && gap.key_concept < angles.length
          ? angles[gap.key_concept]
          : FOOT,
      size: 12,
      // After every source id, so a gap sorts after a source at the same angle.
      key: Number.MAX_SAFE_INTEGER - map.syllabus.gaps.length + i,
    })),
  ]
  const placed = relaxAlongRing(
    items.map((item) => ({
      desired: item.desired,
      halfWidth: (item.size / 2 + 3) / ORBIT,
      key: item.key,
    }))
  )
  const places = items.map((item, i) => ({
    angle: placed[i],
    x: Math.cos(placed[i]) * ORBIT,
    y: Math.sin(placed[i]) * ORBIT,
    size: item.size,
  }))
  return { sources: places.slice(0, map.sources.length), gaps: places.slice(map.sources.length) }
}

/**
 * The weighted circular mean of the key concepts a source covers, or the foot.
 *
 * Circular because an arithmetic mean of 350° and 10° is 180°. A source whose
 * tags cancel out (two opposite key concepts, equally deep) has no meaningful
 * direction and goes to the foot with the untagged.
 */
export function sourceAngle(
  tags: { key_concept: number; depth: ConceptDepth }[],
  angles: number[]
): number {
  let x = 0
  let y = 0
  for (const tag of tags) {
    if (tag.key_concept < 0 || tag.key_concept >= angles.length) continue
    const weight = DEPTH_WEIGHT[tag.depth] ?? 1
    x += Math.cos(angles[tag.key_concept]) * weight
    y += Math.sin(angles[tag.key_concept]) * weight
  }
  if (Math.hypot(x, y) < 1e-6) return FOOT
  return normalise(Math.atan2(y, x))
}

/**
 * Push items apart along a circle until none overlap, each held to its
 * desired angle by a weak spring. Deterministic: fixed iterations, ties by key.
 */
export function relaxAlongRing(
  items: { desired: number; halfWidth: number; key: number }[]
): number[] {
  const n = items.length
  if (n === 0) return []
  // Shrink everything if the ring cannot hold it at full size.
  const total = items.reduce((sum, item) => sum + item.halfWidth * 2, 0)
  const scale = total > Math.PI * 2 * 0.95 ? (Math.PI * 2 * 0.95) / total : 1
  const half = items.map((item) => item.halfWidth * scale)
  const pos = items.map((item) => normalise(item.desired))

  // The spring runs for the first 120 passes only; the last 60 push apart and
  // nothing else, so what is left at the end is separated, not a compromise.
  for (let iteration = 0; iteration < 180; iteration += 1) {
    const order = [...pos.keys()].sort((a, b) => pos[a] - pos[b] || items[a].key - items[b].key)
    for (let k = 0; k < order.length; k += 1) {
      if (n < 2) break
      const a = order[k]
      const b = order[(k + 1) % order.length]
      let gap = pos[b] - pos[a]
      if (k === order.length - 1) gap += Math.PI * 2
      const need = half[a] + half[b]
      if (gap < need) {
        const shift = (need - gap) / 2
        pos[a] -= shift
        pos[b] += shift
      }
    }
    if (iteration >= 120) continue
    for (let i = 0; i < n; i += 1) {
      pos[i] = normalise(pos[i] + angleDelta(pos[i], items[i].desired) * 0.04)
    }
  }
  return pos.map(normalise)
}

interface CloudNode extends SimulationNodeDatum {
  id: number
  target: number
  r: number
}

/** The concept cloud: a short, fixed-length simulation from hashed starting points. */
function cloud(map: MapResponse, angles: number[], slot: number): Float32Array {
  const out = new Float32Array(map.concepts.length * 2)
  if (map.concepts.length === 0) return out

  const nodes: CloudNode[] = map.concepts.map((concept) => {
    const index = concept.key_concept
    const assigned = index !== null && index >= 0 && index < angles.length
    const target = assigned ? angles[index] : FOOT
    const spread = assigned ? slot * 0.45 : FOOT_SPAN * 0.45
    const angle = target + (hash(concept.id, 1) * 2 - 1) * spread
    const radius = CLOUD_IN + hash(concept.id, 2) * (CLOUD_OUT - CLOUD_IN)
    return {
      id: concept.id,
      target,
      r: conceptRadius(concept.source_ids.length),
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
    }
  })
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const links: SimulationLinkDatum<CloudNode>[] = map.links
    .filter((link) => byId.has(link.from) && byId.has(link.to) && link.from !== link.to)
    .map((link) => ({ source: link.from, target: link.to }))

  const simulation = forceSimulation<CloudNode>(nodes)
    .force(
      'link',
      forceLink<CloudNode, SimulationLinkDatum<CloudNode>>(links)
        .id((node) => node.id)
        .strength(0.04)
        .distance(34)
    )
    .force('charge', forceManyBody<CloudNode>().strength(-9).distanceMax(90))
    .force(
      'collide',
      forceCollide<CloudNode>().radius((node) => node.r + 3)
    )
    .force('band', bandForce())
    .force('pull', angularPull())
    .stop()
  simulation.tick(TICKS)

  nodes.forEach((node, i) => {
    out[i * 2] = node.x ?? 0
    out[i * 2 + 1] = node.y ?? 0
  })
  return out
}

/** Keep every concept between the ring and the orbit. */
function bandForce(): Force<CloudNode, undefined> {
  let nodes: CloudNode[] = []
  const force = (alpha: number) => {
    for (const node of nodes) {
      const x = node.x ?? 0
      const y = node.y ?? 0
      const r = Math.hypot(x, y) || 1
      const clamped = Math.min(CLOUD_OUT, Math.max(CLOUD_IN, r))
      if (clamped === r) continue
      const k = ((clamped - r) / r) * BAND_STRENGTH * Math.max(alpha, 0.3)
      node.vx = (node.vx ?? 0) + x * k
      node.vy = (node.vy ?? 0) + y * k
    }
  }
  force.initialize = (next: CloudNode[]) => {
    nodes = next
  }
  return force
}

/** Lean each concept toward its key concept's angle, tangentially. */
function angularPull(): Force<CloudNode, undefined> {
  let nodes: CloudNode[] = []
  const force = (alpha: number) => {
    for (const node of nodes) {
      const x = node.x ?? 0
      const y = node.y ?? 0
      const r = Math.hypot(x, y) || 1
      const delta = angleDelta(Math.atan2(y, x), node.target)
      // Along the tangent, by the arc length still to go.
      const step = delta * r * ANGULAR_PULL * alpha
      node.vx = (node.vx ?? 0) + (-y / r) * step
      node.vy = (node.vy ?? 0) + (x / r) * step
    }
  }
  force.initialize = (next: CloudNode[]) => {
    nodes = next
  }
  return force
}

/** A stable number in [0, 1) from an id — the layout's only randomness. */
export function hash(id: number, salt: number): number {
  let h = (Math.imul(id ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(salt, 0xc2b2ae35)) >>> 0
  h = Math.imul(h ^ (h >>> 16), 0x7feb352d) >>> 0
  h = Math.imul(h ^ (h >>> 15), 0x846ca68b) >>> 0
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296
}

export function normalise(angle: number): number {
  const turn = Math.PI * 2
  return ((angle % turn) + turn) % turn
}

/** The signed shortest turn from `from` to `to`, in (-π, π]. */
export function angleDelta(from: number, to: number): number {
  let delta = normalise(to - from)
  if (delta > Math.PI) delta -= Math.PI * 2
  return delta
}

/** The clockwise angle from `from` to `to`, in [0, 2π). */
function angleBetween(from: number, to: number): number {
  return normalise(to - from)
}
