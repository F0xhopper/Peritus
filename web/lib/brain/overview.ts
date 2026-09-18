import type { MapResponse, MapSource } from '@/lib/api/types'
import { litByCitations, type Lit } from '@/lib/brain/selection'
import {
  parseSourceKindId,
  sourceKindId,
  sourceKindLabel,
  type SourceKindId,
} from '@/lib/source-kind'

/**
 * What the Knowledge page says about an expert before anything is selected:
 * how much it has read, what that is made of, and how well that covers the
 * syllabus. All of it is folded from the map payload the page already holds —
 * the Overview costs no request.
 *
 * `null` stays null (web/AGENTS.md, rule 2): the API does not always record a
 * concept or claim count, and a fabricated zero beside real numbers is worse
 * than a dash.
 */
export interface KnowledgeStats {
  sources: number
  passages: number
  concepts: number | null
  claims: number | null
  keyConcepts: number
  facets: number
  /** Key concepts whose coverage meets this expert's target. */
  met: number
  gaps: number
}

export function knowledgeStats(map: MapResponse): KnowledgeStats {
  const sources = map.sources.filter((source) => !source.pending)
  return {
    sources: sources.length,
    passages: sources.reduce((sum, source) => sum + source.passage_count, 0),
    concepts: map.totals.concepts,
    claims: map.totals.claims,
    keyConcepts: map.syllabus.key_concepts.length,
    facets: map.syllabus.facets?.length ?? 0,
    met: map.syllabus.key_concepts.filter((concept) => concept.met).length,
    gaps: map.syllabus.gaps.length,
  }
}

export interface KindCount {
  id: SourceKindId
  label: string
  count: number
}

/** Sources by kind, commonest first; ties by label so the order never flickers. */
export function kindCounts(map: MapResponse): KindCount[] {
  const counts = new Map<SourceKindId, number>()
  for (const source of map.sources) {
    if (source.pending) continue
    const id = sourceKindId(source.kind)
    counts.set(id, (counts.get(id) ?? 0) + 1)
  }
  return [...counts]
    .map(([id, count]) => ({ id, label: sourceKindLabel(id), count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
}

export type SourceTier = 'primary' | 'secondary' | 'tertiary'

export const TIERS: { id: SourceTier; label: string; hint: string }[] = [
  { id: 'primary', label: 'Primary', hint: 'The works themselves' },
  { id: 'secondary', label: 'Secondary', hint: 'Scholarship about them' },
  { id: 'tertiary', label: 'Tertiary', hint: 'Summaries and reference' },
]

export function parseTier(raw: string | null | undefined): SourceTier | null {
  return TIERS.find((tier) => tier.id === raw)?.id ?? null
}

/** Sources by tier, in the fixed order above. Unclassified sources are left out. */
export function tierCounts(map: MapResponse): Record<SourceTier, number> {
  const counts: Record<SourceTier, number> = { primary: 0, secondary: 0, tertiary: 0 }
  for (const source of map.sources) {
    const tier = parseTier(source.tier)
    if (tier && !source.pending) counts[tier]++
  }
  return counts
}

// ── the filter ──────────────────────────────────────────────────────────────

/**
 * Kind and tier, narrowing the List and lighting the Map and the Flow. URL
 * state (`?kind=`, `?tier=`) like the selection, so a filtered page is a link.
 */
export interface SourceFilter {
  kind: SourceKindId | null
  tier: SourceTier | null
}

export function filterFromParams(params: { get(name: string): string | null }): SourceFilter {
  return { kind: parseSourceKindId(params.get('kind')), tier: parseTier(params.get('tier')) }
}

export function isFiltering(filter: SourceFilter): boolean {
  return filter.kind !== null || filter.tier !== null
}

/** Whether a source passes — by its fetcher key and tier, whatever row it is. */
export function passesFilter(
  source: { type: string | null | undefined; tier: string | null | undefined },
  filter: SourceFilter
): boolean {
  if (filter.kind !== null && sourceKindId(source.type) !== filter.kind) return false
  if (filter.tier !== null && source.tier !== filter.tier) return false
  return true
}

export function filteredSources(map: MapResponse, filter: SourceFilter): MapSource[] {
  return map.sources.filter(
    (source) => !source.pending && passesFilter({ type: source.kind, tier: source.tier }, filter)
  )
}

/**
 * What a filter lights: the sources that pass, and everything they feed — the
 * same reading as an answer's citations, which is the other "these sources"
 * question the map answers.
 */
export function litByFilter(map: MapResponse, filter: SourceFilter): Lit | null {
  if (!isFiltering(filter)) return null
  const lit = litByCitations(
    map,
    filteredSources(map, filter).map((source) => source.id)
  )
  // A kind and a tier that no source has together: nothing is lit, which is
  // the true answer. Null would mean "no filter" and light everything.
  return lit ?? { sources: new Set(), concepts: new Set(), keyConcepts: new Set(), gaps: new Set() }
}

/** "Papers", "Primary sources", "Primary papers" — the filter, as the chip says it. */
export function describeFilter(filter: SourceFilter): string | null {
  if (!isFiltering(filter)) return null
  const tier = TIERS.find((t) => t.id === filter.tier)?.label ?? null
  if (filter.kind === null) return `${tier} sources`
  const kind = sourceKindLabel(filter.kind)
  return tier ? `${tier} · ${kind}` : kind
}
