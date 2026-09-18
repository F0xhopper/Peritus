import type { BuildEvent, ConceptDepth, MapResponse, MapSource } from '@/lib/api/types'

/**
 * The brain growing — a pure fold from the build's event log to a partial map
 * (docs/plans/expert-brain-interactive.md, G1).
 *
 * The build forms the brain in the order the map is layered: the plan is the
 * ring, kept sources are the orbit, extraction is the cloud. This fold draws
 * **only what the log says is true at that moment**:
 *
 * - `plan_ready` draws the ring, its facets, and every named text as a hollow
 *   square — the texts this build is looking for;
 * - `source_ingested` puts a source on the orbit (from G0 it carries its id, tier
 *   and graded tags, so it has an angle); a named text it matches fills in;
 * - `coverage_report` sizes the key-concept discs;
 * - the cloud stays empty: which concepts clear the two-source bar, and what
 *   merges into what, is not known until entity resolution has run. At
 *   `graph_ready` the page fetches the real `/map` instead.
 *
 * `retry` empties the orbit and keeps the ring: a retry from scratch wipes the
 * corpus. Failed and cancelled builds keep what they grew. The same prefix
 * always folds to the same state; what animates is the page's business.
 */

export interface GrowState {
  keyConcepts: string[]
  facets: { name: string; concepts: number[] }[] | null
  /** Per key concept: kept sources counting toward it, from the last coverage report. */
  coverage: Record<string, { sources: number; met: boolean }>
  /** What the plan named, by key concept index or `null` for a must-have work. */
  named: { key_concept: number | null; title: string; author: string | null; found: boolean }[]
  sources: MapSource[]
  /** Recent candidates as they were judged — at most six are ever drawn. */
  judged: { seq: number; title: string; passed: boolean }[]
  /** Sources the last graph batch read, for a pulse. */
  reading: { seq: number; sourceIds: number[] } | null
  conceptsFound: number
  chatReady: boolean
  graphReady: boolean
  /** Whether this log carries G0's fields at all, which is what replay needs. */
  placeable: boolean
  /** The events this fold read, in order — what a replay folds again (G4). */
  log: { seq: number; event: BuildEvent }[]
}

export function initialGrowState(): GrowState {
  return {
    keyConcepts: [],
    facets: null,
    coverage: {},
    named: [],
    sources: [],
    judged: [],
    reading: null,
    conceptsFound: 0,
    chatReady: false,
    graphReady: false,
    placeable: false,
    log: [],
  }
}

/** Event types the fold reads. Everything else returns the state unchanged. */
export const GROW_EVENTS = new Set([
  'plan_ready',
  'source_validated',
  'source_ingested',
  'coverage_report',
  'chat_ready',
  'graph_batch_done',
  'graph_ready',
  'retry',
  'build_started',
])

const MAX_JUDGED = 6
const DEPTHS = new Set<ConceptDepth>(['sets_out', 'treats', 'mentions'])

export function reduceGrow(state: GrowState, seq: number, event: BuildEvent): GrowState {
  if (!GROW_EVENTS.has(event.type)) return state
  const next = foldGrow(state, seq, event)
  return { ...next, log: [...state.log, { seq, event }] }
}

/** Fold a whole log from nothing — the picture at the end of a replay. */
export function foldGrow(events: { seq: number; event: BuildEvent }[]): GrowState
export function foldGrow(state: GrowState, seq: number, event: BuildEvent): GrowState
export function foldGrow(
  first: GrowState | { seq: number; event: BuildEvent }[],
  seq?: number,
  event?: BuildEvent
): GrowState {
  if (Array.isArray(first)) {
    return first.reduce(
      (state, item) => reduceGrow(state, item.seq, item.event),
      initialGrowState()
    )
  }
  return step(first, seq!, event!)
}

function step(state: GrowState, seq: number, event: BuildEvent): GrowState {
  const raw = event as Record<string, unknown>

  switch (event.type) {
    case 'plan_ready': {
      const keyConcepts = strings(raw.key_concepts)
      const index = new Map(keyConcepts.map((c, i) => [c, i]))
      const facets = records(raw.facets)
        .map((facet) => ({
          name: String(facet.name ?? ''),
          concepts: strings(facet.concepts)
            .map((c) => index.get(c))
            .filter((i): i is number => i !== undefined),
        }))
        .filter((facet) => facet.concepts.length > 0)
      const named: GrowState['named'] = []
      const seen = new Set<string>()
      for (const work of records(raw.concept_primary_texts)) {
        const title = String(work.title ?? '')
        const at = index.get(String(work.concept ?? ''))
        if (!title || at === undefined || seen.has(title.toLowerCase())) continue
        seen.add(title.toLowerCase())
        named.push({ key_concept: at, title, author: str(work.author), found: false })
      }
      for (const work of records(raw.must_have_works)) {
        const title = String(work.title ?? '')
        if (!title || seen.has(title.toLowerCase())) continue
        seen.add(title.toLowerCase())
        named.push({ key_concept: null, title, author: str(work.author), found: false })
      }
      return {
        ...state,
        keyConcepts,
        facets: facets.length > 1 ? facets : null,
        named,
        coverage: {},
      }
    }

    case 'source_validated': {
      const judged = [
        ...state.judged,
        { seq, title: String(raw.title ?? ''), passed: Boolean(raw.passed) },
      ]
      return { ...state, judged: judged.slice(-MAX_JUDGED) }
    }

    case 'source_ingested': {
      const id = typeof raw.source_id === 'number' ? raw.source_id : null
      // A log from before G0 has no id and no tags: nothing to place.
      if (id === null || state.sources.some((s) => s.id === id)) return state
      const tags = records(raw.tags)
        .map((tag) => ({ key_concept: Number(tag.key_concept), depth: tag.depth as ConceptDepth }))
        .filter((tag) => Number.isInteger(tag.key_concept) && DEPTHS.has(tag.depth))
      const title = String(raw.title ?? '')
      const source: MapSource = {
        id,
        title,
        author: null,
        kind: String(raw.kind ?? 'web'),
        tier: str(raw.tier),
        passage_count: Number(raw.chunks) || 0,
        tags,
      }
      const key = title.toLowerCase()
      const named = state.named.map((work) =>
        !work.found && key.includes(work.title.toLowerCase()) ? { ...work, found: true } : work
      )
      return { ...state, sources: [...state.sources, source], named, placeable: true }
    }

    case 'coverage_report': {
      const coverage: GrowState['coverage'] = {}
      for (const concept of records(raw.concepts)) {
        coverage[String(concept.concept ?? '')] = {
          sources: Number(concept.sources) || 0,
          met: Boolean(concept.met),
        }
      }
      return { ...state, coverage }
    }

    case 'chat_ready':
      return { ...state, chatReady: true }

    case 'graph_batch_done': {
      const labels = Array.isArray(raw.labels) ? raw.labels.length : 0
      const ids = Array.isArray(raw.source_ids)
        ? raw.source_ids.filter((x): x is number => typeof x === 'number')
        : []
      return {
        ...state,
        conceptsFound: state.conceptsFound + labels,
        reading: ids.length ? { seq, sourceIds: ids } : state.reading,
      }
    }

    case 'graph_ready':
      return { ...state, graphReady: true }

    case 'retry':
      // A retry from scratch wipes the corpus; the plan stands.
      return {
        ...state,
        sources: [],
        coverage: {},
        judged: [],
        reading: null,
        conceptsFound: 0,
        chatReady: false,
        graphReady: false,
        named: state.named.map((work) => ({ ...work, found: false })),
      }

    case 'build_started':
      // A resumed attempt keeps what it had; a fresh one starts over, which
      // `retry` has already done.
      return state
  }
  return state
}

/**
 * The grown state as a map payload the canvas can draw. Missing texts are the
 * named ones not yet found; the cloud is empty and `computed` false.
 */
export function grownMap(state: GrowState, slug: string, topic: string): MapResponse {
  const facetOf = new Map<number, string>()
  for (const facet of state.facets ?? []) for (const i of facet.concepts) facetOf.set(i, facet.name)
  return {
    expert: { slug, topic },
    computed: false,
    syllabus: {
      facets: state.facets,
      key_concepts: state.keyConcepts.map((label, index) => ({
        index,
        label,
        facet: facetOf.get(index) ?? null,
        sources: state.coverage[label]?.sources ?? countTagged(state.sources, index),
        depth_counts: {},
        met: state.coverage[label]?.met ?? false,
        named_text: null,
      })),
      gaps: state.named
        .filter((work) => !work.found)
        .map((work) => ({
          key_concept: work.key_concept,
          title: work.title,
          author: work.author,
          kind: work.key_concept === null ? ('must_have' as const) : ('named_text' as const),
        })),
    },
    sources: state.sources,
    concepts: [],
    links: [],
    totals: { concepts: null, concepts_shown: 0, claims: null, sources: state.sources.length },
    expanded: null,
  }
}

function countTagged(sources: MapSource[], index: number): number {
  return sources.filter((s) =>
    s.tags.some((t) => t.key_concept === index && t.depth !== 'mentions')
  ).length
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((x): x is string => typeof x === 'string') : []
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((x): x is Record<string, unknown> => typeof x === 'object' && x !== null)
    : []
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null
}

// ── adding and removing, on the map (G2) ────────────────────────────────────

/**
 * What removing a source costs, in sentences, from the map already in hand:
 * its passages, the concepts that drop to one source (or none) and leave the
 * map, and a named text that would be missing again.
 */
export function removalCost(map: MapResponse, sourceId: number): string[] {
  const source = map.sources.find((s) => s.id === sourceId)
  if (!source) return []
  const lines = [`${source.passage_count} ${source.passage_count === 1 ? 'passage' : 'passages'}.`]
  if (map.computed) {
    const leaving = map.concepts.filter(
      (concept) =>
        concept.source_ids.includes(sourceId) &&
        !concept.topped_up &&
        concept.source_ids.length <= 2
    ).length
    if (leaving > 0) {
      lines.push(
        `${leaving} ${leaving === 1 ? 'concept drops' : 'concepts drop'} to a single source and ${leaving === 1 ? 'leaves' : 'leave'} the map.`
      )
    }
  }
  const title = source.title.toLowerCase()
  for (const concept of map.syllabus.key_concepts) {
    const named = concept.named_text
    if (named?.title && named.status !== 'missing' && title.includes(named.title.toLowerCase())) {
      lines.push(`${named.title} will be missing again.`)
    }
  }
  return lines
}

/**
 * What an added source changed, for the toast after it lands: the key concepts
 * it covers, its passages, and any named text it filled.
 */
export function additionSummary(before: MapResponse, after: MapResponse): string | null {
  const known = new Set(before.sources.map((s) => s.id))
  const added = after.sources.filter((s) => !known.has(s.id))
  if (added.length === 0) return null
  const covers = new Set<number>()
  let passages = 0
  for (const source of added) {
    passages += source.passage_count
    for (const tag of source.tags) if (tag.depth !== 'mentions') covers.add(tag.key_concept)
  }
  const stillMissing = new Set(after.syllabus.gaps.map((gap) => gap.title))
  const filled = before.syllabus.gaps.filter((gap) => !stillMissing.has(gap.title))
  const parts = [
    `Covers ${covers.size} key ${covers.size === 1 ? 'concept' : 'concepts'}`,
    `${passages} ${passages === 1 ? 'passage' : 'passages'}`,
  ]
  const head = `Added. ${parts.join(', ')}.`
  return filled.length ? `${head} Fills ${filled.map((gap) => gap.title).join(', ')}.` : head
}
