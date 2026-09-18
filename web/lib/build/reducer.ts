import {
  TERMINAL_BUILD_EVENTS,
  type BuildEvent,
  type ExpertTier,
  type Readiness,
  type StageName,
} from '@/lib/api/types'
import { describeChannelStatus } from '@/lib/selection'
import { initialGrowState, reduceGrow, type GrowState } from '@/lib/brain/grow'

/**
 * Build events in, a renderable log out.
 *
 * Two rules govern everything here.
 *
 * **An unknown event type is ignored, never thrown.** The API is free to add
 * events, and a deployed web build that crashed on one it had never seen would
 * turn a routine backend release into an outage on the page users watch a paid
 * build from.
 *
 * **Only a terminal event ends a build.** A closed stream is a dropped
 * connection until `done`, `error` or `cancelled` says otherwise, which is what
 * lets the client reconnect from `lastSeq` and resume rather than declaring a
 * running build finished.
 */

/**
 * The one name for each stage — on the timeline, in the log's stage column, on
 * the log's headline rows, on Home's "Building now" card and in every notice.
 * There used to be three vocabularies for the same six stages (Screen /
 * validate / Screening sources), two of them the pipeline's own keys.
 */
export const STAGE_LABEL: Record<StageName, string> = {
  plan: 'Planning',
  discover: 'Searching',
  validate: 'Screening',
  chunk: 'Reading',
  graph: 'Mapping concepts',
  // Sub-stages of the graph segment: they share its name.
  resolve: 'Mapping concepts',
  reconcile: 'Mapping concepts',
  persona: 'Writing the voice',
}

/** The six segments of the stage timeline, in pipeline order. */
export const TIMELINE: { key: StageName; label: string }[] = (
  ['plan', 'discover', 'validate', 'chunk', 'graph', 'persona'] as const
).map((key) => ({ key, label: STAGE_LABEL[key] }))

/** `resolve` and `reconcile` are sub-stages of graph, not segments of their own. */
const STAGE_SEGMENT: Record<string, StageName> = {
  plan: 'plan',
  discover: 'discover',
  validate: 'validate',
  chunk: 'chunk',
  graph: 'graph',
  resolve: 'graph',
  reconcile: 'graph',
  persona: 'persona',
}

export type RowKind = 'info' | 'keep' | 'drop' | 'stage' | 'warn' | 'bad' | 'ok' | 'meta'

export interface LogRow {
  /** The event's `seq`. Monotonic per job; with `sub`, the React key. */
  seq: number
  /**
   * Position within its event, set only on the second and later rows of an
   * event that logs several (`canonical_resolved` writes one per work). Read
   * the key through `rowKey`, never `seq` alone.
   */
  sub?: number
  kind: RowKind
  /** Which pipeline stage was running. Rendered in the second column. */
  stage: StageName | null
  message: string
  /** Rows in a collapsed group share a `group`; the group counts as one row. */
  group?: string
  raw: BuildEvent
}

export interface StageState {
  key: StageName
  /** 0 → not started, 1 → complete. The timeline fills segments with this. */
  progress: number
  status: 'pending' | 'active' | 'done' | 'degraded' | 'failed'
  detail?: string
}

export type Terminal =
  | { kind: 'done'; message: string }
  | { kind: 'error'; message: string; code?: string; capped: boolean }
  | { kind: 'cancelled'; message: string }

export interface BuildState {
  /** The slug from the `created` event. The only correct source of it. */
  slug: string | null
  jobId: number | null
  tier: ExpertTier | null
  topic: string | null
  rows: LogRow[]
  stages: StageState[]
  /** The stage currently running, for the timeline's active segment. */
  activeStage: StageName | null
  lastSeq: number
  terminal: Terminal | null
  /** True from the `chat_ready` event — this is what enables the chat button. */
  chatReady: boolean
  graphReady: boolean
  readiness: Readiness
  personaName: string | null
  keyConcepts: string[]
  /** Running counts, for the header line above the log. */
  counts: { considered: number; kept: number; dropped: number; chunks: number }
  /** Stages that degraded but did not fail the build. */
  degraded: { stage: string; message: string }[]
  warnings: string[]
  retries: { attempt: number; maxAttempts: number; message: string }[]
  /** True while the build is retrying after a recoverable failure. */
  retrying: boolean
  /** The brain as the log has grown it so far. */
  grow: GrowState
}

export function initialBuildState(): BuildState {
  return {
    slug: null,
    jobId: null,
    tier: null,
    topic: null,
    rows: [],
    stages: TIMELINE.map((s) => ({ key: s.key, progress: 0, status: 'pending' })),
    activeStage: null,
    lastSeq: 0,
    terminal: null,
    chatReady: false,
    graphReady: false,
    readiness: 'pending',
    personaName: null,
    keyConcepts: [],
    counts: { considered: 0, kept: 0, dropped: 0, chunks: 0 },
    degraded: [],
    warnings: [],
    retries: [],
    retrying: false,
    grow: initialGrowState(),
  }
}

/** The object entries of an array field, ignoring anything that is not one. */
function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
    : []
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function num(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function str(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

/** Mark a segment complete, and everything before it too. */
function completeThrough(stages: StageState[], key: StageName): StageState[] {
  const target = TIMELINE.findIndex((s) => s.key === key)
  if (target === -1) return stages
  return stages.map((stage, i) => {
    if (i < target) return stage.status === 'pending' ? { ...stage, progress: 1, status: 'done' } : stage
    if (i === target) return { ...stage, progress: 1, status: 'done' }
    return stage
  })
}

function activate(stages: StageState[], key: StageName, detail?: string): StageState[] {
  const target = TIMELINE.findIndex((s) => s.key === key)
  if (target === -1) return stages
  return stages.map((stage, i) => {
    if (i < target) return stage.status === 'pending' ? { ...stage, progress: 1, status: 'done' } : stage
    if (i === target) return { ...stage, status: 'active', progress: Math.max(stage.progress, 0.1), detail }
    return stage
  })
}

function markStage(
  stages: StageState[],
  key: StageName,
  status: StageState['status'],
  detail?: string,
): StageState[] {
  return stages.map((stage) =>
    stage.key === key ? { ...stage, status, detail: detail ?? stage.detail } : stage,
  )
}

/**
 * Apply one event.
 *
 * Returns the same object when the event changes nothing renderable, so React
 * can skip the re-render — a build emits one `source_validated` per source and
 * a `fetch_progress` per download, and the log is the hottest list in the app.
 */
export function reduceBuildEvent(state: BuildState, seq: number, event: BuildEvent): BuildState {
  const next = reduceLog(state, seq, event)
  // The brain growing is a second fold over the same log (lib/brain/grow.ts),
  // so the build page, a single added source and a replay all read one reducer.
  const grow = reduceGrow(state.grow, seq, event)
  if (grow === state.grow) return next
  return { ...next, grow }
}

function reduceLog(state: BuildState, seq: number, event: BuildEvent): BuildState {
  const type = event.type
  const next: BuildState = {
    ...state,
    lastSeq: Math.max(state.lastSeq, seq),
    // Any event arriving means the stream is alive again.
    retrying: type === 'retry' ? true : state.retrying,
  }
  let pushed = 0
  const push = (row: Omit<LogRow, 'seq' | 'sub' | 'raw'>) => {
    next.rows = [...next.rows, { ...row, seq, ...(pushed > 0 ? { sub: pushed } : {}), raw: event }]
    pushed += 1
  }

  switch (type) {
    case 'created': {
      next.slug = str(event.slug) || null
      next.jobId = num(event.job_id) || null
      next.tier = (str(event.tier) || null) as ExpertTier | null
      next.topic = str(event.topic) || null
      push({ kind: 'meta', stage: null, message: `Queued ${next.tier ?? ''} build`.trim() })
      return next
    }

    case 'build_started': {
      const attempt = num(event.attempt, 1)
      const max = num(event.max_attempts, 1)
      const resumedFrom = str(event.resumed_from) || null
      next.retrying = false
      if (attempt > 1 && !resumedFrom) {
        // A retry that starts from scratch runs `reset_build_state`, so what the
        // last attempt built — its sources, passages, graph and readiness — is
        // gone. Carrying it forward drew a timeline full of finished stages and
        // a live "Chat now" over an expert with nothing left to answer from.
        // The log rows stay: they are the history of why it retried.
        //
        // A retry carrying `resumed_from` is the opposite case: the worker kept
        // the corpus the last attempt reached and only re-runs what came after.
        const fresh = initialBuildState()
        next.stages = fresh.stages
        next.activeStage = null
        next.counts = fresh.counts
        next.chatReady = false
        next.graphReady = false
        next.readiness = fresh.readiness
        next.personaName = null
        next.keyConcepts = []
        next.degraded = []
        next.warnings = []
      }
      push({
        kind: 'meta',
        stage: null,
        message:
          attempt > 1
            ? `Build started (attempt ${attempt} of ${max}${
                resumedFrom ? `, resuming from ${resumedFrom.replace('_', ' ')}` : ''
              })`
            : 'Build started',
      })
      return next
    }

    case 'execution_mode': {
      const batched = event.batched === true
      push({
        kind: 'meta',
        stage: null,
        message: batched
          ? 'Running batched (half price, slower)'
          : `Running ${str(event.mode, 'interactive')}`,
      })
      return next
    }

    case 'stage': {
      const name = str(event.name) as StageName
      const segment = STAGE_SEGMENT[name]
      if (!segment) return next
      next.activeStage = segment
      const round = typeof event.round === 'number' ? ` · round ${event.round + 1}` : ''
      const detail =
        name === 'chunk'
          ? `${num(event.total)} sources`
          : name === 'validate'
            ? `${num(event.total)} sources`
            : name === 'graph'
              ? `${num(event.total_batches)} batches`
              : undefined
      next.stages = activate(state.stages, segment, detail)
      push({ kind: 'stage', stage: segment, message: `${STAGE_LABELS[name] ?? name}${round}` })
      return next
    }

    case 'plan_ready': {
      const concepts = Array.isArray(event.key_concepts) ? (event.key_concepts as string[]) : []
      next.keyConcepts = concepts
      next.stages = completeThrough(state.stages, 'plan')
      push({
        kind: 'ok',
        stage: 'plan',
        message: `Research plan ready — ${concepts.length} key concepts: ${concepts.join(', ')}`,
      })
      // Older builds carry no must-have works; the line is simply absent.
      const works = records(event.must_have_works)
        .map((work) => {
          const title = str(work.title)
          const author = str(work.author)
          return title ? (author ? `${title} (${author})` : title) : ''
        })
        .filter(Boolean)
      if (works.length > 0) {
        push({ kind: 'info', stage: 'plan', message: `Must-have works: ${works.join(', ')}` })
      }
      // Builds before concept primary texts carry neither; both lines are absent.
      const conceptTexts = records(event.concept_primary_texts).map(primaryTextLabel).filter(Boolean)
      if (conceptTexts.length > 0) {
        push({
          kind: 'info',
          stage: 'plan',
          message: `Primary texts per concept: ${conceptTexts.join(', ')}`,
        })
      }
      const definition = str(event.primary_source_definition).trim()
      if (definition) {
        push({ kind: 'info', stage: 'plan', message: `Primary sources here: ${definition}` })
      }
      return next
    }

    case 'discovery_started': {
      const active = Array.isArray(event.active) ? (event.active as string[]) : []
      push({
        kind: 'info',
        stage: 'discover',
        message: `Searching ${active.length} sources: ${active.join(', ')}`,
      })
      return next
    }

    case 'round_started': {
      push({
        kind: 'info',
        stage: 'discover',
        message: `Round ${num(event.round) + 1} — ${str(event.reason, 'searching again')}`,
      })
      return next
    }

    case 'fetcher_done': {
      const name = str(event.name)
      const label = num(event.attempt) >= 1 ? `${name} (retry)` : name
      const status = str(event.status)
      const skipped = event.skipped === true || status === 'skipped'
      const failure = FETCHER_FAILURES[status]
      // `error` is new; older builds put the same text in `reason`, if anywhere.
      const why = str(event.error) || str(event.reason)
      push({
        // Fetcher results fold into one collapsed group per round: eleven rows
        // of "n candidates" is the least interesting part of a build log.
        group: `fetchers:${num(event.round)}`,
        kind: skipped || failure ? 'warn' : 'info',
        stage: 'discover',
        message: skipped
          ? `${label} skipped — ${str(event.reason) || str(event.error) || 'nothing usable'}`
          : failure
            ? `${label}: ${failure}${why ? ` — ${why}` : ''}`
            : `${label}: ${num(event.count)} candidates from ${num(event.queries)} ${
                num(event.queries) === 1 ? 'query' : 'queries'
              }`,
      })
      return next
    }

    case 'fetcher_retried': {
      const after = str(event.after)
      const cause =
        after === 'rate_limited' ? 'being rate-limited' : after === 'timeout' ? 'a timeout' : 'a failure'
      push({
        group: `fetchers:${num(event.round)}`,
        kind: 'info',
        stage: 'discover',
        message: `Retrying ${str(event.name, 'a search')} after ${cause}`,
      })
      return next
    }

    case 'floor_relaxed': {
      push({
        kind: 'warn',
        stage: 'discover',
        message:
          `Few strong candidates (${num(event.reaching)} of ${num(event.needed)} needed scored ≥ ${num(event.floor)})` +
          ` — fetching down to ${num(event.relaxed_to)} this round`,
      })
      return next
    }

    case 'canonical_resolved': {
      // One line per must-have work, folded like the fetchers: the reader
      // opens the group to see which of the plan's canonical works were found.
      for (const work of records(event.works)) {
        push({
          group: `canonical:${num(event.round)}`,
          kind: 'info',
          stage: 'discover',
          message: canonicalMessage(work),
        })
      }
      return next
    }

    case 'primary_texts_suggested': {
      const texts = records(event.texts).map(primaryTextLabel).filter(Boolean)
      // With no texts named, the concepts alone still say what is being looked up.
      const named = texts.length > 0 ? texts : strings(event.concepts)
      if (named.length === 0) return next
      push({
        kind: 'info',
        stage: 'discover',
        message: `Looking up primary texts for concepts without one: ${named.join(', ')}`,
      })
      return next
    }

    case 'dedup_done': {
      const removed =
        num(event.by_identifier) + num(event.by_url) + num(event.already_seen)
      if (removed === 0) return next
      push({
        group: `fetchers:${num(event.round)}`,
        kind: 'info',
        stage: 'discover',
        message: `De-duplicated ${removed} candidates`,
      })
      return next
    }

    case 'triage_done': {
      next.counts = { ...state.counts, considered: state.counts.considered + num(event.candidates) }
      const unscored = num(event.unscored)
      push({
        kind: 'info',
        stage: 'discover',
        message:
          `Triaged ${num(event.candidates)} candidates, ranked ${num(event.ranked)} for a budget of ${num(event.budget)}` +
          (typeof event.above_floor === 'number' ? `, ${event.above_floor} above the fetch floor` : '') +
          (unscored > 0 ? `; ${unscored} could not be scored and were not fetched` : ''),
      })
      return next
    }

    case 'fetch_progress': {
      // One row per download would drown the log; the stage detail carries it.
      next.stages = markStage(
        state.stages,
        'discover',
        'active',
        `fetched ${num(event.fetched)} of ${num(event.budget)}`,
      )
      return next
    }

    case 'fetch_done': {
      const dupes = num(event.content_duplicates)
      const outcomes =
        typeof event.outcomes === 'object' && event.outcomes !== null
          ? (event.outcomes as Record<string, unknown>)
          : {}
      const failed = num(outcomes.failed)
      const notEnglish = num(outcomes.not_english)
      push({
        kind: 'info',
        stage: 'discover',
        message:
          `Retrieved full text for ${num(event.fetched)} sources` +
          (dupes ? `, ${dupes} dropped as duplicates` : '') +
          (failed ? `, ${failed} could not be downloaded` : '') +
          (notEnglish ? `, ${notEnglish} not in English` : ''),
      })
      return next
    }

    case 'source_validated':
    case 'source_reviewed': {
      const passed = event.passed === true
      const title = str(event.title, 'Untitled source')
      const reviewed = type === 'source_reviewed'
      const reason = str(event.drop_reason) || (passed ? '' : 'below threshold')
      next.counts = {
        ...state.counts,
        kept: state.counts.kept + (passed && !reviewed ? 1 : 0),
        dropped: state.counts.dropped + (!passed && !reviewed ? 1 : 0),
      }
      push({
        kind: passed ? 'keep' : 'drop',
        stage: 'validate',
        message:
          `${title}${reviewed ? ' (reviewed' + (event.reversed ? ', reversed' : '') + ')' : ''}` +
          (passed ? '' : ` — ${reason}`),
      })
      return next
    }

    case 'composition_capped': {
      const dropped = records(event.dropped)
      if (dropped.length === 0) return next
      push({
        kind: 'info',
        stage: 'validate',
        message: `Dropped ${dropped.length} ${
          dropped.length === 1 ? 'source' : 'sources'
        } over the abstract-only / tertiary share`,
      })
      return next
    }

    case 'validate_done': {
      next.stages = completeThrough(state.stages, 'validate')
      const capped = num(event.capped)
      push({
        kind: 'info',
        stage: 'validate',
        message:
          `Screening done — kept ${num(event.passed)}, dropped ${num(event.dropped)}` +
          (capped ? ` (${capped} over the composition caps)` : ''),
      })
      return next
    }

    case 'coverage_report': {
      const concepts = Array.isArray(event.concepts) ? (event.concepts as unknown[]) : []
      const short = concepts.filter(
        (c) => typeof c === 'object' && c !== null && (c as { met?: boolean }).met === false,
      ).length
      push({
        kind: short ? 'warn' : 'ok',
        stage: 'discover',
        message: short
          ? `Coverage: ${short} of ${concepts.length} concepts still short`
          : `Coverage: every concept met its target`,
      })
      return next
    }

    case 'feedback_queries': {
      const queries = Array.isArray(event.queries) ? (event.queries as string[]) : []
      const withoutPrimary = strings(event.without_primary)
      push({
        kind: 'info',
        stage: 'discover',
        message:
          `New queries from the corpus: ${queries.slice(0, 3).join(' · ')}${
            queries.length > 3 ? ` (+${queries.length - 3})` : ''
          }` +
          (withoutPrimary.length > 0
            ? ` — no primary source yet for ${withoutPrimary.join(', ')}`
            : ''),
      })
      return next
    }

    case 'snowball_done': {
      push({
        kind: 'info',
        stage: 'discover',
        message: `Followed citations — ${num(event.candidates)} new candidates`,
      })
      return next
    }

    case 'discovery_done': {
      const reason = str(event.stop_reason, 'stopped')
      // The builder's `DiscoveryOutcome.summary()` names this `rounds`.
      const rounds = num(event.rounds)
      next.stages = completeThrough(state.stages, 'discover')
      push({
        kind: reason === 'targets_met' ? 'ok' : 'warn',
        stage: 'discover',
        message:
          reason === 'targets_met'
            ? `Search met its coverage targets after ${rounds} ${rounds === 1 ? 'round' : 'rounds'}`
            : `Search stopped: ${reason.replace(/_/g, ' ')}`,
      })
      // A channel that failed is why a corpus can be thin in one direction
      // (no primary texts when Gutenberg timed out); say so once, at the end.
      const failedChannels =
        typeof event.failed_channels === 'object' && event.failed_channels !== null
          ? Object.entries(event.failed_channels as Record<string, unknown>)
          : []
      if (failedChannels.length > 0) {
        push({
          kind: 'warn',
          stage: 'discover',
          message: `Searches that failed: ${failedChannels
            .map(([name, status]) => `${name} (${describeChannelStatus(str(status))})`)
            .join(', ')}`,
        })
      }
      return next
    }

    case 'source_ingested': {
      next.counts = { ...state.counts, chunks: num(event.total_chunks, state.counts.chunks) }
      next.stages = markStage(
        state.stages,
        'chunk',
        'active',
        `${num(event.total_chunks)} passages`,
      )
      push({
        group: 'ingest',
        kind: 'info',
        stage: 'chunk',
        message: `${str(event.title, 'Source')} → ${num(event.chunks)} passages`,
      })
      return next
    }

    case 'chat_ready': {
      next.chatReady = true
      next.readiness = 'chat_ready'
      next.stages = completeThrough(state.stages, 'chunk')
      push({
        kind: 'ok',
        stage: 'chunk',
        message: `Chat ready — ${num(event.sources)} sources, ${num(event.chunks)} passages`,
      })
      return next
    }

    case 'graph_batch_done': {
      const labels = Array.isArray(event.labels) ? (event.labels as string[]) : []
      push({
        group: 'graph',
        kind: 'info',
        stage: 'graph',
        message: `${labels.length} concepts, ${num(event.edges)} links`,
      })
      return next
    }

    case 'entities_resolved': {
      push({
        kind: 'info',
        stage: 'graph',
        message: `Merged ${num(event.merged)} duplicate concepts`,
      })
      return next
    }

    case 'resolve_progress': {
      next.stages = markStage(state.stages, 'graph', 'active', `merging (${num(event.merged)})`)
      return next
    }

    case 'claims_reconciled': {
      // Emitted on every pass, including one that inserts nothing, so the log
      // can tell "found no relationships" from "its comparisons failed".
      const failed = num(event.calls_failed)
      const examined = num(event.concepts_examined)
      push({
        kind: failed > 0 && failed === examined ? 'warn' : 'info',
        stage: 'graph',
        message:
          `Reconciled claims across ${num(event.concepts)} concepts — ${num(event.relations)} relationships` +
          (failed > 0 ? ` (${failed} of ${examined} comparisons failed)` : ''),
      })
      return next
    }

    case 'graph_ready': {
      next.graphReady = true
      next.readiness = 'graph_ready'
      next.stages = completeThrough(state.stages, 'graph')
      push({
        kind: 'ok',
        stage: 'graph',
        message: `Graph ready — ${num(event.nodes)} concepts, ${num(event.edges)} links`,
      })
      return next
    }

    case 'persona_ready': {
      next.personaName = str(event.name) || null
      next.stages = completeThrough(state.stages, 'persona')
      push({ kind: 'ok', stage: 'persona', message: `Voice written — ${next.personaName}` })
      return next
    }

    case 'picture_ready': {
      // Not a stage: finding a picture runs beside discovery, off `plan_ready`,
      // and cannot fail or delay the build. It gets a log line and nothing on
      // the timeline, because there is no segment it belongs to.
      const title = str(event.title)
      const license = str(event.license)
      push({
        kind: 'ok',
        stage: null,
        message: title
          ? `Picture found — ${title}${license ? ` (${license})` : ''}`
          : 'Picture found',
      })
      return next
    }

    case 'picture_skipped': {
      // Quiet on purpose. No picture is not a degradation — the expert shows
      // its monogram, which is what every expert looked like before — so this
      // is `meta`, not `warn`, and it names the reason so the log can say why.
      const reason = str(event.reason, 'none found')
      push({
        kind: 'meta',
        stage: null,
        message: `No picture — ${PICTURE_SKIP_REASONS[reason] ?? reason}`,
      })
      return next
    }

    case 'stage_degraded': {
      const stage = str(event.stage)
      const message = str(event.message)
      next.degraded = [...state.degraded, { stage, message }]
      const segment = STAGE_SEGMENT[stage]
      if (segment) next.stages = markStage(state.stages, segment, 'degraded')
      push({ kind: 'warn', stage: segment ?? null, message })
      return next
    }

    case 'corpus_warning': {
      const message = str(event.message) || str(event.warning)
      next.warnings = [...state.warnings, message]
      push({ kind: 'warn', stage: state.activeStage, message })
      return next
    }

    case 'retry': {
      const entry = {
        attempt: num(event.attempt),
        maxAttempts: num(event.max_attempts),
        message: str(event.message),
      }
      next.retries = [...state.retries, entry]
      next.retrying = true
      push({
        kind: 'warn',
        stage: null,
        message: `Attempt ${entry.attempt} of ${entry.maxAttempts} failed — retrying. ${entry.message}`,
      })
      return next
    }

    case 'done': {
      const persona = str(event.persona_name) || next.personaName
      next.personaName = persona || null
      next.terminal = {
        kind: 'done',
        message: persona
          ? `${persona} is ready — ${num(event.source_count)} sources, ${num(event.chunk_count)} passages`
          : `Build finished — ${num(event.source_count)} sources, ${num(event.chunk_count)} passages`,
      }
      next.stages = state.stages.map((s) =>
        s.status === 'degraded' ? s : { ...s, progress: 1, status: 'done' },
      )
      next.activeStage = null
      push({ kind: 'ok', stage: null, message: next.terminal.message })
      return next
    }

    case 'error': {
      const message = str(event.message, 'The build failed.')
      const code = str(event.code) || undefined
      next.terminal = { kind: 'error', message, code, capped: code === 'spend_cap_exceeded' }
      if (state.activeStage) next.stages = markStage(state.stages, state.activeStage, 'failed')
      next.activeStage = null
      push({ kind: 'bad', stage: null, message })
      return next
    }

    case 'cancelled': {
      const message = str(event.message, 'Build cancelled.')
      next.terminal = { kind: 'cancelled', message }
      next.activeStage = null
      push({ kind: 'warn', stage: null, message })
      return next
    }

    default:
      // An event this build of the web app has never heard of. Ignored on
      // purpose — see the module docstring.
      return next.lastSeq === state.lastSeq ? state : next
  }
}

/** The fetcher statuses that are failures, as the log phrases them. */
const FETCHER_FAILURES: Record<string, string> = Object.fromEntries(
  ['timeout', 'rate_limited', 'error'].map((status) => [status, describeChannelStatus(status)]),
)

/** "Summa Theologiae I-II qq. 90–97 (natural law)": title, sections when named, concept. */
function primaryTextLabel(text: Record<string, unknown>): string {
  const title = str(text.title).trim()
  if (!title) return ''
  const sections = str(text.sections).trim()
  const concept = str(text.concept).trim()
  return `${title}${sections ? ` ${sections}` : ''}${concept ? ` (${concept})` : ''}`
}

/**
 * "Summa Theologiae: whole text found (internet_archive)", and for a concept's
 * primary text "Summa Theologiae (for natural law): only parts found (gutenberg)".
 */
function canonicalMessage(work: Record<string, unknown>): string {
  const concepts = work.scope === 'concept' ? strings(work.concepts) : []
  const title =
    str(work.title, 'Untitled work') + (concepts.length ? ` (for ${concepts.join(', ')})` : '')
  const candidates = records(work.candidates)
  const routesFor = (extent: string) => [
    ...new Set(
      candidates
        .filter((candidate) => candidate.extent === extent)
        .map((candidate) => str(candidate.route))
        .filter(Boolean),
    ),
  ]
  const whole = routesFor('whole')
  if (candidates.some((candidate) => candidate.extent === 'whole')) {
    return `${title}: whole text found${whole.length ? ` (${whole.join(', ')})` : ''}`
  }
  if (candidates.length > 0) {
    const partial = [
      ...new Set(candidates.map((candidate) => str(candidate.route)).filter(Boolean)),
    ]
    return `${title}: only parts found${partial.length ? ` (${partial.join(', ')})` : ''}`
  }
  const tried = strings(work.routes_tried)
  return `${title}: not found${tried.length ? ` (tried ${tried.join(', ')})` : ''}`
}

/** What each `picture_skipped` reason means in the build log. */
const PICTURE_SKIP_REASONS: Record<string, string> = {
  no_candidate: 'no freely licensed picture of this subject',
  provider_unavailable: 'Wikimedia was unreachable',
  timeout: 'the search ran out of time',
  too_large: 'the pictures found were too large',
  disabled: 'picture search is off on this server',
}

const STAGE_LABELS: Record<string, string> = {
  ...STAGE_LABEL,
  resolve: `${STAGE_LABEL.graph} · merging duplicates`,
  reconcile: `${STAGE_LABEL.graph} · reconciling claims`,
}

export function isTerminalEvent(event: BuildEvent): boolean {
  return TERMINAL_BUILD_EVENTS.has(event.type)
}

/** Apply a whole batch, for replaying a fixture or a reconnect backlog. */
export function reduceAll(
  state: BuildState,
  events: { seq: number; event: BuildEvent }[],
): BuildState {
  return events.reduce((acc, { seq, event }) => reduceBuildEvent(acc, seq, event), state)
}

/**
 * Collapse consecutive rows that share a `group` into one summary row.
 *
 * Groups exist so a 3,000-row log stays scannable: eleven fetcher rows and 400
 * ingest rows each become one line the reader can open. Non-grouped rows pass
 * through untouched.
 */
export interface RowGroup {
  key: string
  /** Null for a plain row. */
  group: string | null
  rows: LogRow[]
}

export function groupRows(rows: LogRow[]): RowGroup[] {
  const out: RowGroup[] = []
  for (const row of rows) {
    const last = out[out.length - 1]
    if (row.group && last && last.group === row.group) {
      last.rows.push(row)
      continue
    }
    out.push({ key: rowKey(row), group: row.group ?? null, rows: [row] })
  }
  return out
}

/** The stable React key of a log row: its event's `seq`, plus its place in that event. */
export function rowKey(row: Pick<LogRow, 'seq' | 'sub'>): string {
  return row.sub ? `${row.seq}.${row.sub}` : `${row.seq}`
}
