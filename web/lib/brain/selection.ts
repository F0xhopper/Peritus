import type { MapResponse } from '@/lib/api/types'

/**
 * What is selected on the Knowledge page, and what that lights on the map.
 *
 * One selection for both views (docs/plans/expert-brain.md, "The page"), held
 * in the URL: `?source=`, `?concept=` (a key concept, by its label — the
 * Overview's links already use it), `?node=` (a concept in the cloud) and
 * `?gap=`. Only one is ever read; see {@link selectionFromParams} for the order.
 */
export type BrainSelection =
  | { kind: 'source'; id: number }
  | { kind: 'concept'; id: number }
  | { kind: 'keyConcept'; index: number }
  | { kind: 'gap'; index: number }

/** Everything a selection lights. The rest of the map drops to 15%. */
export interface Lit {
  sources: Set<number>
  concepts: Set<number>
  keyConcepts: Set<number>
  gaps: Set<number>
}

export function selectionFromParams(
  params: { get(name: string): string | null },
  map: MapResponse | null
): BrainSelection | null {
  const source = Number(params.get('source'))
  if (Number.isInteger(source) && source > 0) return { kind: 'source', id: source }
  const node = Number(params.get('node'))
  if (Number.isInteger(node) && node > 0) return { kind: 'concept', id: node }
  const concept = params.get('concept')
  if (concept && map) {
    const needle = concept.toLowerCase()
    const index = map.syllabus.key_concepts.findIndex((k) => k.label.toLowerCase() === needle)
    if (index >= 0) return { kind: 'keyConcept', index }
  }
  const gap = params.get('gap')
  if (gap !== null && gap !== '' && map) {
    const index = Number(gap)
    if (Number.isInteger(index) && index >= 0 && index < map.syllabus.gaps.length) {
      return { kind: 'gap', index }
    }
  }
  return null
}

/** The query-string changes that select `selection`, clearing the other kinds. */
export function selectionParams(
  selection: BrainSelection | null,
  map: MapResponse | null
): Record<'source' | 'node' | 'concept' | 'gap', string | null> {
  const cleared = { source: null, node: null, concept: null, gap: null }
  if (!selection) return cleared
  switch (selection.kind) {
    case 'source':
      return { ...cleared, source: String(selection.id) }
    case 'concept':
      return { ...cleared, node: String(selection.id) }
    case 'keyConcept':
      return { ...cleared, concept: map?.syllabus.key_concepts[selection.index]?.label ?? null }
    case 'gap':
      return { ...cleared, gap: String(selection.index) }
  }
}

export function selectionKey(selection: BrainSelection | null): string | null {
  if (!selection) return null
  return `${selection.kind}:${'id' in selection ? selection.id : selection.index}`
}

/**
 * What a selection lights.
 *
 * - A **source**: the concepts extracted from its passages and the key concepts
 *   it was tagged with.
 * - A **concept**: the sources it was extracted from, its key concept, and the
 *   concepts it is `part_of` or that are part of it.
 * - A **key concept**: its sector's concepts, the sources tagged with it, and
 *   the texts named for it that are missing.
 * - A **gap**: itself and its key concept.
 */
export function litBy(map: MapResponse, selection: BrainSelection | null): Lit | null {
  if (!selection) return null
  const lit: Lit = {
    sources: new Set(),
    concepts: new Set(),
    keyConcepts: new Set(),
    gaps: new Set(),
  }
  switch (selection.kind) {
    case 'source': {
      const source = map.sources.find((s) => s.id === selection.id)
      if (!source) return null
      lit.sources.add(source.id)
      for (const tag of source.tags) lit.keyConcepts.add(tag.key_concept)
      for (const concept of map.concepts) {
        if (concept.source_ids.includes(source.id)) lit.concepts.add(concept.id)
      }
      return lit
    }
    case 'concept': {
      const concept = map.concepts.find((c) => c.id === selection.id)
      if (!concept) return null
      lit.concepts.add(concept.id)
      for (const id of concept.source_ids) lit.sources.add(id)
      if (concept.key_concept !== null) lit.keyConcepts.add(concept.key_concept)
      for (const link of map.links) {
        if (link.from === concept.id) lit.concepts.add(link.to)
        if (link.to === concept.id) lit.concepts.add(link.from)
      }
      return lit
    }
    case 'keyConcept': {
      lit.keyConcepts.add(selection.index)
      for (const source of map.sources) {
        if (source.tags.some((tag) => tag.key_concept === selection.index))
          lit.sources.add(source.id)
      }
      for (const concept of map.concepts) {
        if (concept.key_concept === selection.index) lit.concepts.add(concept.id)
      }
      map.syllabus.gaps.forEach((gap, i) => {
        if (gap.key_concept === selection.index) lit.gaps.add(i)
      })
      return lit
    }
    case 'gap': {
      const gap = map.syllabus.gaps[selection.index]
      if (!gap) return null
      lit.gaps.add(selection.index)
      if (gap.key_concept !== null) lit.keyConcepts.add(gap.key_concept)
      return lit
    }
  }
}

/**
 * The sources an answer cited, lit with everything they feed (phase 7).
 *
 * `?cited=804,812` on the Knowledge page. The cited sources light, the concepts
 * extracted from them light, and so do the key concepts they were tagged with.
 */
export function litByCitations(map: MapResponse, sourceIds: number[]): Lit | null {
  const wanted = new Set(sourceIds)
  const sources = map.sources.filter((source) => wanted.has(source.id))
  if (sources.length === 0) return null
  const lit: Lit = {
    sources: new Set(sources.map((s) => s.id)),
    concepts: new Set(),
    keyConcepts: new Set(),
    gaps: new Set(),
  }
  for (const source of sources) for (const tag of source.tags) lit.keyConcepts.add(tag.key_concept)
  for (const concept of map.concepts) {
    if (concept.source_ids.some((id) => lit.sources.has(id))) lit.concepts.add(concept.id)
  }
  return lit
}

/** `?cited=804,812` → `[804, 812]`, dropping anything that is not an id. */
export function parseCited(raw: string | null): number[] {
  if (!raw) return []
  return raw
    .split(',')
    .map((part) => Number(part.trim()))
    .filter((id) => Number.isInteger(id) && id > 0)
    .slice(0, 60)
}
