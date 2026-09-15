import { describe, expect, it } from 'vitest'

import fixtures from './fixtures/build-events.json' with { type: 'json' }
import {
  groupRows,
  initialBuildState,
  isTerminalEvent,
  reduceAll,
  reduceBuildEvent,
  TIMELINE,
} from '@/lib/build/reducer'
import type { BuildEvent } from '@/lib/api/types'

/**
 * The build-event reducer, driven by one captured payload per event type.
 *
 * The fixtures are the contract. Typing them against `BuildEvent` is what makes
 * a backend schema change fail `tsc` here rather than fail silently in a
 * browser — which is the whole reason they exist as JSON rather than as inline
 * literals.
 */

// This annotation is the schema check: a fixture that stops matching the
// interface is a type error at build time.
const events: Record<string, BuildEvent> = fixtures

/** Apply a named fixture sequence, numbering the sequences from 1. */
function play(...names: string[]) {
  return reduceAll(
    initialBuildState(),
    names.map((name, index) => {
      const event = events[name]
      if (!event) throw new Error(`No fixture named ${name}`)
      return { seq: index + 1, event }
    }),
  )
}

describe('every captured event type is handled', () => {
  it('reduces each fixture without throwing', () => {
    for (const [name, event] of Object.entries(events)) {
      expect(() => reduceBuildEvent(initialBuildState(), 1, event), name).not.toThrow()
    }
  })
})

describe('unknown event types', () => {
  it('are ignored, not thrown', () => {
    // A newer API emitting an event this build has never seen must not break
    // the page someone is watching a paid build from.
    const state = play('unknown_future_event')
    expect(state.rows).toEqual([])
    expect(state.terminal).toBeNull()
  })

  it('still advance the cursor, so a reconnect does not replay them', () => {
    const state = reduceBuildEvent(initialBuildState(), 12, events.unknown_future_event)
    expect(state.lastSeq).toBe(12)
  })
})

describe('the slug', () => {
  it('comes from the created event and nowhere else', () => {
    const state = play('created')
    expect(state.slug).toBe('varroa-mite-control-in-temperate-beekeeping')
    expect(state.jobId).toBe(118)
    expect(state.tier).toBe('standard')
  })

  it('is null before the created event arrives', () => {
    expect(play('build_started').slug).toBeNull()
  })
})

describe('terminal events', () => {
  it('recognises exactly done, error and cancelled', () => {
    expect(isTerminalEvent(events.done)).toBe(true)
    expect(isTerminalEvent(events.error)).toBe(true)
    expect(isTerminalEvent(events.cancelled)).toBe(true)
    // Not terminal: a closed stream after these means "reconnect".
    expect(isTerminalEvent(events.chat_ready)).toBe(false)
    expect(isTerminalEvent(events.graph_ready)).toBe(false)
    expect(isTerminalEvent(events.persona_ready)).toBe(false)
    expect(isTerminalEvent(events.retry)).toBe(false)
    expect(isTerminalEvent(events.stage_degraded)).toBe(false)
  })

  it('records done with its counts', () => {
    const state = play('created', 'done')
    expect(state.terminal).toEqual({
      kind: 'done',
      message: 'Dr. Marta Belen is ready — 21 sources, 412 passages',
    })
    expect(state.personaName).toBe('Dr. Marta Belen')
  })

  it('marks a spend-cap error as capped, which changes what the page offers', () => {
    const state = play('created', 'error_capped')
    expect(state.terminal).toMatchObject({
      kind: 'error',
      code: 'spend_cap_exceeded',
      capped: true,
    })
  })

  it('does not mark an ordinary failure as capped', () => {
    expect(play('created', 'error').terminal).toMatchObject({ kind: 'error', capped: false })
  })

  it('records a cancellation distinctly from a failure', () => {
    expect(play('created', 'cancelled').terminal).toEqual({
      kind: 'cancelled',
      message: 'Build cancelled',
    })
  })
})

describe('readiness', () => {
  it('sets chatReady on chat_ready and nothing earlier', () => {
    expect(play('created', 'stage_chunk').chatReady).toBe(false)
    const ready = play('created', 'stage_chunk', 'chat_ready')
    expect(ready.chatReady).toBe(true)
    expect(ready.readiness).toBe('chat_ready')
    // Still not graph-ready: that is a later stage.
    expect(ready.graphReady).toBe(false)
  })

  it('advances to graph_ready on the graph event', () => {
    const state = play('created', 'chat_ready', 'graph_ready')
    expect(state.graphReady).toBe(true)
    expect(state.readiness).toBe('graph_ready')
  })

  it('keeps chatReady true through a degraded graph stage', () => {
    // The point of degradation: the expert still answers.
    const state = play('created', 'chat_ready', 'stage_degraded')
    expect(state.chatReady).toBe(true)
    expect(state.graphReady).toBe(false)
    expect(state.degraded).toHaveLength(1)
  })
})

describe('the stage timeline', () => {
  it('activates a stage and completes everything before it', () => {
    const state = play('created', 'stage_plan', 'plan_ready', 'stage_validate')
    const plan = state.stages.find((stage) => stage.key === 'plan')!
    const discover = state.stages.find((stage) => stage.key === 'discover')!
    const validate = state.stages.find((stage) => stage.key === 'validate')!
    expect(plan.status).toBe('done')
    // Skipped forward over discover — it is treated as done rather than left
    // pending, or the timeline would show a hole.
    expect(discover.status).toBe('done')
    expect(validate.status).toBe('active')
  })

  it('maps resolve and reconcile onto the graph segment, not their own', () => {
    const resolve = play('created', 'stage_resolve')
    expect(resolve.activeStage).toBe('graph')
    const reconcile = play('created', 'stage_reconcile')
    expect(reconcile.activeStage).toBe('graph')
    // Six segments, not eight.
    expect(resolve.stages).toHaveLength(TIMELINE.length)
  })

  it('fills every segment on done, except a degraded one', () => {
    const state = play('created', 'chat_ready', 'stage_degraded', 'done')
    const graph = state.stages.find((stage) => stage.key === 'graph')!
    expect(graph.status).toBe('degraded')
    expect(state.stages.filter((stage) => stage.status === 'done')).toHaveLength(
      TIMELINE.length - 1,
    )
  })

  it('marks the running stage failed on an error', () => {
    const state = play('created', 'stage_validate', 'error')
    expect(state.stages.find((stage) => stage.key === 'validate')!.status).toBe('failed')
    expect(state.activeStage).toBeNull()
  })

  it('carries a stage detail without adding a row', () => {
    // `fetch_progress` fires per download; a row each would drown the log.
    const before = play('created', 'stage_validate')
    const after = reduceBuildEvent(before, 9, events.fetch_progress)
    expect(after.rows).toHaveLength(before.rows.length)
    expect(after.stages.find((stage) => stage.key === 'discover')!.detail).toBe(
      'fetched 18 of 30',
    )
  })
})

describe('screening rows', () => {
  it('marks a kept source as a keep row with its scores', () => {
    const state = play('created', 'source_validated_keep')
    const row = state.rows.at(-1)!
    expect(row.kind).toBe('keep')
    expect(row.scores).toMatchObject({ q: 8.5, r: 9 })
    expect(state.counts.kept).toBe(1)
  })

  it('marks a dropped source as a drop row and states the reason', () => {
    const state = play('created', 'source_validated_drop')
    const row = state.rows.at(-1)!
    expect(row.kind).toBe('drop')
    expect(row.message).toContain('Secondary commentary')
    expect(state.counts.dropped).toBe(1)
  })

  it('does not double-count a reviewed source', () => {
    // The review is a second look at a source already counted, so counting it
    // again would overstate the corpus.
    const state = play('created', 'source_validated_keep', 'source_reviewed')
    expect(state.counts.kept).toBe(1)
    expect(state.rows.at(-1)!.message).toContain('reviewed, reversed')
  })

  it('shows the first-pass scores on a reviewed row', () => {
    const state = play('created', 'source_reviewed')
    expect(state.rows.at(-1)!.scores).toMatchObject({ firstQ: 5.5, firstR: 5.5, q: 8, r: 8.5 })
  })
})

describe('discovery', () => {
  it('reads the stop reason and flags anything but targets_met', () => {
    const met = play('created', 'discovery_done')
    expect(met.rows.at(-1)!.kind).toBe('ok')
    expect(met.rows.at(-1)!.message).toBe('Search met its coverage targets after 2 rounds')

    const short = reduceBuildEvent(initialBuildState(), 1, {
      type: 'discovery_done',
      rounds: 2,
      stop_reason: 'budget_exhausted',
    })
    expect(short.rows.at(-1)!.kind).toBe('warn')
    expect(short.rows.at(-1)!.message).toContain('budget exhausted')
  })

  it('warns when coverage is short and confirms when it is not', () => {
    expect(play('created', 'coverage_report').rows.at(-1)).toMatchObject({
      kind: 'warn',
      message: 'Coverage: 1 of 2 concepts still short',
    })
  })

  it('records a skipped fetcher as a warning with its reason', () => {
    const state = play('created', 'fetcher_skipped')
    expect(state.rows.at(-1)).toMatchObject({ kind: 'warn' })
    expect(state.rows.at(-1)!.message).toContain('no public-domain works')
  })

  it('keeps the key concepts from the plan', () => {
    expect(play('created', 'plan_ready').keyConcepts).toHaveLength(4)
  })
})

describe('retries', () => {
  it('records the attempt and flags the build as retrying', () => {
    const state = play('created', 'retry')
    expect(state.retrying).toBe(true)
    expect(state.retries).toEqual([
      { attempt: 1, maxAttempts: 3, message: 'Provider timed out during validation.' },
    ])
  })

  it('clears the retrying flag once the build starts again', () => {
    expect(play('created', 'retry', 'build_started').retrying).toBe(false)
  })

  it('starts a later attempt from nothing, because the worker wiped the last one', () => {
    const first = play('created', 'build_started', 'stage_chunk', 'source_ingested', 'chat_ready', 'retry')
    expect(first.chatReady).toBe(true)

    const second = reduceBuildEvent(first, first.lastSeq + 1, {
      type: 'build_started',
      attempt: 2,
      max_attempts: 3,
    })
    expect(second.chatReady).toBe(false)
    expect(second.readiness).toBe('pending')
    expect(second.counts.chunks).toBe(0)
    expect(second.stages.every((s) => s.status === 'pending')).toBe(true)
    // The history of why it retried stays in the log.
    expect(second.rows.length).toBe(first.rows.length + 1)
  })

  it('keeps what the last attempt built when the retry resumes from it', () => {
    const first = play('created', 'build_started', 'stage_chunk', 'source_ingested', 'chat_ready', 'retry')

    const second = reduceBuildEvent(first, first.lastSeq + 1, {
      type: 'build_started',
      attempt: 2,
      max_attempts: 3,
      resumed_from: 'chat_ready',
    })
    expect(second.chatReady).toBe(true)
    expect(second.readiness).toBe(first.readiness)
    expect(second.counts.chunks).toBe(first.counts.chunks)
    expect(second.rows.at(-1)?.message).toBe(
      'Build started (attempt 2 of 3, resuming from chat ready)',
    )
  })
})

describe('grouping', () => {
  it('folds consecutive fetcher rows of the same round into one group', () => {
    const state = play('created', 'fetcher_done', 'fetcher_skipped', 'triage_done')
    const groups = groupRows(state.rows)
    const fetchers = groups.find((group) => group.group === 'fetchers:0')
    expect(fetchers?.rows).toHaveLength(2)
    // The ungrouped rows stay ungrouped.
    expect(groups.filter((group) => group.group === null).length).toBeGreaterThan(0)
  })

  it('does not merge groups from different rounds', () => {
    const round1 = { ...events.fetcher_done, round: 1 } as BuildEvent
    const state = reduceAll(initialBuildState(), [
      { seq: 1, event: events.fetcher_done },
      { seq: 2, event: round1 },
    ])
    const groups = groupRows(state.rows)
    expect(groups.map((group) => group.group)).toEqual(['fetchers:0', 'fetchers:1'])
  })

  it('groups ingest rows, which are one per source', () => {
    const state = play('created', 'source_ingested', 'source_ingested')
    expect(groupRows(state.rows).find((group) => group.group === 'ingest')?.rows).toHaveLength(2)
  })
})

describe('the expert picture', () => {
  /**
   * Finding a picture is not a stage. It runs beside discovery, off
   * `plan_ready`, and nothing about it can fail or delay a build — so what
   * these assert is mostly what does *not* happen: no timeline segment moves,
   * no stage is marked degraded, and no terminal state is reached.
   */
  it('logs the picture it found, with its licence', () => {
    const state = play('created', 'plan_ready', 'picture_ready')
    const row = state.rows.at(-1)
    expect(row?.kind).toBe('ok')
    expect(row?.stage).toBeNull()
    expect(row?.message).toContain('Varroa destructor')
    expect(row?.message).toContain('CC BY-SA 2.0')
  })

  it('says why there is none, quietly', () => {
    // `meta`, not `warn`: no picture is not a degradation. The expert shows
    // its monogram, which is what every expert looked like before this existed.
    const state = play('created', 'plan_ready', 'picture_skipped')
    const row = state.rows.at(-1)
    expect(row?.kind).toBe('meta')
    expect(row?.message).toBe('No picture — no freely licensed picture of this subject')
  })

  it('reports a reason it has never seen rather than dropping it', () => {
    const state = reduceBuildEvent(initialBuildState(), 1, {
      type: 'picture_skipped',
      reason: 'some_future_reason',
    } as BuildEvent)
    expect(state.rows.at(-1)?.message).toContain('some_future_reason')
  })

  it('touches neither the timeline nor the terminal state', () => {
    const state = play('created', 'plan_ready', 'picture_ready', 'picture_skipped')
    expect(state.terminal).toBeNull()
    expect(state.degraded).toEqual([])
    // `plan` completed; nothing after it moved.
    expect(state.stages.filter((s) => s.status !== 'pending' && s.key !== 'plan')).toEqual([])
  })
})

describe('the cursor', () => {
  it('never regresses, even if events arrive out of order', () => {
    let state = reduceBuildEvent(initialBuildState(), 40, events.build_started)
    state = reduceBuildEvent(state, 12, events.stage_plan)
    expect(state.lastSeq).toBe(40)
  })
})

describe('a whole build', () => {
  it('reduces the full happy path to a ready expert', () => {
    const state = play(
      'created',
      'build_started',
      'execution_mode',
      'stage_plan',
      'plan_ready',
      'discovery_started',
      'fetcher_done',
      'dedup_done',
      'triage_done',
      'fetch_done',
      'stage_validate',
      'source_validated_keep',
      'source_validated_drop',
      'validate_done',
      'coverage_report',
      'round_started',
      'feedback_queries',
      'snowball_done',
      'discovery_done',
      'stage_chunk',
      'source_ingested',
      'chat_ready',
      'stage_graph',
      'graph_batch_done',
      'entities_resolved',
      'claims_reconciled',
      'graph_ready',
      'stage_persona',
      'persona_ready',
      'done',
    )

    expect(state.terminal?.kind).toBe('done')
    expect(state.chatReady).toBe(true)
    expect(state.graphReady).toBe(true)
    expect(state.readiness).toBe('graph_ready')
    expect(state.personaName).toBe('Dr. Marta Belen')
    expect(state.degraded).toEqual([])
    expect(state.rows.length).toBeGreaterThan(15)
    // Every row has a unique, monotonic key.
    const seqs = state.rows.map((row) => row.seq)
    expect(new Set(seqs).size).toBe(seqs.length)
    expect([...seqs].sort((a, b) => a - b)).toEqual(seqs)
  })
})
