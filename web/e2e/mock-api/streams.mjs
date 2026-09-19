import { frame, json, sleep, sseHead } from './http.mjs'
import { fixture, state } from './state.mjs'

/**
 * The two SSE streams, which are the whole reason this server is hand-written.
 *
 * A build log and a chat answer both arrive as `text/event-stream` with real
 * `id:` cursors, and the two behaviours most worth testing in a browser are
 * only observable against a real stream: **resuming from a cursor** after an
 * abandoned connection, and the client's once-per-frame token batching. A
 * static response exercises neither.
 *
 * `state.scenario` is how a test asks for the unhappy paths — a connection
 * dropped mid-build, a build that fails, a cap exceeded — none of which a real
 * backend can be asked for on demand.
 */

/** The event sequence a build replays, in order, from the fixtures. */
export async function buildScript() {
  const events = await fixture('build-events')
  const order = [
    'created',
    'build_started',
    'execution_mode',
    'stage_plan',
    'plan_ready',
    'picture_ready',
    'discovery_started',
    'canonical_resolved',
    'fetcher_done',
    'fetcher_skipped',
    'fetcher_timeout',
    'fetcher_retried',
    'fetcher_retry_ok',
    'dedup_done',
    'floor_relaxed',
    'triage_done',
    'fetch_done',
    'stage_validate',
    'source_validated_keep',
    'source_validated_drop',
    'source_reviewed',
    'validate_done',
    'coverage_report',
    'primary_texts_suggested',
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
  ]
  return order.map((name) => events[name])
}

/**
 * The same build, grown in full: a plan with facets and named texts, candidates
 * judged, ten sources placed on the orbit one by one, and extraction reading
 * them — every field the brain growing needs (expert-brain-interactive.md, G0).
 * Only under the `grow` scenario, so the counts other specs assert on stand.
 */
export async function growScript() {
  const base = await buildScript()
  const map = await fixture('map')
  const keyConcepts = map.syllabus.key_concepts.map((k) => k.label)
  const out = []
  for (const event of base) {
    if (event.type === 'plan_ready') {
      out.push({
        ...event,
        key_concepts: keyConcepts,
        facets: (map.syllabus.facets ?? []).map((f) => ({
          name: f.name,
          concepts: f.concepts.map((i) => keyConcepts[i]),
        })),
        concept_primary_texts: [
          {
            concept: keyConcepts[4],
            title: 'Tools for Varroa Management',
            author: 'Honey Bee Health Coalition',
          },
          {
            concept: keyConcepts[1],
            title: 'Amitraz resistance in field populations',
            author: 'Okonkwo, A.',
          },
        ],
        must_have_works: [{ title: 'The Biology of the Honey Bee', author: 'Mark L. Winston' }],
      })
    } else if (event.type === 'source_validated') {
      for (let i = 0; i < 8; i += 1) {
        out.push({ ...event, title: `Candidate ${i}`, passed: i % 3 !== 0 })
      }
    } else if (event.type === 'source_ingested') {
      let total = 0
      for (const source of map.sources) {
        total += source.passage_count
        out.push({
          type: 'source_ingested',
          title: source.title,
          chunks: source.passage_count,
          total_chunks: total,
          source_id: source.id,
          tier: source.tier,
          kind: source.kind,
          tags: source.tags,
        })
      }
    } else if (event.type === 'graph_batch_done') {
      for (let i = 0; i < map.sources.length; i += 3) {
        out.push({
          ...event,
          source_ids: map.sources.slice(i, i + 3).map((s) => s.id),
        })
      }
    } else {
      out.push(event)
    }
  }
  return out
}

/**
 * Register a build for a slug, without starting it.
 *
 * The events are materialised up front so a reconnect with `after=<seq>` is
 * served from the same array a first connection was reading — which is the
 * whole point of the log being durable server-side.
 */
export async function startBuild(slug, topic) {
  const script = state.scenario === 'grow' ? await growScript() : await buildScript()
  const created = { ...script[0], slug, topic: topic ?? slug }
  const events = [created, ...script.slice(1)]
  state.builds.set(slug, { events, delivered: 0, jobId: created.job_id })
  return created
}

/**
 * Stream from `after`, appending as the script "progresses".
 *
 * `resumable` is true only for `GET …/build/events`, which is the stream a
 * client reconnects on. The `drop-midway` scenario fires only there: the POST
 * response is abandoned the moment the composer navigates, so dropping *that*
 * would test nothing — the client is already gone.
 */
export async function streamBuild(req, res, slug, after, resumable = false) {
  const build = state.builds.get(slug)
  if (!build) return json(res, 404, { detail: 'No build job for this expert' })

  sseHead(res)
  let closed = false
  req.on('close', () => {
    closed = true
  })

  for (let index = after; index < build.events.length; index += 1) {
    if (closed) return
    /**
     * Abandon a stream whose build has been replaced by a `__reset`.
     *
     * Home tails the seeded in-progress build, and that tail is held open by
     * the *Next server*, not by the browser — so it can outlive the test that
     * opened it by a moment. When it did, it walked on to its `done` event and
     * flipped the freshly re-seeded "still building" expert to ready
     * underneath the next test, which then failed looking for the pending
     * state. Identity, not the slug: after a reset the map holds a new record.
     */
    if (state.builds.get(slug) !== build) return
    const event = build.events[index]
    // Sequence numbers are 1-based, matching the API's `seq`.
    frame(res, index + 1, event)
    build.delivered = Math.max(build.delivered, index + 1)

    if (event.type === 'done' || event.type === 'error' || event.type === 'cancelled') {
      // A terminal event ends the tail, and the expert becomes ready.
      const expert = state.experts.get(slug)
      if (expert && event.type === 'done') {
        Object.assign(expert, {
          status: 'ready',
          readiness: 'graph_ready',
          graph_expanded: true,
          persona_name: event.persona_name,
          source_count: event.source_count,
          chunk_count: event.chunk_count,
          node_count: event.node_count,
          edge_count: event.edge_count,
          avg_quality: event.avg_quality,
        })
      }
      res.end()
      return
    }

    if (event.type === 'chat_ready') {
      const expert = state.experts.get(slug)
      if (expert) Object.assign(expert, { readiness: 'chat_ready', status: 'building' })
    }

    // Fast enough that a test does not wait, slow enough that the log visibly
    // streams rather than arriving as one chunk.
    //
    // `slow-build` is for the test that cancels one. At 60ms an event the whole
    // script is over in under four seconds, and a slow runner can spend that
    // getting a single press heard — after which there is no build left to
    // cancel, and the failure reads as a missing Cancel button.
    const slow =
      state.scenario === 'slow-build' &&
      (state.scenarioSlug === null || state.scenarioSlug === slug)
    await sleep(slow ? 600 : Number(process.env.MOCK_BUILD_INTERVAL_MS || 60))

    // The scenario that matters most: the connection dies mid-build and the
    // client has to resume from its cursor.
    if (
      resumable &&
      state.scenario === 'drop-midway' &&
      (state.scenarioSlug === null || state.scenarioSlug === slug) &&
      index === 12
    ) {
      res.destroy()
      // One shot: the reconnect must then succeed.
      state.scenario = 'happy'
      state.scenarioSlug = null
      return
    }
  }
  res.end()
}

// ── the chat stream ──

export async function streamChat(req, res, conversationId, question) {
  const conversation = state.conversations.get(conversationId)
  if (!conversation) return json(res, 404, { detail: 'Conversation not found' })
  if (state.scenario === 'chat-busy') {
    state.scenario = 'happy'
    return json(res, 409, { detail: 'An answer is already streaming' })
  }

  const events = await fixture('chat-events')
  sseHead(res)
  let closed = false
  req.on('close', () => {
    closed = true
  })

  let seq = 0
  const send = (payload) => frame(res, (seq += 1), payload)

  send({ ...events.meta, conversation_id: conversationId })
  for (const status of ['status_planning', 'status_searching', 'status_composing']) {
    if (closed) return
    send(events[status])
    await sleep(40)
  }

  // Many small token events, which is what exercises the per-frame batching.
  const answer =
    'Drone brood removal reduces mite load substantially on its own, but the evidence does not ' +
    'support it as a sole control in high-pressure years [1].\n\n' +
    'A randomised trial measured a 43% reduction relative to untreated controls [1]. A five-year ' +
    'cohort found that mechanical control alone did not prevent viral amplification when mite ' +
    'pressure was high [3]. Nothing in this corpus supports [7].'
  for (const word of answer.split(/(?<=\s)/)) {
    if (closed) return
    send({ type: 'token', text: word })
    await sleep(Number(process.env.MOCK_TOKEN_INTERVAL_MS || 8))
  }

  send(events.sources)
  send(events.retrieval_audit)
  send(events.done)

  conversation.messages.push(
    {
      id: conversation.messages.length + 1,
      role: 'user',
      content: question,
      citations: null,
      has_contradiction: false,
      interrupted: false,
      created_at: new Date().toISOString(),
    },
    {
      id: conversation.messages.length + 2,
      role: 'assistant',
      content: answer,
      citations: events.sources.citations,
      has_contradiction: true,
      interrupted: false,
      created_at: new Date().toISOString(),
    }
  )
  conversation.message_count = conversation.messages.length
  conversation.last_message_at = new Date().toISOString()
  if (!conversation.title) conversation.title = question.slice(0, 60)
  res.end()
}
