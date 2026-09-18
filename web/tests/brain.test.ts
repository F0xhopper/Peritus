import { describe, expect, it } from 'vitest'

import expertMap from './fixtures/map.json' with { type: 'json' }
import type { MapResponse } from '@/lib/api/types'
import { computeLayout } from '@/lib/brain/layout'
import {
  FLATTEN_MS,
  IDLE_TILT,
  REVOLUTION_MS,
  advance,
  disengage,
  engage,
  initialMotion,
  isMoving,
  lcg,
  nearness,
  project,
  pulseDuration,
  unproject,
  type View,
} from '@/lib/brain/motion'
import {
  DIM,
  conceptAlpha,
  keyConceptLabel,
  paintBrain,
  type BrainPaintState,
} from '@/lib/brain/paint'
import { entrancePulses, hitFor, hitTest, mapSummary, selectionPulses } from '@/lib/brain/scene'
import {
  litBy,
  litByCitations,
  parseCited,
  selectionFromParams,
  selectionParams,
} from '@/lib/brain/selection'

const map = expertMap as MapResponse
const layout = computeLayout(map)

// ── selection ───────────────────────────────────────────────────────────────

describe('selection in the URL', () => {
  const params = (query: string) => new URLSearchParams(query)

  it('reads a source, a concept, a key concept by label and a gap', () => {
    expect(selectionFromParams(params('source=804'), map)).toEqual({ kind: 'source', id: 804 })
    expect(selectionFromParams(params('node=5004'), map)).toEqual({ kind: 'concept', id: 5004 })
    expect(selectionFromParams(params('concept=Acaricide%20resistance'), map)).toEqual({
      kind: 'keyConcept',
      index: 1,
    })
    expect(selectionFromParams(params('gap=0'), map)).toEqual({ kind: 'gap', index: 0 })
  })

  it('ignores what names nothing, rather than selecting something else', () => {
    expect(selectionFromParams(params('source=abc'), map)).toBeNull()
    expect(selectionFromParams(params('concept=not%20a%20key%20concept'), map)).toBeNull()
    expect(selectionFromParams(params('gap=9'), map)).toBeNull()
  })

  it('writes one kind and clears the others', () => {
    expect(selectionParams({ kind: 'keyConcept', index: 2 }, map)).toEqual({
      source: null,
      node: null,
      concept: 'drone brood removal',
      gap: null,
    })
    expect(selectionParams(null, map)).toEqual({
      source: null,
      node: null,
      concept: null,
      gap: null,
    })
  })
})

describe('what a selection lights', () => {
  it('a source lights the concepts drawn from it and the key concepts it covers', () => {
    const lit = litBy(map, { kind: 'source', id: 815 })!
    expect([...lit.sources]).toEqual([815])
    expect(lit.concepts.has(5004)).toBe(true)
    expect(lit.concepts.has(5001)).toBe(false)
    expect([...lit.keyConcepts].sort()).toEqual([2, 4])
  })

  it('a concept lights its sources, its key concept and its part_of neighbours', () => {
    const lit = litBy(map, { kind: 'concept', id: 5019 })!
    expect([...lit.sources].sort()).toEqual([815, 817, 819])
    expect([...lit.keyConcepts]).toEqual([4])
    expect(lit.concepts.has(5017) && lit.concepts.has(5018) && lit.concepts.has(5020)).toBe(true)
  })

  it('a key concept lights its sector, the sources tagged with it and its missing text', () => {
    const lit = litBy(map, { kind: 'keyConcept', index: 4 })!
    expect(lit.sources.has(817) && lit.sources.has(815)).toBe(true)
    expect(lit.concepts.has(5019)).toBe(true)
    expect([...lit.gaps]).toEqual([0])
  })

  it('an answer lights its cited sources and everything they feed', () => {
    const lit = litByCitations(map, parseCited('804,812,junk,999999'))!
    expect([...lit.sources].sort()).toEqual([804, 812])
    expect(lit.concepts.has(5001) && lit.concepts.has(5003)).toBe(true)
    expect(litByCitations(map, [424242])).toBeNull()
  })
})

// ── motion ──────────────────────────────────────────────────────────────────

describe('idle is alive, engaged is still', () => {
  it('opens every visit on the same tilted frame, and flat under reduced motion', () => {
    expect(initialMotion(0, false)).toMatchObject({ tilt: IDLE_TILT, rotation: 0, engaged: false })
    const reduced = initialMotion(0, true)
    expect(reduced).toMatchObject({ tilt: 1, engaged: true })
    expect(isMoving(reduced)).toBe(false)
  })

  it('turns once in eight minutes while idle', () => {
    const later = advance(initialMotion(0, false), REVOLUTION_MS / 4)
    expect(later.rotation).toBeCloseTo(Math.PI / 2)
  })

  it('flattens and turns back to rest by the shortest way when engaged', () => {
    const idle = advance(initialMotion(0, false), REVOLUTION_MS * 0.9) // 324° round
    const engaged = engage(idle, REVOLUTION_MS * 0.9)
    const settled = advance(engaged, REVOLUTION_MS * 0.9 + FLATTEN_MS * 3)
    expect(settled.tilt).toBe(1)
    expect(settled.rotation).toBeCloseTo(0)
    // Mid-ease it went forward to 360°, not back through 180°.
    const mid = advance(engaged, REVOLUTION_MS * 0.9 + FLATTEN_MS / 2)
    expect(Math.abs(mid.rotation)).toBeLessThan(Math.PI / 5)
    expect(isMoving(settled)).toBe(false)
  })

  it('stays still once flat, and eases back into the idle tilt when let go', () => {
    const flat = advance(engage(initialMotion(0, false), 0), FLATTEN_MS * 2)
    expect(advance(flat, 60_000).rotation).toBe(flat.rotation)
    const released = advance(disengage(flat, 60_000), 60_000 + FLATTEN_MS * 4)
    expect(released.tilt).toBeCloseTo(IDLE_TILT)
    expect(isMoving(released)).toBe(true)
  })
})

describe('the projection', () => {
  const view: View = { k: 1.7, x: 300, y: 200, tilt: 0.62, rotation: 1.1 }

  it('inverts exactly, so a click during the flatten lands on what is under it', () => {
    const [sx, sy] = project(123, -45, view)
    const [x, y] = unproject(sx, sy, view)
    expect(x).toBeCloseTo(123)
    expect(y).toBeCloseTo(-45)
  })

  it('has no near side on a flat map', () => {
    expect(nearness(0, 300, { ...view, tilt: 1 }, 300)).toBe(0)
    expect(nearness(0, 300, { ...view, rotation: 0 }, 300)).toBeGreaterThan(0.9)
  })

  it('times a pulse between 400 and 700ms, longer for a longer dendrite', () => {
    expect(pulseDuration([0, 0], [0, 1])).toBeGreaterThanOrEqual(400)
    expect(pulseDuration([0, 0], [0, 10_000])).toBe(700)
  })

  it('fires from a deterministic sequence', () => {
    const a = lcg(7)
    const b = lcg(7)
    expect([a(), a(), a()]).toEqual([b(), b(), b()])
  })
})

// ── scene ───────────────────────────────────────────────────────────────────

describe('hit-testing', () => {
  it('finds a key concept, a source, a gap and a concept at their own positions', () => {
    const kc = layout.keyConcepts[2]
    expect(hitTest(map, layout, kc.x, kc.y, 1)).toEqual({ kind: 'keyConcept', index: 2 })
    const source = layout.sources[3]
    expect(hitTest(map, layout, source.x, source.y, 1)).toEqual({ kind: 'source', index: 3 })
    const gap = layout.gaps[1]
    expect(hitTest(map, layout, gap.x, gap.y, 1)).toEqual({ kind: 'gap', index: 1 })
    const i = map.concepts.findIndex((c) => c.id === 5004)
    expect(hitTest(map, layout, layout.concepts[i * 2], layout.concepts[i * 2 + 1], 0)).toEqual({
      kind: 'concept',
      index: i,
    })
  })

  it('finds nothing in empty space', () => {
    expect(hitTest(map, layout, 0, 0, 1)).toBeNull()
  })

  it('maps a selection to what is drawn, or to nothing', () => {
    expect(hitFor(map, { kind: 'source', id: 815 })).toEqual({ kind: 'source', index: 2 })
    expect(hitFor(map, { kind: 'concept', id: 123 })).toBeNull()
  })
})

describe('pulses', () => {
  it('run inward on entrance: sources to concepts, then concepts to their key concepts', () => {
    const pulses = entrancePulses(map, layout, 0)
    expect(pulses.length).toBeGreaterThan(map.concepts.length)
    const later = pulses.filter((pulse) => pulse.start >= 650)
    for (const pulse of later) {
      expect(Math.hypot(...pulse.to)).toBeLessThan(Math.hypot(...pulse.from))
    }
  })

  it('run once down each lit dendrite of a selection', () => {
    const lit = litBy(map, { kind: 'source', id: 815 })!
    const pulses = selectionPulses(map, layout, lit, 0)
    // Concepts drawn from it, plus the two key concepts it is tagged with.
    const concepts = map.concepts.filter((c) => c.source_ids.includes(815)).length
    expect(pulses).toHaveLength(concepts + 2)
  })
})

describe('the accessible summary', () => {
  it('says what the canvas holds, including what is missing', () => {
    expect(mapSummary(map)).toBe(
      "Map of this expert's knowledge: 10 sources, 5 key concepts in 2 facets, 22 concepts; 2 named texts missing."
    )
  })
})

// ── paint ───────────────────────────────────────────────────────────────────

/** A 2D context that records what was drawn, with the alpha and colour of each fill. */
function recordingContext() {
  const fills: { alpha: number; style: unknown }[] = []
  const strokes: { alpha: number; style: unknown }[] = []
  const texts: string[] = []
  const state: Record<string, unknown> = { globalAlpha: 1, fillStyle: '', strokeStyle: '' }
  const context = new Proxy(state, {
    get(target, key) {
      if (key in target) return target[key as string]
      if (key === 'fill')
        return () => fills.push({ alpha: target.globalAlpha as number, style: target.fillStyle })
      if (key === 'stroke')
        return () =>
          strokes.push({ alpha: target.globalAlpha as number, style: target.strokeStyle })
      if (key === 'fillText') return (text: string) => texts.push(text)
      if (key === 'measureText') return (text: string) => ({ width: text.length * 6 })
      if (key === 'createLinearGradient') return () => ({ addColorStop: () => undefined })
      return () => undefined
    },
    set(target, key, value) {
      if (key === 'shadowBlur') throw new Error('shadowBlur is never used: glow is a sprite')
      target[key as string] = value
      return true
    },
  }) as unknown as CanvasRenderingContext2D
  return { context, fills, strokes, texts }
}

function state(overrides: Partial<BrainPaintState> = {}): BrainPaintState {
  return {
    map,
    layout,
    view: { k: 1, x: 400, y: 400, tilt: 1, rotation: 0 },
    width: 800,
    height: 800,
    dpr: 1,
    colours: {
      fg: 'FG',
      fg2: 'FG2',
      fg3: 'FG3',
      fg4: 'FG4',
      border: 'BORDER',
      warn: 'WARN',
      bg: 'BG',
      font: 'system-ui',
    },
    lit: null,
    selected: null,
    hovered: null,
    pulses: [],
    now: 0,
    labelBudget: 12,
    glow: null,
    ...overrides,
  }
}

describe('painting', () => {
  it('labels every key concept, without its trailing parenthetical', () => {
    const { context, texts } = recordingContext()
    paintBrain(context, state())
    for (const concept of map.syllabus.key_concepts) {
      expect(texts).toContain(keyConceptLabel(concept.label))
    }
    expect(keyConceptLabel('Being, essence, and existence (act/potency)')).toBe(
      'Being, essence, and existence'
    )
    expect(texts).toContain('BIOLOGY')
  })

  it('uses warn only for a dispute — the one status on the canvas', () => {
    const { context, strokes, fills } = recordingContext()
    paintBrain(context, state())
    const warned = strokes.filter((stroke) => stroke.style === 'WARN')
    expect(warned).toHaveLength(map.concepts.filter((c) => c.disputes > 0).length)
    expect(fills.some((fill) => fill.style === 'WARN')).toBe(false)
  })

  it('drops everything unlit to 15% when something is selected', () => {
    const { context, fills } = recordingContext()
    const lit = litBy(map, { kind: 'source', id: 815 })
    paintBrain(context, state({ lit, selected: { kind: 'source', index: 2 } }))
    const alphas = fills.map((fill) => fill.alpha)
    expect(alphas.some((alpha) => alpha <= DIM + 0.001)).toBe(true)
    expect(alphas.some((alpha) => alpha >= 0.99)).toBe(true)
  })

  it('draws the spine brighter than the rest of the cloud, and a top-up faintest', () => {
    expect(conceptAlpha(4, false)).toBeGreaterThan(conceptAlpha(3, false))
    expect(conceptAlpha(3, false)).toBeGreaterThan(conceptAlpha(2, false))
    expect(conceptAlpha(1, true)).toBeLessThan(conceptAlpha(2, false))
  })

  it('names the source under the pointer, and only that one', () => {
    const { context, texts } = recordingContext()
    paintBrain(context, state({ hovered: { kind: 'source', index: 1 } }))
    expect(texts.some((text) => text.startsWith('Amitraz resistance'))).toBe(true)
    expect(texts.some((text) => text.startsWith('Drone brood trapping'))).toBe(false)
  })
})
