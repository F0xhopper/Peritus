import { describe, expect, it } from 'vitest'

import expertMap from './fixtures/map.json' with { type: 'json' }
import type { MapResponse } from '@/lib/api/types'
import {
  CLOUD_IN,
  CLOUD_OUT,
  FOOT,
  ORBIT,
  RING,
  angleDelta,
  computeLayout,
  relaxAlongRing,
  sourceAngle,
} from '@/lib/brain/layout'

/**
 * The map's layout (docs/plans/expert-brain.md, phase 3).
 *
 * Its "done when" is the first test here: the same payload gives byte-identical
 * positions twice. A map that lands somewhere new on each visit cannot be
 * learned, and nothing about a plausible-looking canvas would say it had moved.
 */

const map = expertMap as MapResponse

describe('determinism', () => {
  it('lays the same payload out byte for byte the same, twice', () => {
    const a = computeLayout(map)
    const b = computeLayout(structuredClone(map))
    expect(Buffer.from(a.concepts.buffer)).toEqual(Buffer.from(b.concepts.buffer))
    expect(a.sources).toEqual(b.sources)
    expect(a.keyConcepts).toEqual(b.keyConcepts)
    expect(a.gaps).toEqual(b.gaps)
  })
})

describe('the rings', () => {
  const layout = computeLayout(map)

  it('puts key concepts on the ring, sources and gaps on the orbit', () => {
    for (const place of layout.keyConcepts) expect(Math.hypot(place.x, place.y)).toBeCloseTo(RING)
    for (const place of [...layout.sources, ...layout.gaps]) {
      expect(Math.hypot(place.x, place.y)).toBeCloseTo(ORBIT)
    }
  })

  it('keeps every concept in the band between them', () => {
    for (let i = 0; i < map.concepts.length; i += 1) {
      const r = Math.hypot(layout.concepts[i * 2], layout.concepts[i * 2 + 1])
      expect(r).toBeGreaterThanOrEqual(CLOUD_IN - 12)
      expect(r).toBeLessThanOrEqual(CLOUD_OUT + 12)
    }
  })

  it("groups key concepts by facet: a facet's members are neighbours on the ring", () => {
    // Biology is [0, 3], Control [1, 2, 4]: going round, the two facets do not interleave.
    const order = [...layout.keyConcepts].sort(
      (a, b) => angleDelta(FOOT, a.angle) - angleDelta(FOOT, b.angle)
    )
    const facetOf = (index: number) => map.syllabus.key_concepts[index].facet
    const runs = order.map((place) => facetOf(place.index)).filter((f, i, all) => f !== all[i - 1])
    expect(runs).toHaveLength(2)
    expect(layout.facets.map((facet) => facet.name)).toEqual(['Biology', 'Control'])
  })

  it('reserves the foot for what belongs to no key concept', () => {
    // The fixture has an untagged source, two unassigned concepts and a gap named for nothing.
    expect(layout.foot).toBe(true)
    const untagged = map.sources.findIndex((source) => source.tags.length === 0)
    expect(Math.abs(angleDelta(layout.sources[untagged].angle, FOOT))).toBeLessThan(0.5)
    for (const place of layout.keyConcepts) {
      expect(Math.abs(angleDelta(place.angle, FOOT))).toBeGreaterThan(0.3)
    }
  })

  it("places a concept in its key concept's sector", () => {
    const drone = map.concepts.findIndex((c) => c.label === 'drone comb frames')
    const angle = Math.atan2(layout.concepts[drone * 2 + 1], layout.concepts[drone * 2])
    const target = layout.keyConcepts[2].angle
    const others = layout.keyConcepts.filter((k) => k.index !== 2)
    const nearest = Math.min(...others.map((k) => Math.abs(angleDelta(angle, k.angle))))
    expect(Math.abs(angleDelta(angle, target))).toBeLessThan(nearest)
  })

  it("places a missing named text at its key concept's angle", () => {
    const gap = map.syllabus.gaps.findIndex((g) => g.key_concept === 4)
    expect(Math.abs(angleDelta(layout.gaps[gap].angle, layout.keyConcepts[4].angle))).toBeLessThan(
      0.35
    )
  })

  it('lets nothing on the orbit overlap', () => {
    const items = [...layout.sources, ...layout.gaps].sort((a, b) => a.angle - b.angle)
    for (let i = 0; i < items.length; i += 1) {
      const a = items[i]
      const b = items[(i + 1) % items.length]
      const gap = Math.hypot(a.x - b.x, a.y - b.y)
      expect(gap).toBeGreaterThan((a.size + b.size) / 2 - 0.5)
    }
  })
})

describe('source angles', () => {
  it('is the weighted circular mean — 350° and 10° average to 0°, not 180°', () => {
    const angles = [(350 * Math.PI) / 180, (10 * Math.PI) / 180]
    const angle = sourceAngle(
      [
        { key_concept: 0, depth: 'treats' },
        { key_concept: 1, depth: 'treats' },
      ],
      angles
    )
    expect(Math.abs(angleDelta(angle, 0))).toBeLessThan(1e-9)
  })

  it('weights sets_out over treats over mentions', () => {
    const angles = [0, Math.PI / 2]
    const angle = sourceAngle(
      [
        { key_concept: 0, depth: 'sets_out' },
        { key_concept: 1, depth: 'mentions' },
      ],
      angles
    )
    expect(angle).toBeLessThan(Math.PI / 4)
  })

  it('sends an untagged source, or one whose tags cancel out, to the foot', () => {
    expect(sourceAngle([], [0])).toBe(FOOT)
    const opposite = sourceAngle(
      [
        { key_concept: 0, depth: 'treats' },
        { key_concept: 1, depth: 'treats' },
      ],
      [0, Math.PI]
    )
    expect(opposite).toBe(FOOT)
  })
})

describe('relaxing along the ring', () => {
  it('separates items that want the same angle, and keeps them near it', () => {
    const placed = relaxAlongRing([
      { desired: 1, halfWidth: 0.05, key: 1 },
      { desired: 1, halfWidth: 0.05, key: 2 },
      { desired: 1, halfWidth: 0.05, key: 3 },
    ])
    const sorted = [...placed].sort((a, b) => a - b)
    expect(sorted[1] - sorted[0]).toBeGreaterThanOrEqual(0.099)
    expect(sorted[2] - sorted[1]).toBeGreaterThanOrEqual(0.099)
    expect(Math.abs(sorted[1] - 1)).toBeLessThan(0.05)
  })
})

describe('an expert with no plan', () => {
  it('spaces key concepts evenly with no sectors and no facet labels', () => {
    const planless: MapResponse = {
      ...map,
      syllabus: { ...map.syllabus, facets: null, gaps: [] },
      sources: map.sources.filter((s) => s.tags.length > 0),
      concepts: map.concepts.filter((c) => c.key_concept !== null),
    }
    const layout = computeLayout(planless)
    expect(layout.facets).toEqual([])
    expect(layout.foot).toBe(false)
    const angles = layout.keyConcepts.map((k) => k.angle).sort((a, b) => a - b)
    const steps = angles.map((a, i) => angleDelta(a, angles[(i + 1) % angles.length]))
    for (const step of steps) expect(step).toBeCloseTo((Math.PI * 2) / angles.length)
  })

  it('still lays out a syllabus with nothing extracted yet', () => {
    const pending: MapResponse = { ...map, computed: false, concepts: [], links: [] }
    const layout = computeLayout(pending)
    expect(layout.concepts.length).toBe(0)
    expect(layout.keyConcepts).toHaveLength(map.syllabus.key_concepts.length)
  })
})
