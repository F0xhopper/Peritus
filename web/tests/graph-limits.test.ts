import { describe, expect, it } from 'vitest'

import { GRAPH_LIMITS, GRAPH_LIMIT_DEFAULT, parseGraphLimit } from '@/lib/graph/limits'

describe("the Graph view's node limit", () => {
  it('takes any of the stops the slider has', () => {
    for (const limit of GRAPH_LIMITS) expect(parseGraphLimit(String(limit))).toBe(limit)
  })

  it('falls back rather than forwarding what the API would refuse', () => {
    // A URL someone edited by hand: the API's bound is 1–1500 and it answers
    // anything else with a 422, which the page would show as an error.
    for (const raw of [null, undefined, '', '0', '-5', '250', '99999', 'abc', '400.5', ' ']) {
      expect(parseGraphLimit(raw)).toBe(GRAPH_LIMIT_DEFAULT)
    }
  })

  it('defaults to a stop, so the slider always has a position', () => {
    expect((GRAPH_LIMITS as readonly number[]).includes(GRAPH_LIMIT_DEFAULT)).toBe(true)
  })
})
