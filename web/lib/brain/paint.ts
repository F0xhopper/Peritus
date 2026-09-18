import type { MapResponse } from '@/lib/api/types'
import { CLOUD_IN, ORBIT, RING, conceptRadius, type BrainLayout } from '@/lib/brain/layout'
import { nearness, project, type Pulse, type View } from '@/lib/brain/motion'
import type { Lit } from '@/lib/brain/selection'

/**
 * Drawing the expert's map — a pure function of the state handed to it.
 *
 * docs/plans/expert-brain.md, phase 4. Everything is projected to the screen
 * first and drawn there, so a disc stays round and a label stays upright when
 * the map is tilted and turning; the one exception is the orbits, which are
 * ellipses because a tilted circle is one.
 *
 * **The chrome stays monochrome.** Facets are position, never hue; a source's
 * tier is shape and fill, never hue. The only colour on the canvas is `--warn`,
 * on a concept whose claims were judged to disagree — a status, like every other
 * colour in the product.
 *
 * It reads no refs, no DOM beyond the context it is given, and no clock: the
 * time a pulse is at arrives as `now`.
 */

export interface BrainColours {
  fg: string
  fg2: string
  fg3: string
  fg4: string
  border: string
  warn: string
  bg: string
  /** The resolved font family: a canvas cannot read `var(--font-sans)`. */
  font: string
}

export interface BrainPaintState {
  map: MapResponse
  layout: BrainLayout
  view: View
  /** CSS pixels, and the device pixel ratio the canvas was sized at. */
  width: number
  height: number
  dpr: number
  colours: BrainColours
  /** What the selection (or a cited answer) lights; null lights everything. */
  lit: Lit | null
  /** The one thing selected, whose label is forced. */
  selected: Hit | null
  hovered: Hit | null
  pulses: Pulse[]
  now: number
  /** How many concept labels may be drawn besides the forced ones. */
  labelBudget: number
  /** False: only the hovered and selected thing is named (the small build form). */
  labels?: boolean
  /** A pre-rendered soft glow for the spine, or null (tests). Never `shadowBlur`. */
  glow: CanvasImageSource | null
}

/** Something on the map a pointer can land on. */
export type Hit =
  | { kind: 'concept'; index: number }
  | { kind: 'keyConcept'; index: number }
  | { kind: 'source'; index: number }
  | { kind: 'gap'; index: number }

/** Everything not lit drops to this when something is selected. */
export const DIM = 0.15
/** Concepts at least this many sources discuss are the spine: glow, and a label. */
export const SPINE_SOURCES = 4

// The plan said 28; "Being, essence, and existence", its own example, is 29.
const KEY_LABEL_CHARS = 30
const LABEL_CHARS = 30

export function paintBrain(context: CanvasRenderingContext2D, state: BrainPaintState): void {
  const { width, height, dpr } = state
  context.save()
  context.setTransform(dpr, 0, 0, dpr, 0, 0)
  context.clearRect(0, 0, width, height)

  paintOrbits(context, state)
  paintDendrites(context, state)
  paintPulses(context, state)
  paintConcepts(context, state)
  paintKeyConcepts(context, state)
  paintOrbitItems(context, state)
  paintLabels(context, state)

  context.restore()
}

/** The alpha a thing gets when something is selected and it is not lit. */
function dimmed(lit: Lit | null, isLit: boolean): number {
  return lit === null || isLit ? 1 : DIM
}

/** A layout size in screen pixels, never smaller than `min`. */
function px(size: number, view: View, min: number): number {
  return Math.max(min, size * view.k)
}

// ── orbits ──────────────────────────────────────────────────────────────────

function paintOrbits(context: CanvasRenderingContext2D, state: BrainPaintState): void {
  const { view, colours } = state
  context.lineWidth = 1
  context.strokeStyle = colours.border

  context.beginPath()
  context.ellipse(view.x, view.y, RING * view.k, RING * view.k * view.tilt, 0, 0, Math.PI * 2)
  context.stroke()

  context.setLineDash([3, 5])
  context.beginPath()
  context.ellipse(view.x, view.y, ORBIT * view.k, ORBIT * view.k * view.tilt, 0, 0, Math.PI * 2)
  context.stroke()
  context.setLineDash([])
}

// ── dendrites ───────────────────────────────────────────────────────────────

/**
 * A dendrite: a quadratic curve whose control point is pulled a fifth of the
 * way toward the nucleus, so every link bows inward and the whole reads as
 * radial rather than as a net. The projection is linear, so projecting the
 * control point projects the curve.
 */
export function dendrite(
  from: [number, number],
  to: [number, number]
): { from: [number, number]; control: [number, number]; to: [number, number] } {
  const mx = (from[0] + to[0]) / 2
  const my = (from[1] + to[1]) / 2
  return { from, control: [mx * 0.8, my * 0.8], to }
}

/** A point `t` of the way along a dendrite. */
export function alongDendrite(
  from: [number, number],
  to: [number, number],
  t: number
): [number, number] {
  const { control } = dendrite(from, to)
  const u = 1 - t
  return [
    u * u * from[0] + 2 * u * t * control[0] + t * t * to[0],
    u * u * from[1] + 2 * u * t * control[1] + t * t * to[1],
  ]
}

function strokeDendrite(
  context: CanvasRenderingContext2D,
  view: View,
  from: [number, number],
  to: [number, number]
): void {
  const curve = dendrite(from, to)
  const [ax, ay] = project(curve.from[0], curve.from[1], view)
  const [cx, cy] = project(curve.control[0], curve.control[1], view)
  const [bx, by] = project(curve.to[0], curve.to[1], view)
  context.moveTo(ax, ay)
  context.quadraticCurveTo(cx, cy, bx, by)
}

function paintDendrites(context: CanvasRenderingContext2D, state: BrainPaintState): void {
  const { map, layout, view, colours, lit } = state
  const keyPoint = (index: number): [number, number] | null => {
    const place = layout.keyConcepts[index]
    return place ? [place.x, place.y] : null
  }
  const conceptIndex = new Map(map.concepts.map((concept, i) => [concept.id, i]))
  const conceptPoint = (id: number): [number, number] | null => {
    const i = conceptIndex.get(id)
    return i === undefined ? null : [layout.concepts[i * 2], layout.concepts[i * 2 + 1]]
  }
  const sourceIndex = new Map(map.sources.map((source, i) => [source.id, i]))

  context.lineWidth = 1
  context.strokeStyle = colours.fg3

  // At rest: every source to the key concepts it was tagged with, faint — and
  // fainter the more of them there are, or a real corpus is a net again.
  const tagLines = map.sources.reduce((sum, source) => sum + source.tags.length, 0)
  const density = Math.min(1, 36 / Math.max(1, tagLines))
  context.globalAlpha = (lit ? 0.06 : 0.16) * Math.max(0.35, density)
  context.beginPath()
  map.sources.forEach((source, i) => {
    if (lit?.sources.has(source.id)) return
    const from = layout.sources[i]
    for (const tag of source.tags) {
      const to = keyPoint(tag.key_concept)
      if (to) strokeDendrite(context, view, [from.x, from.y], to)
    }
  })
  context.stroke()

  // `part_of` between concepts, faint.
  context.globalAlpha =
    (lit ? 0.05 : 0.22) * Math.max(0.35, Math.min(1, 60 / Math.max(1, map.links.length)))
  context.beginPath()
  for (const link of map.links) {
    const a = conceptPoint(link.from)
    const b = conceptPoint(link.to)
    if (a && b) strokeDendrite(context, view, a, b)
  }
  context.stroke()

  if (!lit) {
    context.globalAlpha = 1
    return
  }

  // Lit: every source → concept dendrite among lit things, and the lit
  // sources' tags. Tapered: bright at the source, fading inward.
  context.lineWidth = 1.2
  for (const sourceId of lit.sources) {
    const i = sourceIndex.get(sourceId)
    if (i === undefined) continue
    const from: [number, number] = [layout.sources[i].x, layout.sources[i].y]
    const targets: [number, number][] = []
    for (const concept of map.concepts) {
      if (!lit.concepts.has(concept.id) || !concept.source_ids.includes(sourceId)) continue
      const to = conceptPoint(concept.id)
      if (to) targets.push(to)
    }
    for (const tag of map.sources[i].tags) {
      if (!lit.keyConcepts.has(tag.key_concept)) continue
      const to = keyPoint(tag.key_concept)
      if (to) targets.push(to)
    }
    for (const to of targets) {
      const [ax, ay] = project(from[0], from[1], view)
      const [bx, by] = project(to[0], to[1], view)
      const gradient = context.createLinearGradient(ax, ay, bx, by)
      gradient.addColorStop(0, colours.fg)
      gradient.addColorStop(1, colours.fg4)
      context.strokeStyle = gradient
      context.globalAlpha = 0.7
      context.beginPath()
      strokeDendrite(context, view, from, to)
      context.stroke()
    }
  }
  context.globalAlpha = 1
}

function paintPulses(context: CanvasRenderingContext2D, state: BrainPaintState): void {
  const { pulses, now, view, colours } = state
  context.fillStyle = colours.fg
  for (const pulse of pulses) {
    const t = (now - pulse.start) / pulse.duration
    if (t < 0 || t > 1) continue
    const [lx, ly] = alongDendrite(pulse.from, pulse.to, t)
    const [x, y] = project(lx, ly, view)
    // Brightest mid-flight; fades in and out rather than popping.
    context.globalAlpha = Math.sin(Math.PI * t) * 0.95
    context.beginPath()
    context.arc(x, y, 2.4, 0, Math.PI * 2)
    context.fill()
  }
  context.globalAlpha = 1
}

// ── things ──────────────────────────────────────────────────────────────────

/** A concept's resting alpha: 2 sources 0.35, 3 → 0.55, 4 or more 0.8; topped up 0.2. */
export function conceptAlpha(sourceCount: number, toppedUp: boolean): number {
  if (toppedUp || sourceCount < 2) return 0.2
  if (sourceCount >= SPINE_SOURCES) return 0.8
  return sourceCount === 2 ? 0.35 : 0.55
}

function paintConcepts(context: CanvasRenderingContext2D, state: BrainPaintState): void {
  const { map, layout, view, colours, lit, glow } = state
  map.concepts.forEach((concept, i) => {
    const lx = layout.concepts[i * 2]
    const ly = layout.concepts[i * 2 + 1]
    const [x, y] = project(lx, ly, view)
    const near = nearness(lx, ly, view, CLOUD_IN)
    const isLit = lit?.concepts.has(concept.id) ?? false
    const radius = px(conceptRadius(concept.source_ids.length), view, 1.6) * (1 + near * 0.15)
    const base = isLit ? 1 : conceptAlpha(concept.source_ids.length, concept.topped_up)
    const alpha = Math.min(1, base * (1 + near * 0.2)) * dimmed(lit, isLit)

    if (glow && concept.source_ids.length >= SPINE_SOURCES && (lit === null || isLit)) {
      const size = radius * 7
      context.globalAlpha = 0.5 * alpha
      context.drawImage(glow, x - size / 2, y - size / 2, size, size)
    }

    context.globalAlpha = alpha
    context.fillStyle = colours.fg
    context.beginPath()
    context.arc(x, y, radius, 0, Math.PI * 2)
    context.fill()

    // A dispute is a status: the only hue on the canvas.
    if (concept.disputes > 0) {
      context.globalAlpha = Math.max(0.5, alpha)
      context.strokeStyle = colours.warn
      context.lineWidth = 1.5
      context.beginPath()
      context.arc(x, y, radius + 3, 0, Math.PI * 2)
      context.stroke()
    }
  })
  context.globalAlpha = 1
}

function paintKeyConcepts(context: CanvasRenderingContext2D, state: BrainPaintState): void {
  const { layout, view, colours, lit, selected } = state
  for (const place of layout.keyConcepts) {
    const [x, y] = project(place.x, place.y, view)
    const near = nearness(place.x, place.y, view, RING)
    const isLit = lit?.keyConcepts.has(place.index) ?? false
    const radius = px(place.r, view, 4) * (1 + near * 0.12)
    context.globalAlpha = Math.max(DIM + 0.1, 0.92 * dimmed(lit, isLit))
    context.fillStyle = colours.fg
    context.beginPath()
    context.arc(x, y, radius, 0, Math.PI * 2)
    context.fill()

    if (selected?.kind === 'keyConcept' && selected.index === place.index) {
      context.globalAlpha = 1
      context.strokeStyle = colours.fg
      context.lineWidth = 1.5
      context.beginPath()
      context.arc(x, y, radius + 4, 0, Math.PI * 2)
      context.stroke()
    }
  }
  context.globalAlpha = 1
}

/**
 * Sources as rounded squares, gaps as dashed hollow ones.
 *
 * Tier is shape and fill: a primary source is filled, a secondary one outlined,
 * a tertiary one outlined and smaller (its size already says so, see
 * `sourceSize`). A gap is what the plan named and the build never found — the
 * same square, hollow and dashed, where it would have stood.
 */
function paintOrbitItems(context: CanvasRenderingContext2D, state: BrainPaintState): void {
  const { map, layout, view, colours, lit, selected } = state
  map.sources.forEach((source, i) => {
    const place = layout.sources[i]
    const [x, y] = project(place.x, place.y, view)
    const near = nearness(place.x, place.y, view, ORBIT)
    const size = px(place.size, view, 5) * (1 + near * 0.15)
    const isLit = lit?.sources.has(source.id) ?? false
    const alpha = Math.min(1, 0.85 * (1 + near * 0.15)) * dimmed(lit, isLit)
    if (source.pending) {
      // Being read in: hollow, breathing slowly, at the foot of the orbit.
      context.globalAlpha = 0.45 + 0.35 * Math.sin(state.now / 450)
      context.setLineDash([3, 2])
      context.strokeStyle = colours.fg2
      context.lineWidth = 1.2
      roundedSquare(context, x, y, size)
      context.stroke()
      context.setLineDash([])
      return
    }
    context.globalAlpha = alpha
    roundedSquare(context, x, y, size)
    if (source.tier === 'primary') {
      context.fillStyle = colours.fg2
      context.fill()
    } else {
      context.fillStyle = colours.bg
      context.fill()
      context.strokeStyle = colours.fg2
      context.lineWidth = 1.2
      context.stroke()
    }
    if (selected?.kind === 'source' && selected.index === i) {
      context.globalAlpha = 1
      context.strokeStyle = colours.fg
      context.lineWidth = 1.5
      roundedSquare(context, x, y, size + 7)
      context.stroke()
    }
  })

  map.syllabus.gaps.forEach((_gap, i) => {
    const place = layout.gaps[i]
    const [x, y] = project(place.x, place.y, view)
    const size = px(place.size, view, 6)
    const isLit = lit?.gaps.has(i) ?? false
    context.globalAlpha = 0.9 * dimmed(lit, isLit)
    context.setLineDash([2, 2])
    context.strokeStyle = colours.fg3
    context.lineWidth = 1.2
    roundedSquare(context, x, y, size)
    context.stroke()
    context.setLineDash([])
    if (selected?.kind === 'gap' && selected.index === i) {
      context.globalAlpha = 1
      context.strokeStyle = colours.fg
      roundedSquare(context, x, y, size + 7)
      context.stroke()
    }
  })
  context.globalAlpha = 1
}

function roundedSquare(context: CanvasRenderingContext2D, x: number, y: number, size: number) {
  const half = size / 2
  const r = Math.min(3, size / 4)
  context.beginPath()
  context.roundRect(x - half, y - half, size, size, r)
}

// ── labels ──────────────────────────────────────────────────────────────────

/** A key concept's label: the trailing parenthetical dropped, elided at 30. */
export function keyConceptLabel(label: string): string {
  const bare = label.replace(/\s*\([^()]*\)\s*$/, '').trim() || label
  return elide(bare, KEY_LABEL_CHARS)
}

export function elide(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text
}

interface LabelBox {
  x0: number
  y0: number
  x1: number
  y1: number
}

/**
 * Labels, greedily placed in priority order and skipped where they would
 * collide — except the selected and hovered ones, which are forced: they are
 * the answer to what the reader just did.
 *
 * Priority: the selected and hovered thing, facet names and key concepts
 * (always), then lit concepts, then the spine — within `labelBudget`. Sources are
 * labelled only on hover and selection: thirty-seven titles at once is the
 * table's job.
 */
function paintLabels(context: CanvasRenderingContext2D, state: BrainPaintState): void {
  const { map, layout, view, colours, lit, selected, hovered, labelBudget } = state
  const placed: LabelBox[] = []
  context.textAlign = 'center'
  context.textBaseline = 'top'

  const place = (
    text: string,
    x: number,
    y: number,
    colour: string,
    forced: boolean,
    size = 11,
    align: CanvasTextAlign = 'center'
  ): boolean => {
    context.font = `${size}px ${colours.font}`
    context.textAlign = align
    const width = context.measureText(text).width
    const left = align === 'left' ? x : align === 'right' ? x - width : x - width / 2
    const box = { x0: left - 2, y0: y, x1: left + width + 2, y1: y + size + 3 }
    const collides = placed.some(
      (other) => box.x0 < other.x1 && box.x1 > other.x0 && box.y0 < other.y1 && box.y1 > other.y0
    )
    if (collides && !forced) return false
    placed.push(box)
    context.fillStyle = colour
    context.fillText(text, x, y)
    return true
  }

  const isHit = (hit: Hit | null, kind: Hit['kind'], index: number) =>
    hit !== null && hit.kind === kind && hit.index === index

  // Forced first so nothing else claims their space.
  for (const hit of [selected, hovered]) {
    if (!hit) continue
    const label = hitLabel(map, hit)
    const [x, y, r] = hitScreen(state, hit)
    context.globalAlpha = 1
    place(label, x, y + r + 4, colours.fg, true, 12)
  }

  if (state.labels === false) {
    context.globalAlpha = 1
    return
  }

  // Facet names, small caps on each sector's bisector just outside the orbit,
  // like the points of a compass. Inside the ring five of them collided with
  // each other and with the nucleus on a real syllabus.
  context.globalAlpha = lit ? 0.4 : 0.9
  for (const facet of layout.facets) {
    const [x, y] = project(facet.x, facet.y, view)
    const spot = radialLabel(x, y, view, 0, 9)
    place(elide(facet.name.toUpperCase(), 26), spot.x, spot.y, colours.fg3, false, 9, spot.align)
  }

  // Key concepts, always — set radially outward from the disc, so ten of them
  // round a ring do not stack on each other the way labels under each disc did.
  for (const kc of layout.keyConcepts) {
    if (isHit(selected, 'keyConcept', kc.index) || isHit(hovered, 'keyConcept', kc.index)) continue
    const [x, y] = project(kc.x, kc.y, view)
    const isLit = lit?.keyConcepts.has(kc.index) ?? false
    context.globalAlpha = lit && !isLit ? 0.4 : 1
    const spot = radialLabel(x, y, view, px(kc.r, view, 4) + 5, 11)
    place(
      keyConceptLabel(map.syllabus.key_concepts[kc.index].label),
      spot.x,
      spot.y,
      colours.fg2,
      true,
      11,
      spot.align
    )
  }

  // Concepts: lit ones first, then the spine, within the budget.
  const order = map.concepts
    .map((concept, i) => ({ concept, i }))
    .filter(({ concept }) =>
      lit ? lit.concepts.has(concept.id) : concept.source_ids.length >= SPINE_SOURCES
    )
    .sort(
      (a, b) =>
        b.concept.source_ids.length - a.concept.source_ids.length ||
        b.concept.degree - a.concept.degree ||
        a.concept.id - b.concept.id
    )
  let budget = labelBudget
  context.globalAlpha = 1
  for (const { concept, i } of order) {
    if (budget <= 0) break
    if (isHit(selected, 'concept', i) || isHit(hovered, 'concept', i)) continue
    const [x, y] = project(layout.concepts[i * 2], layout.concepts[i * 2 + 1], view)
    const r = px(conceptRadius(concept.source_ids.length), view, 1.6)
    if (place(elide(concept.label, LABEL_CHARS), x, y + r + 3, colours.fg3, false)) budget -= 1
  }
  context.globalAlpha = 1
}

/**
 * Where a label goes to sit radially outward from a point: to its right on the
 * right of the map, to its left on the left, above or below at the top and the
 * bottom. `y` is the label's top.
 */
function radialLabel(
  x: number,
  y: number,
  view: View,
  gap: number,
  size: number
): { x: number; y: number; align: CanvasTextAlign } {
  const dx = x - view.x
  const dy = y - view.y
  const length = Math.hypot(dx, dy) || 1
  const ux = dx / length
  const uy = dy / length
  const ax = x + ux * gap
  const ay = y + uy * gap
  if (ux > 0.38) return { x: ax, y: ay - size / 2 - 1, align: 'left' }
  if (ux < -0.38) return { x: ax, y: ay - size / 2 - 1, align: 'right' }
  // Near the top or the bottom: above or below, leaning away from the axis so
  // two neighbours either side of it do not meet in the middle.
  const top = uy < 0 ? ay - size - 2 : ay
  if (ux > 0.08) return { x: ax - 6, y: top, align: 'left' }
  if (ux < -0.08) return { x: ax + 6, y: top, align: 'right' }
  return { x: ax, y: top, align: 'center' }
}

export function hitLabel(map: MapResponse, hit: Hit): string {
  switch (hit.kind) {
    case 'concept':
      return elide(map.concepts[hit.index]?.label ?? '', LABEL_CHARS + 10)
    case 'keyConcept':
      return keyConceptLabel(map.syllabus.key_concepts[hit.index]?.label ?? '')
    case 'source':
      return elide(map.sources[hit.index]?.title ?? '', 44)
    case 'gap':
      return `Missing: ${elide(map.syllabus.gaps[hit.index]?.title ?? '', 36)}`
  }
}

/** Where a hit is on screen, and its radius there. */
export function hitScreen(
  state: Pick<BrainPaintState, 'map' | 'layout' | 'view'>,
  hit: Hit
): [number, number, number] {
  const { layout, view, map } = state
  switch (hit.kind) {
    case 'concept': {
      const [x, y] = project(
        layout.concepts[hit.index * 2],
        layout.concepts[hit.index * 2 + 1],
        view
      )
      return [x, y, px(conceptRadius(map.concepts[hit.index]?.source_ids.length ?? 0), view, 1.6)]
    }
    case 'keyConcept': {
      const place = layout.keyConcepts[hit.index]
      const [x, y] = project(place.x, place.y, view)
      return [x, y, px(place.r, view, 4)]
    }
    case 'source': {
      const place = layout.sources[hit.index]
      const [x, y] = project(place.x, place.y, view)
      return [x, y, px(place.size, view, 5) / 2]
    }
    case 'gap': {
      const place = layout.gaps[hit.index]
      const [x, y] = project(place.x, place.y, view)
      return [x, y, px(place.size, view, 6) / 2]
    }
  }
}

/** The theme's colours, with the fallbacks that keep a canvas drawable. */
export function readBrainColours(element: Element): BrainColours {
  const style = getComputedStyle(element)
  const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
  return {
    fg: read('--fg', '#ececee'),
    fg2: read('--fg-2', '#b4b4bb'),
    fg3: read('--fg-3', '#8a8a93'),
    fg4: read('--fg-4', '#55555c'),
    border: read('--border', '#26262a'),
    warn: read('--warn', '#e0a526'),
    bg: read('--bg', '#0f0f11'),
    font: style.fontFamily || 'system-ui, sans-serif',
  }
}
