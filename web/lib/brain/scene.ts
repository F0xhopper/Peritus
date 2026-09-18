import type { MapResponse } from '@/lib/api/types'
import { ORBIT, conceptRadius, hash, type BrainLayout } from '@/lib/brain/layout'
import { pulseDuration, type Pulse } from '@/lib/brain/motion'
import type { Hit } from '@/lib/brain/paint'
import type { BrainSelection, Lit } from '@/lib/brain/selection'

/**
 * The map's scene helpers: what is under a point, what a selection maps to on
 * the canvas, and which dendrites fire. Pure, so they are unit-tested
 * (`tests/brain-scene.test.ts`) rather than trusted inside the component.
 */

const MAX_SELECTION_PULSES = 80

export function hitKey(hit: Hit | null): string {
  return hit ? `${hit.kind}:${hit.index}` : ''
}

/** The canvas's accessible summary. The List is the accessible form of the page. */
export function mapSummary(map: MapResponse): string {
  const facets = map.syllabus.facets?.length ?? 0
  const keys = map.syllabus.key_concepts.length
  const missing = map.syllabus.gaps.length
  const parts = [
    `${map.sources.length} ${map.sources.length === 1 ? 'source' : 'sources'}`,
    `${keys} key ${keys === 1 ? 'concept' : 'concepts'}${facets ? ` in ${facets} facets` : ''}`,
    map.computed ? `${map.concepts.length} concepts` : 'concepts still being extracted',
  ]
  const text = `Map of this expert's knowledge: ${parts.join(', ')}`
  return missing
    ? `${text}; ${missing} named ${missing === 1 ? 'text' : 'texts'} missing.`
    : `${text}.`
}

export function hitFor(map: MapResponse, selection: BrainSelection | null): Hit | null {
  if (!selection) return null
  switch (selection.kind) {
    case 'source': {
      const index = map.sources.findIndex((s) => s.id === selection.id)
      return index >= 0 ? { kind: 'source', index } : null
    }
    case 'concept': {
      const index = map.concepts.findIndex((c) => c.id === selection.id)
      return index >= 0 ? { kind: 'concept', index } : null
    }
    case 'keyConcept':
      return selection.index < map.syllabus.key_concepts.length
        ? { kind: 'keyConcept', index: selection.index }
        : null
    case 'gap':
      return selection.index < map.syllabus.gaps.length
        ? { kind: 'gap', index: selection.index }
        : null
  }
}

export function selectionFor(map: MapResponse, hit: Hit): BrainSelection {
  switch (hit.kind) {
    case 'source':
      return { kind: 'source', id: map.sources[hit.index].id }
    case 'concept':
      return { kind: 'concept', id: map.concepts[hit.index].id }
    case 'keyConcept':
      return { kind: 'keyConcept', index: hit.index }
    case 'gap':
      return { kind: 'gap', index: hit.index }
  }
}

export function hitPoint(layout: BrainLayout, hit: Hit): [number, number] {
  switch (hit.kind) {
    case 'concept':
      return [layout.concepts[hit.index * 2], layout.concepts[hit.index * 2 + 1]]
    case 'keyConcept':
      return [layout.keyConcepts[hit.index].x, layout.keyConcepts[hit.index].y]
    case 'source':
      return [layout.sources[hit.index].x, layout.sources[hit.index].y]
    case 'gap':
      return [layout.gaps[hit.index].x, layout.gaps[hit.index].y]
  }
}

/**
 * The thing under a layout point, nearest edge first. Linear over at most a few
 * hundred things, which a pointer move can afford; a quadtree would have to be
 * rebuilt for every kind.
 */
export function hitTest(
  map: MapResponse,
  layout: BrainLayout,
  x: number,
  y: number,
  slack: number
): Hit | null {
  let best: Hit | null = null
  let bestScore = 0
  const consider = (hit: Hit, px: number, py: number, radius: number) => {
    const score = Math.hypot(px - x, py - y) - radius - slack
    if (score < bestScore) {
      bestScore = score
      best = hit
    }
  }
  layout.keyConcepts.forEach((place, index) =>
    consider({ kind: 'keyConcept', index }, place.x, place.y, place.r)
  )
  layout.sources.forEach((place, index) =>
    consider({ kind: 'source', index }, place.x, place.y, place.size / 2)
  )
  layout.gaps.forEach((place, index) =>
    consider({ kind: 'gap', index }, place.x, place.y, place.size / 2)
  )
  map.concepts.forEach((concept, index) =>
    consider(
      { kind: 'concept', index },
      layout.concepts[index * 2],
      layout.concepts[index * 2 + 1],
      conceptRadius(concept.source_ids.length) + 2
    )
  )
  return best
}

/** Inward, once: every drawn concept's sources to it, then each concept to its key concept. */
export function entrancePulses(map: MapResponse, layout: BrainLayout, now: number): Pulse[] {
  const out: Pulse[] = []
  const sourceIndex = new Map(map.sources.map((s, i) => [s.id, i]))
  map.concepts.forEach((concept, i) => {
    if (out.length >= 160) return
    const to: [number, number] = [layout.concepts[i * 2], layout.concepts[i * 2 + 1]]
    const first = concept.source_ids.map((id) => sourceIndex.get(id)).find((j) => j !== undefined)
    if (first !== undefined) {
      const from: [number, number] = [layout.sources[first].x, layout.sources[first].y]
      out.push({ from, to, start: now + (i % 7) * 40, duration: pulseDuration(from, to) })
    }
    const key = concept.key_concept !== null ? layout.keyConcepts[concept.key_concept] : undefined
    if (key) {
      const end: [number, number] = [key.x, key.y]
      out.push({
        from: to,
        to: end,
        start: now + 650 + (i % 7) * 40,
        duration: pulseDuration(to, end),
      })
    }
  })
  return out
}

/** One pulse down each lit source → concept / key-concept dendrite. */
export function selectionPulses(
  map: MapResponse,
  layout: BrainLayout,
  lit: Lit,
  now: number
): Pulse[] {
  const out: Pulse[] = []
  const conceptIndex = new Map(map.concepts.map((c, i) => [c.id, i]))
  map.sources.forEach((source, i) => {
    if (!lit.sources.has(source.id)) return
    const from: [number, number] = [layout.sources[i].x, layout.sources[i].y]
    for (const concept of map.concepts) {
      if (out.length >= MAX_SELECTION_PULSES) return
      if (!lit.concepts.has(concept.id) || !concept.source_ids.includes(source.id)) continue
      const j = conceptIndex.get(concept.id)!
      const to: [number, number] = [layout.concepts[j * 2], layout.concepts[j * 2 + 1]]
      out.push({ from, to, start: now, duration: pulseDuration(from, to) })
    }
    for (const tag of source.tags) {
      const key = layout.keyConcepts[tag.key_concept]
      if (!key || !lit.keyConcepts.has(tag.key_concept) || out.length >= MAX_SELECTION_PULSES)
        continue
      const to: [number, number] = [key.x, key.y]
      out.push({ from, to, start: now, duration: pulseDuration(from, to) })
    }
  })
  return out
}

/** While idle, one random source → concept dendrite fires. One moving dot. */
export function idlePulse(
  map: MapResponse,
  layout: BrainLayout,
  random: () => number,
  now: number
): Pulse | null {
  if (map.concepts.length === 0 || map.sources.length === 0) return null
  const i = Math.floor(random() * map.concepts.length)
  const concept = map.concepts[i]
  const sourceId = concept.source_ids[Math.floor(random() * concept.source_ids.length)]
  const j = map.sources.findIndex((s) => s.id === sourceId)
  if (j < 0) return null
  const from: [number, number] = [layout.sources[j].x, layout.sources[j].y]
  const to: [number, number] = [layout.concepts[i * 2], layout.concepts[i * 2 + 1]]
  return { from, to, start: now, duration: pulseDuration(from, to) }
}

/**
 * A source that has just landed on the orbit: one pulse inward to each key
 * concept it covers and each concept drawn from it.
 */
export function arrivalPulses(
  map: MapResponse,
  layout: BrainLayout,
  arrived: Set<number>,
  now: number
): Pulse[] {
  const lit: Lit = {
    sources: arrived,
    concepts: new Set(),
    keyConcepts: new Set(),
    gaps: new Set(),
  }
  for (const source of map.sources) {
    if (!arrived.has(source.id)) continue
    for (const tag of source.tags) lit.keyConcepts.add(tag.key_concept)
  }
  for (const concept of map.concepts) {
    if (concept.source_ids.some((id) => arrived.has(id))) lit.concepts.add(concept.id)
  }
  return selectionPulses(map, layout, lit, now)
}

export type BurstEffect =
  | { key: string; kind: 'judged'; passed: boolean }
  | { key: string; kind: 'read'; sourceIds: number[] }

/**
 * The build log's one-off effects.
 *
 * - A candidate judged: a speck just outside the orbit at an angle hashed from
 *   its key. Kept, it drifts onto the orbit; dropped, it drifts away and fades.
 *   It is *not yet a source* — composition caps can still drop it.
 * - A graph batch read some sources: each pulses inward to its key concepts.
 */
export function burstPulses(
  map: MapResponse,
  layout: BrainLayout,
  bursts: BurstEffect[],
  now: number
): Pulse[] {
  const out: Pulse[] = []
  const index = new Map(map.sources.map((source, i) => [source.id, i]))
  bursts.forEach((burst, order) => {
    if (burst.kind === 'judged') {
      const angle = hash(stringHash(burst.key), 3) * Math.PI * 2
      const at = (r: number): [number, number] => [Math.cos(angle) * r, Math.sin(angle) * r]
      out.push({
        from: at(ORBIT + 70),
        to: at(burst.passed ? ORBIT : ORBIT + 150),
        start: now + order * 90,
        duration: 900,
      })
      return
    }
    for (const id of burst.sourceIds) {
      const i = index.get(id)
      if (i === undefined) continue
      const from: [number, number] = [layout.sources[i].x, layout.sources[i].y]
      for (const tag of map.sources[i].tags) {
        const key = layout.keyConcepts[tag.key_concept]
        if (!key) continue
        const to: [number, number] = [key.x, key.y]
        out.push({ from, to, start: now, duration: pulseDuration(from, to) })
      }
    }
  })
  return out
}

function stringHash(text: string): number {
  let h = 0
  for (let i = 0; i < text.length; i += 1) h = (Math.imul(h, 31) + text.charCodeAt(i)) | 0
  return h
}
