import { describe, expect, it } from 'vitest'

import expertMap from './fixtures/map.json' with { type: 'json' }
import notComputed from './fixtures/map-not-computed.json' with { type: 'json' }
import type { MapResponse } from '@/lib/api/types'
import { cn } from '@/lib/cn'
import {
  describeFilter,
  filterFromParams,
  filteredSources,
  isFiltering,
  kindCounts,
  knowledgeStats,
  litByFilter,
  passesFilter,
  tierCounts,
} from '@/lib/brain/overview'
import { parseSourceKindId, sourceKind, sourceKindId, sourceKindLabel } from '@/lib/source-kind'

const map = expertMap as MapResponse
const params = (query: string) => new URLSearchParams(query)

describe('what the Overview counts', () => {
  it('is folded from the map the page already holds', () => {
    expect(knowledgeStats(map)).toEqual({
      sources: 10,
      passages: map.sources.reduce((sum, source) => sum + source.passage_count, 0),
      concepts: map.totals.concepts,
      claims: map.totals.claims,
      keyConcepts: 5,
      facets: 2,
      met: 3,
      gaps: 2,
    })
  })

  it('keeps "not recorded" as null rather than inventing a zero', () => {
    const stats = knowledgeStats(notComputed as MapResponse)
    expect(stats.concepts).toBe((notComputed as MapResponse).totals.concepts)
    expect(stats.concepts).toBeNull()
  })

  it('does not count a source that is still being read in', () => {
    const reading: MapResponse = {
      ...map,
      sources: [...map.sources, { ...map.sources[0], id: -3, pending: true }],
    }
    expect(knowledgeStats(reading).sources).toBe(10)
    expect(kindCounts(reading)).toEqual(kindCounts(map))
    expect(tierCounts(reading)).toEqual(tierCounts(map))
  })
})

describe('a kind is what a reader would call it, not the fetcher that found it', () => {
  it('folds fetchers into kinds', () => {
    // OpenAlex and PubMed both find papers; Exa and the web search, web pages.
    expect(sourceKindId('openalex')).toBe('paper')
    expect(sourceKindId('pubmed')).toBe('paper')
    expect(sourceKindId('exa')).toBe(sourceKindId('web'))
    expect(sourceKindId('a_fetcher_added_later')).toBe('other')
    expect(sourceKindId(null)).toBe('other')
  })

  it('names a kind exactly as the table and the panels already do', () => {
    for (const type of ['openalex', 'arxiv', 'wikipedia', 'exa', 'reddit', 'gutenberg']) {
      expect(sourceKindLabel(sourceKindId(type))).toBe(sourceKind(type))
    }
  })

  it('counts them commonest first, and breaks a tie by name', () => {
    const counts = kindCounts(map)
    expect(counts[0]).toEqual({ id: 'paper', label: 'Paper', count: 4 })
    expect(counts[1]).toEqual({ id: 'web', label: 'Web page', count: 2 })
    expect(counts.slice(2).map((kind) => kind.label)).toEqual([
      'Book',
      'Discussion',
      'Encyclopedia',
      'Preprint',
    ])
    expect(counts.reduce((sum, kind) => sum + kind.count, 0)).toBe(map.sources.length)
  })

  it('counts tiers', () => {
    expect(tierCounts(map)).toEqual({ primary: 5, secondary: 3, tertiary: 2 })
  })
})

describe('the kind and tier filter', () => {
  it('is read from the URL, and an edited URL falls back to no filter', () => {
    expect(filterFromParams(params('kind=paper&tier=primary'))).toEqual({
      kind: 'paper',
      tier: 'primary',
    })
    expect(filterFromParams(params('kind=openalex&tier=best'))).toEqual({ kind: null, tier: null })
    expect(parseSourceKindId('toString')).toBeNull()
    expect(isFiltering(filterFromParams(params('')))).toBe(false)
  })

  it('passes a source by its fetcher key and tier, whichever row it is', () => {
    expect(passesFilter({ type: 'pubmed', tier: 'primary' }, { kind: 'paper', tier: null })).toBe(
      true
    )
    expect(passesFilter({ type: 'exa', tier: 'primary' }, { kind: 'paper', tier: null })).toBe(
      false
    )
    expect(
      passesFilter({ type: 'pubmed', tier: 'secondary' }, { kind: 'paper', tier: 'primary' })
    ).toBe(false)
    expect(passesFilter({ type: 'pubmed', tier: null }, { kind: null, tier: null })).toBe(true)
  })

  it('lights the sources that pass and everything they feed', () => {
    const lit = litByFilter(map, { kind: 'paper', tier: null })!
    expect([...lit.sources].sort()).toEqual([804, 812, 815, 816])
    // 804 sets out varroa biology and treats viral co-infection; and so on.
    expect([...lit.keyConcepts].sort()).toEqual([0, 1, 2, 3, 4])
    for (const concept of map.concepts) {
      expect(lit.concepts.has(concept.id)).toBe(
        concept.source_ids.some((id) => lit.sources.has(id))
      )
    }
  })

  it('lights nothing — not everything — when no source is both', () => {
    const filter = { kind: 'discussion', tier: 'primary' } as const
    expect(filteredSources(map, filter)).toEqual([])
    const lit = litByFilter(map, filter)
    expect(lit).not.toBeNull()
    expect(lit!.sources.size + lit!.concepts.size + lit!.keyConcepts.size).toBe(0)
    expect(litByFilter(map, { kind: null, tier: null })).toBeNull()
  })

  it('says itself in the words the chip shows', () => {
    expect(describeFilter({ kind: 'paper', tier: null })).toBe('Paper')
    expect(describeFilter({ kind: null, tier: 'primary' })).toBe('Primary sources')
    expect(describeFilter({ kind: 'book', tier: 'primary' })).toBe('Primary · Book')
    expect(describeFilter({ kind: null, tier: null })).toBeNull()
  })
})

describe('cn', () => {
  it("keeps this project's font sizes when a colour follows", () => {
    // tailwind-merge took `text-label` for a colour and dropped it, so every
    // label styled through `cn` rendered at the size it inherited.
    expect(cn('text-label uppercase', 'text-fg-3')).toBe('text-label uppercase text-fg-3')
    expect(cn('text-stat font-medium', 'text-warn')).toBe('text-stat font-medium text-warn')
    expect(cn('text-md', 'text-fg')).toBe('text-md text-fg')
  })

  it('still lets a later size, or a later colour, win', () => {
    expect(cn('text-label', 'text-xs')).toBe('text-xs')
    expect(cn('text-stat', 'text-title')).toBe('text-title')
    expect(cn('text-fg-3', 'text-warn')).toBe('text-warn')
  })
})
