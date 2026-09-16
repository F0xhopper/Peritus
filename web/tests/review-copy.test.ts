import { describe, expect, it } from 'vitest'

import { endsMidSentence } from '@/components/chat/assistant-card'
import { numberCitations } from '@/components/chat/citations'
import { dotState, isBuilding, stateLabel } from '@/components/ui/status-dot'
import { describeBuildFailure } from '@/lib/build/copy'
import { STAGE_LABEL, TIMELINE } from '@/lib/build/reducer'
import { chatTitle } from '@/lib/format'
import { describeDiscovery, describeTextRead, sourceKind } from '@/lib/source-kind'

/**
 * The UX-review changes that are logic rather than layout: what counts as a live
 * build, how an answer numbers its citations, when an answer is visibly cut
 * short, and the words the pipeline's keys become.
 */

describe('build state', () => {
  it('treats a queued row with no job behind it as not building', () => {
    // The real "Thomism · Queued · 117h" case: answerable, no job.
    expect(dotState('queued', 'graph_ready', false)).toBe('ready')
    expect(isBuilding({ status: 'queued', readiness: 'graph_ready', build_active: false })).toBe(
      false
    )
    // And one that cannot answer says the build never started.
    expect(dotState('queued', 'pending', false)).toBe('stalled')
    expect(stateLabel('stalled')).toBe('Build never started')
  })

  it('still shows a real build as building, and an older server as before', () => {
    expect(isBuilding({ status: 'building', readiness: 'pending', build_active: true })).toBe(true)
    expect(isBuilding({ status: 'queued', readiness: 'pending' })).toBe(true)
    expect(dotState('building', 'chat_ready', true)).toBe('chat-ready')
  })
})

describe('numberCitations', () => {
  const citations = [
    { n: 1, label: 'a', source_id: 1 },
    { n: 3, label: 'c', source_id: 3 },
    { n: 7, label: 'g', source_id: 7 },
  ]

  it('numbers citations 1, 2, 3 in the order the answer first uses them', () => {
    const numbered = numberCitations('First [3]. Then [1] and [3] again.', citations)
    expect(numbered.map((c) => [c.n, c.display])).toEqual([
      [3, 1],
      [1, 2],
      [7, 3],
    ])
  })
})

describe('endsMidSentence', () => {
  it('flags prose that stops without finishing', () => {
    expect(endsMidSentence('A full paragraph.\n\nletting a beekeeper watch the colony’s')).toBe(
      true
    )
  })

  it('accepts a finished sentence, with or without a trailing citation', () => {
    expect(endsMidSentence('It doubles every month [2].')).toBe(false)
    expect(endsMidSentence('It doubles every month.[2]')).toBe(false)
  })

  it('does not judge blocks that legitimately end without a full stop', () => {
    expect(endsMidSentence('- one\n- two')).toBe(false)
    expect(endsMidSentence('| a | b |\n|---|---|\n| 1 | 2 |')).toBe(false)
    expect(endsMidSentence('```\nx = 1\n```')).toBe(false)
  })
})

describe('describeBuildFailure', () => {
  it('turns the planning failure into a sentence for the reader', () => {
    const { headline, advice } = describeBuildFailure(
      'Build finished without: key concepts (research planning failed). An expert is only ready once…'
    )
    expect(headline).toBe('Planning the search failed, so nothing was searched.')
    expect(advice).toBe('Rebuilding usually fixes this.')
  })

  it('has a plain fallback for anything unrecognised', () => {
    expect(describeBuildFailure(null).headline).toMatch(/stopped before/)
  })
})

describe('vocabulary', () => {
  it('uses one name per stage on the timeline', () => {
    expect(TIMELINE.map((segment) => segment.label)).toEqual([
      'Planning',
      'Searching',
      'Screening',
      'Reading',
      'Mapping concepts',
      'Writing the voice',
    ])
    expect(STAGE_LABEL.validate).toBe('Screening')
  })

  it('names what a source is and how it was found, not the fetcher key', () => {
    expect(sourceKind('openalex')).toBe('Paper')
    expect(sourceKind('exa')).toBe('Web page')
    expect(describeDiscovery('plan')).toBe('Planned search')
    expect(describeDiscovery('gapfill:acaricide resistance')).toBe(
      'Follow-up search: acaricide resistance'
    )
    expect(describeTextRead('oa_landing_html')).toBe('Open-access web page')
  })

  it('sentence-cases chat titles stored in the question’s own casing', () => {
    expect(chatTitle('what is the potency')).toBe('What is the potency')
    expect(chatTitle(null)).toBe('Untitled chat')
  })
})
