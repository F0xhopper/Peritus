import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

/**
 * The world this server serves.
 *
 * Everything the suite asserts against starts from the captured fixtures in
 * `tests/fixtures/`, which are real API payloads. That is deliberate: the
 * fixture tests bind each one to its TypeScript interface, so a payload that
 * drifts fails `tsc` rather than turning up as `undefined` in a browser — and
 * this server serving the same files is what makes the browser suite exercise
 * the same shapes.
 */

const FIXTURES = fileURLToPath(new URL('../../tests/fixtures/', import.meta.url))

export async function fixture(name) {
  return JSON.parse(await readFile(`${FIXTURES}${name}.json`, 'utf8'))
}

/**
 * The map fixture blown up to the size a real expert reaches.
 *
 * The captured fixture has twenty-two concepts and ten sources. Thomism draws
 * 132 concepts on 37 sources and the cloud is capped at 250 — a scale at which
 * the layout worker, the labels' collision pass and the paint loop behave
 * differently. Deterministic, so a test can assert on it; the fixture's own
 * rows stay exactly as they are, so every assertion about them still holds.
 */
export function bigMap(base) {
  const SOURCES = 48
  const CONCEPTS = 250
  const keys = base.syllabus.key_concepts.length
  const sources = [...base.sources]
  for (let i = sources.length; i < SOURCES; i += 1) {
    sources.push({
      id: 2000 + i,
      title: `Synthetic source ${i}`,
      author: null,
      kind: ['openalex', 'pubmed', 'web', 'gutenberg'][i % 4],
      tier: ['primary', 'secondary', 'tertiary'][i % 3],
      passage_count: 3 + ((i * 7) % 40),
      tags: [{ key_concept: i % keys, depth: ['sets_out', 'treats', 'mentions'][i % 3] }],
    })
  }
  const concepts = [...base.concepts]
  for (let i = concepts.length; i < CONCEPTS; i += 1) {
    const a = sources[i % SOURCES].id
    const b = sources[(i * 5 + 3) % SOURCES].id
    concepts.push({
      id: 20000 + i,
      label: `synthetic concept ${i}`,
      key_concept: i % 9 === 0 ? null : i % keys,
      source_ids: a === b ? [a] : [a, b].sort((x, y) => x - y),
      degree: 1 + (i % 11),
      disputes: 0,
      topped_up: a === b,
    })
  }
  const links = [...base.links]
  for (let i = base.concepts.length; i < CONCEPTS - 1; i += 3) {
    links.push({ from: concepts[i].id, to: concepts[i + 1].id })
  }
  return {
    ...base,
    sources,
    concepts,
    links,
    totals: { concepts: 1063, concepts_shown: CONCEPTS, claims: 1820, sources: SOURCES },
  }
}

export const state = {
  /** slug → expert */
  experts: new Map(),
  /** slug → { events: [...], cursor, terminal } */
  builds: new Map(),
  conversations: new Map(),
  nextConversation: 1,
  /** slug → { token, viewers } for the caller's own experts with a live link. */
  links: new Map(),
  /** Someone else's expert, reachable only through its share token until opened. */
  foreign: null,
  /** Set by the test harness to steer a scenario. */
  scenario: 'happy',
  /**
   * The slug a scenario applies to, or null for any.
   *
   * Scoped because Home tails a build of its own for the seeded in-progress
   * expert — so an unscoped `drop-midway` fires on *that* stream and the test's
   * build never sees it.
   */
  scenarioSlug: null,
}

/**
 * The bytes served at `/experts/:slug/picture`.
 *
 * A real 1x1 PNG, built here rather than checked in: the e2e assertions are
 * about *which element renders and where its src points*, not about what the
 * image depicts, and a binary fixture in the repo would be one more thing to
 * keep in step with nothing.
 */
export const PICTURE_BYTES = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64'
)
export const PICTURE_SHA = 'f1e2d3c4b5a6'

/** The seeded expert that has one. */
export const PICTURE_SLUG = 'stoic-philosophy'

/** What the API returns on every expert that has one. */
export function pictureMeta() {
  return {
    version: PICTURE_SHA,
    width: 512,
    height: 341,
    provider: 'wikipedia',
    title: 'Varroa destructor',
    artist: 'Gilles San Martin',
    license: 'CC BY-SA 2.0',
    license_url: 'https://creativecommons.org/licenses/by-sa/2.0',
    page_url: 'https://en.wikipedia.org/wiki/Varroa_destructor',
    file_page_url: 'https://commons.wikimedia.org/wiki/File:Varroa_destructor_on_honeybee_host.jpg',
    attribution_required: true,
  }
}
