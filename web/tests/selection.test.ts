import { describe, expect, it } from 'vitest'

import screeningFlow from './fixtures/screening-flow.json' with { type: 'json' }
import type { CorpusComposition, ScreeningFlow } from '@/lib/api/types'
import {
  canonicalFound,
  describeChannelStatus,
  describeFetchOutcome,
  describeMustHave,
  describeMustHaveFor,
  isMustHaveFound,
  ledgerByOutcome,
  mustHaveGroups,
  mustHaveTone,
} from '@/lib/selection'

/**
 * The arithmetic behind the Sources page's Selection section. Component
 * rendering is Playwright's job (see vitest.config.mts); what is checked here
 * is that the numbers the section shows are the numbers the API sent.
 */

const flow = screeningFlow as ScreeningFlow
const selection = flow.selection!
if (!selection.available) throw new Error('fixture selection must be available')
const corpus = selection.corpus as CorpusComposition

describe('canonical works', () => {
  it('counts found in full and named sections found as found, across both scopes', () => {
    expect(canonicalFound(corpus)).toEqual({ found: 2, total: 5 })
  })

  it('phrases each status', () => {
    expect(corpus.must_have.map((work) => describeMustHave(work.status))).toEqual([
      'Found in full',
      'Only parts found',
      'Not found',
      'Named sections found',
      'Not found',
    ])
  })

  it('colours found green, parts amber and missing red', () => {
    expect(
      ['found_whole', 'found_sections', 'found_partial', 'not_found'].map(mustHaveTone)
    ).toEqual(['ok', 'ok', 'warn', 'bad'])
    expect(isMustHaveFound('found_partial')).toBe(false)
  })

  it('splits canonical works from primary texts for concepts, treating no scope as overall', () => {
    const groups = mustHaveGroups(corpus)
    expect(
      groups.map((group) => ({
        scope: group.scope,
        title: group.title,
        found: group.found,
        total: group.total,
        works: group.works.map((work) => work.title),
      }))
    ).toEqual([
      {
        scope: 'overall',
        title: 'Canonical works',
        found: 1,
        total: 3,
        // The second and third entries carry no scope, as an older build's do.
        works: [
          'The Hive and the Honey-Bee',
          'ABC and XYZ of Bee Culture',
          'Varroa destructor: research avenues towards sustainable control',
        ],
      },
      {
        scope: 'concept',
        title: 'Primary texts for concepts',
        found: 1,
        total: 2,
        works: [
          'ABC and XYZ of Bee Culture',
          'Varroa jacobsoni (Acari: Varroidae) is more than one species',
        ],
      },
    ])
    expect(groups[1]!.works.map(describeMustHaveFor)).toEqual([
      'drone brood removal · Drone comb; Swarming',
      'acaricide resistance, varroa biology',
    ])
  })

  it('leaves out a group with no works', () => {
    const overallOnly = corpus.must_have.filter((work) => work.scope !== 'concept')
    expect(
      mustHaveGroups({ ...corpus, must_have: overallOnly }).map((group) => group.scope)
    ).toEqual(['overall'])
  })

  it('reports none of none for a plan with no must-have works', () => {
    expect(canonicalFound({ ...corpus, must_have: [] })).toEqual({ found: 0, total: 0 })
    expect(mustHaveGroups({ ...corpus, must_have: [] })).toEqual([])
  })
})

describe('the candidate ledger', () => {
  it('sums counts across rounds and triage statuses, in fall-through order', () => {
    expect(ledgerByOutcome(selection.candidate_ledger!.rows)).toEqual([
      { outcome: 'fetched', label: 'Fetched', count: 34 },
      { outcome: 'content_duplicate', label: 'Duplicate of a fetched text', count: 1 },
      { outcome: 'failed', label: 'Download failed', count: 3 },
      { outcome: 'below_floor', label: 'Scored under the fetch floor', count: 62 },
      { outcome: 'budget', label: 'Out of budget', count: 5 },
    ])
  })

  it('keeps an unrecorded outcome as its own row, last, never folded into another', () => {
    const rows = ledgerByOutcome([
      { round: 0, fetch_outcome: null, triage_status: 'scored', count: 2, mean_triage_score: null },
      {
        round: 0,
        fetch_outcome: 'fetched',
        triage_status: 'scored',
        count: 1,
        mean_triage_score: 7,
      },
      {
        round: 0,
        fetch_outcome: 'mystery',
        triage_status: 'scored',
        count: 1,
        mean_triage_score: 7,
      },
    ])
    expect(rows.map((row) => row.label)).toEqual(['Fetched', 'Mystery', 'Not recorded'])
  })

  it('names an outcome it has never seen rather than dropping it', () => {
    expect(describeFetchOutcome('some_new_outcome')).toBe('Some new outcome')
  })
})

describe('failed channels', () => {
  it('phrases the statuses the way the build log does', () => {
    expect(describeChannelStatus('timeout')).toBe('timed out')
    expect(describeChannelStatus('rate_limited')).toBe('rate-limited')
    expect(describeChannelStatus('error')).toBe('failed')
    expect(describeChannelStatus('brand_new')).toBe('brand new')
  })
})
