import { describe, expect, it } from 'vitest'

import expertMap from './fixtures/map.json' with { type: 'json' }
import type { MapResponse } from '@/lib/api/types'
import {
  FLOW,
  flowColumns,
  flowLayout,
  flowPath,
  homeKeyConcept,
  type FlowItem,
  type FlowLayout,
} from '@/lib/brain/flow'

const map = expertMap as MapResponse
const layout = flowLayout(map, { rowH: 26 })

const of = <K extends FlowItem['kind']>(from: FlowLayout, kind: K) =>
  from.items.filter((item): item is Extract<FlowItem, { kind: K }> => item.kind === kind)

/** Maps do not survive `JSON.stringify`; the rest of the layout does. */
const serialise = (value: FlowLayout) =>
  JSON.stringify({
    ...value,
    sourceY: [...value.sourceY],
    conceptY: [...value.conceptY],
    gapY: [...value.gapY],
  })

describe('where a source stands', () => {
  it('is beside the key concept it covers most deeply', () => {
    expect(
      homeKeyConcept([
        { key_concept: 4, depth: 'mentions' },
        { key_concept: 2, depth: 'sets_out' },
        { key_concept: 0, depth: 'treats' },
      ])
    ).toEqual({ key: 2, depth: 'sets_out' })
  })

  it('breaks a tie toward the lower index, so the layout cannot flicker', () => {
    const tags = [
      { key_concept: 4, depth: 'treats' as const },
      { key_concept: 1, depth: 'treats' as const },
    ]
    expect(homeKeyConcept(tags)?.key).toBe(1)
    expect(homeKeyConcept([...tags].reverse())?.key).toBe(1)
  })

  it('is nowhere in the syllabus when nothing tagged it', () => {
    expect(homeKeyConcept([])).toBeNull()
  })
})

describe('the bands', () => {
  it('follow the facets, then what is outside the syllabus', () => {
    // Biology is key concepts 0 and 3, Control is 1, 2 and 4.
    expect(layout.bands.map((band) => band.key)).toEqual([0, 3, 1, 2, 4, null])
    expect(layout.facets.map((facet) => facet.name)).toEqual([
      'Biology',
      'Control',
      'Outside the syllabus',
    ])
  })

  it('never overlap, and a facet heading has its own room above its first band', () => {
    layout.bands.forEach((band, i) => {
      const next = layout.bands[i + 1]
      if (next) expect(next.top).toBeGreaterThanOrEqual(band.top + band.height + FLOW.bandGap)
    })
    for (const facet of layout.facets) {
      const first = layout.bands.find((band) => band.top >= facet.y)
      expect(first?.top).toBe(facet.y + FLOW.facetH)
    }
    const last = layout.bands.at(-1)!
    expect(layout.height).toBe(last.top + last.height)
  })

  it('put each source in one band: deepest tag, then tier, then title', () => {
    const inBand = (key: number | null) => {
      const index = layout.bands.findIndex((band) => band.key === key)
      return of(layout, 'source')
        .filter((item) => item.band === index)
        .map((item) => item.id)
    }
    // 804 sets varroa biology out; 820 (secondary) and 818 (tertiary) treat it.
    expect(inBand(0)).toEqual([804, 820, 818])
    // 819 treats both 1 and 4 — the tie goes to 1.
    expect(inBand(1)).toEqual([812, 819])
    expect(inBand(4)).toEqual([817])
    // 822 has no tags.
    expect(inBand(null)).toEqual([822])
    expect(of(layout, 'source')).toHaveLength(map.sources.length)
  })

  it('put a missing text where it would have stood', () => {
    const band = (index: number) => layout.bands[of(layout, 'gap')[index].band].key
    const gaps = of(layout, 'gap')
    expect(gaps.map((gap) => gap.index).sort()).toEqual([0, 1])
    expect(band(gaps.findIndex((gap) => gap.index === 0))).toBe(4)
    expect(band(gaps.findIndex((gap) => gap.index === 1))).toBeNull()
  })

  it('keep every row of a column clear of the next, at either row height', () => {
    for (const rowH of [26, 44]) {
      const sized = flowLayout(map, { rowH })
      const left = sized.items
        .filter((item) => item.kind === 'source' || item.kind === 'gap')
        .map((item) => item.y)
        .sort((a, b) => a - b)
      const right = sized.items
        .filter((item) => item.kind === 'concept' || item.kind === 'more')
        .map((item) => item.y)
        .sort((a, b) => a - b)
      for (const column of [left, right]) {
        column.forEach((y, i) => {
          if (i > 0) expect(y - column[i - 1]).toBeGreaterThanOrEqual(rowH)
        })
      }
      // And every row is inside its own band.
      for (const item of sized.items) {
        const band = sized.bands[item.band]
        expect(item.y - rowH / 2).toBeGreaterThanOrEqual(band.top)
        expect(item.y + rowH / 2).toBeLessThanOrEqual(band.top + band.height)
      }
    }
  })
})

describe('the concepts shown', () => {
  const bandOf = (from: FlowLayout, key: number) => from.bands.findIndex((band) => band.key === key)

  it('are the best-attested of each sector, with the rest behind "+n more"', () => {
    // Acaricide resistance has five concepts on the map and two sources.
    const index = bandOf(layout, 1)
    const shown = of(layout, 'concept').filter((item) => item.band === index)
    expect(shown).toHaveLength(FLOW.conceptsPerBand)
    const counts = shown.map(
      (item) => map.concepts.find((concept) => concept.id === item.id)!.source_ids.length
    )
    expect(counts).toEqual([...counts].sort((a, b) => b - a))
    expect(of(layout, 'more').find((item) => item.band === index)).toMatchObject({
      hidden: 1,
      expanded: false,
    })
  })

  it('are all of them once the band is expanded', () => {
    const open = flowLayout(map, { rowH: 26, expanded: new Set([1]) })
    const index = bandOf(open, 1)
    expect(of(open, 'concept').filter((item) => item.band === index)).toHaveLength(5)
    expect(of(open, 'more').find((item) => item.band === index)).toMatchObject({
      hidden: 0,
      expanded: true,
    })
  })

  it('include a selected concept its band had folded away', () => {
    const index = bandOf(layout, 1)
    const shown = new Set(of(layout, 'concept').map((item) => item.id))
    const folded = map.concepts.find((c) => c.key_concept === 1 && !shown.has(c.id))!
    const pinned = flowLayout(map, { rowH: 26, pinnedConcept: folded.id })
    expect(pinned.conceptY.has(folded.id)).toBe(true)
    expect(of(pinned, 'more').find((item) => item.band === index)).toBeUndefined()
  })

  it('fill a band its sources have already made tall', () => {
    const many: MapResponse = {
      ...map,
      sources: Array.from({ length: 9 }, (_unused, i) => ({
        ...map.sources[1],
        id: 9000 + i,
        tags: [{ key_concept: 1, depth: 'treats' as const }],
      })),
    }
    const tall = flowLayout(many, { rowH: 26 })
    const index = bandOf(tall, 1)
    // Nine sources leave room for all five concepts and no "+n more".
    expect(of(tall, 'concept').filter((item) => item.band === index)).toHaveLength(5)
    expect(of(tall, 'more').find((item) => item.band === index)).toBeUndefined()
  })
})

describe('the links', () => {
  it('are one per tag and one per concept shown in its own sector', () => {
    const tags = map.sources.reduce((sum, source) => sum + source.tags.length, 0)
    expect(layout.links.filter((link) => link.kind === 'tag')).toHaveLength(tags)

    const members = layout.links.filter((link) => link.kind === 'member')
    const inSyllabus = of(layout, 'concept').filter((item) => layout.bands[item.band].key !== null)
    expect(members).toHaveLength(inSyllabus.length)
    // What is outside the syllabus is drawn, and linked to nothing.
    const foot = layout.bands.findIndex((band) => band.key === null)
    expect(of(layout, 'concept').some((item) => item.band === foot)).toBe(true)
  })

  it('start and end on the rows and the card they join', () => {
    for (const link of layout.links) {
      const band = layout.bands.find((candidate) => candidate.key === link.keyConcept)!
      const [row, port] =
        link.kind === 'tag'
          ? [layout.sourceY.get(link.sourceId!), link.y2]
          : [layout.conceptY.get(link.conceptId!), link.y1]
      expect(link.kind === 'tag' ? link.y1 : link.y2).toBe(row)
      expect(Math.abs(port - band.nodeY)).toBeLessThanOrEqual(FLOW.nodeH / 2)
    }
  })

  it("mark a source's own band, so the tags that cross bands can be drawn as a trace", () => {
    const tags = layout.links.filter((link) => link.kind === 'tag')
    for (const source of map.sources) {
      const mine = tags.filter((link) => link.sourceId === source.id)
      const item = of(layout, 'source').find((candidate) => candidate.id === source.id)!
      const home = layout.bands[item.band].key
      // Exactly one home link for a tagged source, and it is the level one.
      expect(mine.filter((link) => link.home)).toHaveLength(source.tags.length ? 1 : 0)
      for (const link of mine) expect(link.home).toBe(link.keyConcept === home)
    }
    // 804 sets varroa biology out (home) and only treats viral co-infection.
    expect(tags.find((link) => link.sourceId === 804 && link.keyConcept === 0)?.home).toBe(true)
    expect(tags.find((link) => link.sourceId === 804 && link.keyConcept === 3)?.home).toBe(false)
  })

  it('reach a card in the order of what they join, so none cross on the way in', () => {
    for (const band of layout.bands) {
      if (band.key === null) continue
      for (const kind of ['tag', 'member'] as const) {
        const into = layout.links
          .filter((link) => link.kind === kind && link.keyConcept === band.key)
          .map((link) => (kind === 'tag' ? [link.y1, link.y2] : [link.y2, link.y1]))
          .sort((a, b) => a[0] - b[0])
        into.forEach(([, port], i) => {
          if (i > 0) expect(port).toBeGreaterThan(into[i - 1][1])
        })
      }
    }
  })
})

describe('the layout as a whole', () => {
  it('is deterministic', () => {
    expect(serialise(flowLayout(map, { rowH: 26 }))).toBe(serialise(layout))
    const shuffled: MapResponse = {
      ...map,
      sources: [...map.sources].reverse(),
      concepts: [...map.concepts].reverse(),
    }
    // The payload's order is not the layout's: only what the rows *are* is.
    expect(serialise(flowLayout(shuffled, { rowH: 26 }))).toBe(serialise(layout))
  })

  it('draws an expert with no syllabus as one band of what it has', () => {
    const bare: MapResponse = {
      ...map,
      syllabus: { facets: null, key_concepts: [], gaps: [] },
      sources: map.sources.map((source) => ({ ...source, tags: [] })),
      concepts: map.concepts.map((concept) => ({ ...concept, key_concept: null })),
    }
    const flat = flowLayout(bare, { rowH: 26 })
    expect(flat.bands.map((band) => band.key)).toEqual([null])
    expect(flat.links).toEqual([])
    expect(of(flat, 'source')).toHaveLength(map.sources.length)
  })

  it('leaves a source still being read in off the diagram', () => {
    const reading: MapResponse = {
      ...map,
      sources: [...map.sources, { ...map.sources[0], id: -7, pending: true }],
    }
    expect(flowLayout(reading, { rowH: 26 }).sourceY.has(-7)).toBe(false)
  })
})

describe('the columns', () => {
  it('fit the width, in order, with a channel between each', () => {
    for (const width of [640, 764, 1128, 1600]) {
      const columns = flowColumns(width)
      expect(columns.width).toBe(width)
      expect(columns.source.x).toBeGreaterThan(0)
      expect(columns.node.x).toBeGreaterThan(columns.source.x + columns.source.w + 40)
      expect(columns.concept.x).toBeGreaterThan(columns.node.x + columns.node.w + 40)
      expect(columns.concept.x + columns.concept.w).toBeLessThan(width)
      expect(columns.source.w).toBeGreaterThan(120)
      expect(columns.concept.w).toBeGreaterThan(100)
    }
  })

  it('never go below the width the diagram needs: it scrolls in its own box instead', () => {
    expect(flowColumns(360).width).toBe(FLOW.minWidth)
    expect(flowColumns(0).width).toBe(FLOW.minWidth)
  })

  it('join with a level S-curve', () => {
    expect(flowPath(100, 20, 200, 60)).toBe('M100,20C150,20 150,60 200,60')
  })
})
