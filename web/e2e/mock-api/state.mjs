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
 * The graph fixture blown up to the size a real corpus reaches.
 *
 * The captured fixture has six concepts. A real expert has a thousand, and the
 * page caps the view at four hundred — a scale at which the layout worker, the
 * quadtree and the paint loop behave differently from six nodes in a row. The
 * shape is deterministic (a ring with chords) so a test can assert on it, and
 * the first six nodes stay exactly as the fixture has them, so every existing
 * assertion about labels and contradictions still holds.
 */
export function bigGraph(base) {
  const NODES = 400
  const nodes = [...base.nodes]
  for (let i = nodes.length; i < NODES; i += 1) {
    nodes.push({
      id: 1000 + i,
      label: `synthetic concept ${i}`,
      node_type: 'concept',
      degree: 1 + (i % 7),
    })
  }
  const edges = [...base.edges]
  for (let i = 0; i < NODES; i += 1) {
    edges.push({
      id: 5000 + i,
      source: nodes[i].id,
      target: nodes[(i + 1) % NODES].id,
      edge_type: 'related_to',
      evidence: 1 + (i % 3),
    })
  }
  return { ...base, nodes, edges, total_nodes: 1125, total_edges: edges.length }
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
