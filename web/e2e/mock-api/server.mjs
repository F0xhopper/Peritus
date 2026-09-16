import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

/**
 * A stand-in for FastAPI, serving the captured fixtures.
 *
 * The e2e suite needs a backend that is deterministic, offline, and cheap — a
 * real build costs money and takes minutes, so it can never be what CI runs
 * against. This server answers the same endpoints with the same shapes the
 * fixtures pin, and it **streams the build and chat logs as real SSE** with
 * real `id:` cursors, because the reconnect-from-cursor behaviour and the
 * once-per-frame token batching are the two things most worth testing in a
 * browser and neither is observable against a static response.
 *
 * Deliberately hand-written rather than msw-behind-a-listener: SSE, an
 * abandoned connection resumed from a cursor, and a multipart upload are
 * exactly the cases a request-mocking library makes awkward.
 */

const PORT = Number(process.env.MOCK_API_PORT || 8787)
const FIXTURES = fileURLToPath(new URL('../../tests/fixtures/', import.meta.url))

async function fixture(name) {
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
function bigGraph(base) {
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

const state = {
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

function json(res, status, body, headers = {}) {
  const payload = JSON.stringify(body)
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(payload),
    ...headers,
  })
  res.end(payload)
}

function noContent(res) {
  res.writeHead(204)
  res.end()
}

function sseHead(res) {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  })
}

/** One frame, CRLF-terminated as sse-starlette emits. */
function frame(res, seq, payload) {
  res.write(`id: ${seq}\r\ndata: ${JSON.stringify(payload)}\r\n\r\n`)
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * The bytes served at `/experts/:slug/picture`.
 *
 * A real 1x1 PNG, built here rather than checked in: the e2e assertions are
 * about *which element renders and where its src points*, not about what the
 * image depicts, and a binary fixture in the repo would be one more thing to
 * keep in step with nothing.
 */
const PICTURE_BYTES = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64'
)
const PICTURE_SHA = 'f1e2d3c4b5a6'

/** The seeded expert that has one. */
const PICTURE_SLUG = 'stoic-philosophy'

/** What the API returns on every expert that has one. */
function pictureMeta() {
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

// ── seeding ─────────────────────────────────────────────────────────────────

/** The live link to the seeded foreign expert. 32+ URL-safe characters, like a real token. */
const FOREIGN_TOKEN = 'mockSharedTokenForTheThomismExpert01'
const FOREIGN_SLUG = 'thomism'

async function seed() {
  const expert = await fixture('expert')
  // Deliberately picture-less: this is the expert most specs act on, and its
  // monogram is what the derived-identity assertions are about. The one with a
  // found picture is seeded below, so both branches of the avatar resolver are
  // on screen in every run.
  expert.picture = null
  state.experts.set(expert.name, expert)

  // A second expert that is mid-build, so the rail's pulse, the Building-now
  // card and the pending-readiness chat gate all have something to render.
  state.experts.set('measurement-error-in-nutritional-epidemiology', {
    ...expert,
    id: 42,
    name: 'measurement-error-in-nutritional-epidemiology',
    topic: 'Measurement error in nutritional epidemiology',
    status: 'building',
    readiness: 'pending',
    graph_expanded: false,
    persona_name: null,
    persona_bio: null,
    persona_style: null,
    avg_quality: null,
    source_count: 0,
    chunk_count: 0,
    node_count: 0,
    edge_count: 0,
    source_type_counts: {},
    avatar: null,
    picture: null,
  })

  // A third expert that arrived with a found picture of its subject — the
  // default a freshly built expert now has. Separate from the two above so the
  // monogram assertions stay about the monogram and this one stays about the
  // picture, in the same run.
  state.experts.set(PICTURE_SLUG, {
    ...expert,
    id: 43,
    name: PICTURE_SLUG,
    topic: 'Stoic philosophy',
    persona_name: 'Dr. Aurelia Vance',
    persona_bio: 'A historian of Hellenistic philosophy who reads the Stoics in Greek.',
    persona_style: 'plain, quotes the sources, refuses the self-help reading',
    avatar: null,
    picture: pictureMeta(),
  })

  // A real expert with status 'building' always has a build job behind it, so
  // the seeded one gets a registered (un-streamed) build. Without it the
  // Overview would offer "start a build" for something already building.
  await startBuild('measurement-error-in-nutritional-epidemiology', 'Measurement error')

  const conversation = {
    id: '2f2b8a4e-1c9d-4f8a-9b1e-7c0d2a5f6e31',
    expert_id: expert.id,
    expert_slug: expert.name,
    expert_topic: expert.topic,
    expert_persona_name: expert.persona_name,
    expert_status: expert.status,
    expert_picture_version: null,
    title: 'How effective is drone brood removal on its own?',
    message_count: 2,
    created_at: '2026-09-09T09:00:00.000Z',
    last_message_at: '2026-09-09T09:01:12.000Z',
    messages: [
      {
        id: 1,
        role: 'user',
        content: 'How effective is drone brood removal on its own?',
        citations: null,
        has_contradiction: false,
        interrupted: false,
        created_at: '2026-09-09T09:00:00.000Z',
      },
      {
        id: 2,
        role: 'assistant',
        content:
          'Drone brood removal reduces mite load substantially on its own, but the evidence does not support it as a sole control in high-pressure years [1].\n\nA randomised trial measured a 43% reduction relative to untreated controls over one season [1]. A five-year cohort found that mechanical control alone did not prevent viral amplification when mite pressure was high [3].',
        citations: [
          {
            n: 1,
            label:
              'Drone brood removal as mechanical control: a randomised trial — removal reduced mite load by 43% relative to untreated controls over one season.',
            source_id: 812,
          },
          {
            n: 3,
            label:
              'Varroa destructor and honeybee viral loads: a five-year cohort — mechanical control alone did not prevent viral amplification in high-pressure years.',
            source_id: 804,
          },
        ],
        has_contradiction: true,
        interrupted: false,
        created_at: '2026-09-09T09:01:12.000Z',
      },
    ],
  }
  state.conversations.set(conversation.id, conversation)

  // Someone else's expert with a live share link. Not in the workspace until the
  // test opens the link, exactly like the real read rule.
  state.foreign = {
    ...expert,
    id: 77,
    name: FOREIGN_SLUG,
    topic: 'Thomism',
    persona_name: 'Fr. Reginald Hale',
    persona_bio: 'A Dominican who reads the Summa slowly and argues with its commentators.',
    persona_style: 'patient, cites article and objection, distinguishes before answering',
    avatar: null,
    picture: pictureMeta(),
    access: 'viewer',
  }
  state.links.set('__foreign__', { token: FOREIGN_TOKEN, viewers: 0 })
}

function newToken() {
  return Array.from(
    { length: 32 },
    () =>
      'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-'[
        Math.floor(Math.random() * 64)
      ]
  ).join('')
}

function shareState(slug) {
  const link = state.links.get(slug)
  return {
    enabled: Boolean(link),
    token: link?.token ?? null,
    created_at: link ? '2026-09-15T10:00:00.000Z' : null,
    viewer_count: link?.viewers ?? 0,
    // The seeded expert has one upload, so the dialog's warning has something to say.
    uploaded_source_count: slug === 'varroa-mite-control-in-temperate-beekeeping' ? 1 : 0,
  }
}

/** The anonymous card: no slug, no id, no owner, no error. */
function sharedCard(expert) {
  const {
    id: _id,
    name: _name,
    status: _status,
    error: _error,
    updated_at: _updated,
    catalog: _catalog,
    access: _access,
    persona_style: _style,
    edge_count: _edges,
    ...card
  } = expert
  return card
}

// ── the build stream ────────────────────────────────────────────────────────

/** The event sequence a build replays, in order, from the fixtures. */
async function buildScript() {
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
 * Register a build for a slug, without starting it.
 *
 * The events are materialised up front so a reconnect with `after=<seq>` is
 * served from the same array a first connection was reading — which is the
 * whole point of the log being durable server-side.
 */
async function startBuild(slug, topic) {
  const script = await buildScript()
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
async function streamBuild(req, res, slug, after, resumable = false) {
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
    await sleep(Number(process.env.MOCK_BUILD_INTERVAL_MS || 60))

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

// ── the chat stream ─────────────────────────────────────────────────────────

async function streamChat(req, res, conversationId, question) {
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

// ── routing ─────────────────────────────────────────────────────────────────

async function body(req) {
  const chunks = []
  for await (const chunk of req) chunks.push(chunk)
  return Buffer.concat(chunks)
}

async function handle(req, res) {
  const url = new URL(req.url, 'http://mock')
  const path = url.pathname
  const method = req.method ?? 'GET'

  // A hook for the tests to pick a scenario before acting.
  if (path === '/__scenario' && method === 'POST') {
    const raw = JSON.parse((await body(req)).toString() || '{}')
    state.scenario = raw.scenario ?? 'happy'
    state.scenarioSlug = raw.slug ?? null
    return json(res, 200, { scenario: state.scenario, slug: state.scenarioSlug })
  }
  if (path === '/__reset' && method === 'POST') {
    state.experts.clear()
    state.builds.clear()
    state.conversations.clear()
    state.links.clear()
    state.foreign = null
    state.scenario = 'happy'
    state.scenarioSlug = null
    await seed()
    return json(res, 200, { ok: true })
  }

  // ── auth ──
  if (path === '/auth/status') {
    return json(res, 200, { auth_enabled: true, login_available: true })
  }
  if (path === '/auth/otp' && method === 'POST') {
    const email = JSON.parse((await body(req)).toString()).email
    if (String(email).includes('ratelimited')) {
      return json(res, 429, { detail: 'Too many requests' }, { 'Retry-After': '30' })
    }
    if (String(email).includes('unknown')) {
      return json(res, 400, { detail: 'Signups are disabled on this server.' })
    }
    return noContent(res)
  }
  if (path === '/auth/verify' && method === 'POST') {
    const { email, token } = JSON.parse((await body(req)).toString())
    // One fixed code, so the test is deterministic.
    if (token !== '123456') return json(res, 400, { detail: 'Invalid or expired code' })
    return json(res, 200, session(email))
  }
  if (path === '/auth/refresh' && method === 'POST') {
    const { refresh_token: refresh } = JSON.parse((await body(req)).toString())
    if (refresh !== 'mock-refresh') return json(res, 401, { detail: 'Invalid refresh token' })
    return json(res, 200, session('tester@example.com'))
  }
  if (path === '/auth/logout' && method === 'POST') return noContent(res)
  if (path === '/auth/me') {
    return json(res, 200, {
      id: '11111111-1111-1111-1111-111111111111',
      email: 'tester@example.com',
      is_admin: true,
    })
  }
  if (path === '/auth/oauth/authorize') {
    // Straight back to the callback with a code, so the PKCE round trip is
    // exercised without a real provider.
    const redirect = url.searchParams.get('redirect_to')
    return json(res, 200, { url: `${redirect}?code=mock-auth-code` })
  }
  if (path === '/auth/oauth/exchange' && method === 'POST') {
    const { auth_code: code, code_verifier: verifier } = JSON.parse((await body(req)).toString())
    if (code !== 'mock-auth-code') return json(res, 400, { detail: 'Bad code' })
    // The length bound the real API enforces (RFC 7636 §4.1).
    if (!verifier || verifier.length < 43 || verifier.length > 128) {
      return json(res, 422, { detail: 'code_verifier out of range' })
    }
    return json(res, 200, session('tester@example.com'))
  }

  // ── billing ──
  if (path === '/billing/me') return json(res, 200, await fixture('billing'))
  if (path === '/billing/ledger') {
    return json(res, 200, [
      {
        id: 2,
        entry_type: 'hold',
        delta: -3,
        job_id: 118,
        tier: 'standard',
        reason: 'Build hold',
        source: 'build',
        cost_usd: 1.62,
        created_at: '2026-09-08T12:14:02.118Z',
      },
      {
        id: 1,
        entry_type: 'grant',
        delta: 3,
        job_id: null,
        tier: null,
        reason: 'Signup grant',
        source: 'system',
        cost_usd: null,
        created_at: '2026-09-01T09:00:00.000Z',
      },
    ])
  }
  if (path === '/admin/credits/grant' && method === 'POST') {
    const { owner, amount } = JSON.parse((await body(req)).toString())
    return json(res, 200, {
      owner_id: '11111111-1111-1111-1111-111111111111',
      balance: 2 + amount,
      granted: amount,
      owner,
    })
  }

  // ── share links (anyone holding one) ──
  const shareMatch = /^\/share\/([^/]+)(\/picture|\/accept)?$/.exec(path)
  if (shareMatch) {
    const token = decodeURIComponent(shareMatch[1])
    const foreignLink = state.links.get('__foreign__')
    const ownSlug = [...state.links.entries()].find(
      ([slug, link]) => slug !== '__foreign__' && link.token === token
    )?.[0]
    const expert =
      foreignLink?.token === token ? state.foreign : ownSlug ? state.experts.get(ownSlug) : null
    if (!expert) return json(res, 404, { detail: 'This link is not active' })
    const noStore = { 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex, nofollow' }

    if (!shareMatch[2] && method === 'GET') return json(res, 200, sharedCard(expert), noStore)
    if (shareMatch[2] === '/picture' && method === 'GET') {
      if (!expert.picture) return json(res, 404, { detail: 'This expert has no picture' })
      res.writeHead(200, {
        'Content-Type': 'image/png',
        'Content-Length': PICTURE_BYTES.length,
        ...noStore,
      })
      return res.end(PICTURE_BYTES)
    }
    if (shareMatch[2] === '/accept' && method === 'POST') {
      if (expert === state.foreign) {
        foreignLink.viewers += 1
        state.experts.set(expert.name, expert)
        return json(res, 200, { slug: expert.name, access: 'viewer' })
      }
      return json(res, 200, { slug: expert.name, access: 'owner' })
    }
  }

  // ── experts ──
  if (path === '/experts' && method === 'GET') {
    return json(res, 200, [...state.experts.values()])
  }
  if (path === '/experts/build' && method === 'POST') {
    const { topic, tier } = JSON.parse((await body(req)).toString())
    if (state.scenario === 'insufficient-credits') {
      state.scenario = 'happy'
      const denials = await fixture('denial')
      return json(res, 402, { detail: denials.insufficient_credits })
    }
    const slug = slugify(topic)
    if (!state.experts.has(slug)) {
      const base = await fixture('expert')
      state.experts.set(slug, {
        ...base,
        id: 100 + state.experts.size,
        name: slug,
        topic,
        tier: tier ?? 'standard',
        status: 'queued',
        readiness: 'pending',
        graph_expanded: false,
        persona_name: null,
        persona_bio: null,
        persona_style: null,
        avg_quality: null,
        source_count: 0,
        chunk_count: 0,
        node_count: 0,
        edge_count: 0,
        avatar: null,
      })
    }
    await startBuild(slug, topic)
    return streamBuild(req, res, slug, 0)
  }

  const expertMatch = /^\/experts\/([^/]+)(\/.*)?$/.exec(path)
  if (expertMatch) {
    const slug = decodeURIComponent(expertMatch[1])
    const rest = expertMatch[2] ?? ''
    const expert = state.experts.get(slug)

    if (rest === '' && method === 'GET') {
      if (!expert) return json(res, 404, { detail: 'Expert not found' })
      return json(res, 200, expert)
    }
    // The owner's link. A viewer resolves nothing through the ownership gate.
    const owned = expert && expert.access !== 'viewer'
    if (rest === '/share' || rest === '/share/reset') {
      if (!owned) return json(res, 404, { detail: 'Expert not found' })
      if (rest === '/share' && method === 'GET') return json(res, 200, shareState(slug))
      if (rest === '/share' && method === 'PUT') {
        if (!state.links.has(slug)) state.links.set(slug, { token: newToken(), viewers: 0 })
        return json(res, 200, shareState(slug))
      }
      if (rest === '/share/reset' && method === 'POST') {
        state.links.set(slug, { token: newToken(), viewers: 0 })
        return json(res, 200, shareState(slug))
      }
      if (rest === '/share' && method === 'DELETE') {
        state.links.delete(slug)
        return noContent(res)
      }
    }
    if (rest === '/access' && method === 'DELETE') {
      if (!expert) return json(res, 404, { detail: 'Expert not found' })
      if (owned) return json(res, 409, { detail: 'You own this expert' })
      state.experts.delete(slug)
      return noContent(res)
    }
    if (rest === '' && method === 'DELETE') {
      if (!expert) return json(res, 404, { detail: 'Expert not found' })
      state.experts.delete(slug)
      state.builds.delete(slug)
      // The real schema cascades: deleting an expert takes its conversations,
      // sources, passages and graph with it.
      for (const [id, conversation] of state.conversations) {
        if (conversation.expert_slug === slug) state.conversations.delete(id)
      }
      return noContent(res)
    }
    if (rest === '/picture' && method === 'GET') {
      if (!expert?.picture) return json(res, 404, { detail: 'This expert has no picture' })
      const etag = `"${PICTURE_SHA.repeat(5)}"`
      if (req.headers['if-none-match'] === etag) {
        res.writeHead(304, { ETag: etag, 'Cache-Control': 'private, max-age=31536000, immutable' })
        return res.end()
      }
      res.writeHead(200, {
        'Content-Type': 'image/png',
        'Content-Length': PICTURE_BYTES.length,
        ETag: etag,
        'Cache-Control': 'private, max-age=31536000, immutable',
      })
      return res.end(PICTURE_BYTES)
    }
    if (rest === '/picture' && method === 'DELETE') {
      if (!expert) return json(res, 404, { detail: 'Expert not found' })
      expert.picture = null
      return noContent(res)
    }
    if (rest === '/picture/refresh' && method === 'POST') {
      if (!expert) return json(res, 404, { detail: 'Expert not found' })
      expert.picture = { ...pictureMeta(), title: 'Apis mellifera' }
      return json(res, 200, expert)
    }
    if (rest === '/avatar' && method === 'PUT') {
      if (!expert) return json(res, 404, { detail: 'Expert not found' })
      const { avatar } = JSON.parse((await body(req)).toString())
      const allowed = ['sigil', 'shapes', 'glass', 'rings', 'identicon', 'icons', 'picture']
      if (avatar && !allowed.includes(avatar.style)) {
        return json(res, 400, {
          detail: `Unknown avatar style '${avatar.style}'. Choose one of: ${allowed.join(', ')}.`,
        })
      }
      expert.avatar = avatar
        ? { style: avatar.style, seed: avatar.seed ?? null, hue: avatar.hue ?? null }
        : null
      return json(res, 200, expert)
    }
    if (rest === '/build/events' && method === 'GET') {
      const after = Number(url.searchParams.get('after') || 0)
      if (!state.builds.has(slug)) await startBuild(slug, expert?.topic)
      return streamBuild(req, res, slug, Number.isFinite(after) ? after : 0, true)
    }
    if (rest === '/build/status') {
      const build = state.builds.get(slug)
      if (!build) return json(res, 404, { detail: 'No build job for this expert' })
      const last = build.events[build.delivered - 1]
      const finished = last && ['done', 'error', 'cancelled'].includes(last.type)
      return json(res, 200, {
        job_id: build.jobId,
        expert_status: expert?.status ?? 'building',
        expert_readiness: expert?.readiness ?? 'pending',
        job_status: finished ? 'succeeded' : 'running',
        attempts: 1,
        max_attempts: 3,
        last_error: null,
        updated_at: new Date().toISOString(),
      })
    }
    if (rest === '/build/cancel' && method === 'POST') {
      const build = state.builds.get(slug)
      if (!build) return json(res, 409, { detail: 'No active build for this expert' })
      build.events = [
        ...build.events.slice(0, build.delivered),
        { type: 'cancelled', message: 'Build cancelled' },
      ]
      if (expert) Object.assign(expert, { status: 'failed', error: 'Build cancelled' })
      return json(res, 202, { job_id: build.jobId, status: 'cancelled', credits_refunded: 3 })
    }
    if (rest === '/build/usage') {
      if (!state.builds.has(slug)) return json(res, 404, { detail: 'No build job' })
      return json(res, 200, {
        job_id: state.builds.get(slug).jobId,
        expert_id: expert?.id ?? 0,
        status: 'running',
        cost_usd: 1.6214,
        input_tokens: 482_113,
        output_tokens: 21_004,
        embed_tokens: 190_443,
        spend_cap_usd: 5,
        cap_exceeded_at: null,
        by_stage: [
          {
            stage: 'graph_extraction',
            calls: 9,
            input_tokens: 210_000,
            output_tokens: 12_000,
            cost_usd: 0.79,
          },
          {
            stage: 'contextualization',
            calls: 21,
            input_tokens: 190_000,
            output_tokens: 6_000,
            cost_usd: 0.65,
          },
          {
            stage: 'validation',
            calls: 4,
            input_tokens: 62_000,
            output_tokens: 2_400,
            cost_usd: 0.12,
          },
        ],
        by_model: [
          {
            provider: 'anthropic',
            mode: 'batch',
            model: 'claude-haiku-4-5-20251001',
            calls: 30,
            cost_usd: 0.91,
          },
        ],
        discovery: {
          estimated_ingest_usd: 0.91,
          actual_ingest_usd: 1.44,
          estimator_error: -0.368,
          note: 'A negative error means the forecast was low.',
        },
      })
    }
    if (rest === '/corpus-report' && method === 'GET') {
      if (!expert) return json(res, 404, { detail: 'Expert not found' })
      const report = await fixture('corpus-report')
      const decision = url.searchParams.get('decision') ?? 'all'
      const sources =
        decision === 'all'
          ? report.sources
          : report.sources.filter((source) => source.decision === decision)
      return json(res, 200, {
        ...report,
        expert: { name: expert.name, topic: expert.topic, tier: expert.tier },
        page: { ...report.page, decision, returned: sources.length },
        sources,
      })
    }
    if (rest === '/screening-flow' && method === 'GET') {
      if (!expert) return json(res, 404, { detail: 'Expert not found' })
      const flow = await fixture('screening-flow')
      return json(res, 200, {
        ...flow,
        expert: { name: expert.name, topic: expert.topic, tier: expert.tier },
      })
    }
    if (rest === '/corpus-report/export' && method === 'GET') {
      const format = url.searchParams.get('format') ?? 'csv'
      const isRis = format === 'ris'
      const payload = isRis
        ? 'TY  - JOUR\nTI  - Varroa destructor and honeybee viral loads\nER  - \n'
        : 'id,decision,title,quality_score,relevance_score,drop_reason\n804,accepted,"Varroa destructor and honeybee viral loads",8.5,9.0,\n'
      res.writeHead(200, {
        'Content-Type': isRis
          ? 'application/x-research-info-systems; charset=utf-8'
          : 'text/csv; charset=utf-8',
        'Content-Disposition': `attachment; filename="${slug}-all.${isRis ? 'ris' : 'csv'}"`,
        'X-Peritus-Export-Rows': '1',
      })
      return res.end(payload)
    }
    if (rest === '/sources/upload' && method === 'POST') {
      const raw = await body(req)
      if (raw.length === 0) return json(res, 400, { detail: 'The uploaded file is empty.' })
      const build = state.builds.get(slug)
      return json(res, 202, {
        upload_id: 9,
        job_id: build?.jobId ?? 501,
        title: 'Uploaded source',
        kind: 'pdf',
      })
    }
    if (rest === '/sources/url' && method === 'POST') {
      const { url: target } = JSON.parse((await body(req)).toString())
      if (!/^https?:\/\//i.test(target ?? '')) {
        return json(res, 422, { detail: 'URL must start with http:// or https://' })
      }
      return json(res, 202, { upload_id: 10, job_id: 502, title: target, kind: 'url' })
    }
    const sourceMatch = /^\/sources\/(\d+)$/.exec(rest)
    if (sourceMatch && method === 'DELETE') return noContent(res)

    if (rest === '/graph' && method === 'GET') {
      if (!expert) return json(res, 404, { detail: 'Expert not found' })
      if (!expert.graph_expanded) return json(res, 200, await fixture('graph-not-computed'))
      const graph =
        state.scenario === 'big-graph' ? bigGraph(await fixture('graph')) : await fixture('graph')
      const limit = Number(url.searchParams.get('limit') || 400)
      const nodes = graph.nodes.slice(0, limit)
      const ids = new Set(nodes.map((node) => node.id))
      return json(res, 200, {
        ...graph,
        expert: { name: expert.name, topic: expert.topic },
        nodes,
        edges: graph.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target)),
        truncated: nodes.length < graph.total_nodes,
      })
    }
    if (rest === '/conversations' && method === 'GET') {
      return json(
        res,
        200,
        [...state.conversations.values()]
          .filter((conversation) => conversation.expert_slug === slug)
          .map(summary)
      )
    }
    if (rest === '/conversations' && method === 'POST') {
      if (!expert) return json(res, 404, { detail: 'Expert not found' })
      if (expert.readiness === 'pending') {
        return json(res, 409, { detail: 'Expert is still building' })
      }
      const id = `00000000-0000-4000-8000-${String(state.nextConversation++).padStart(12, '0')}`
      const conversation = {
        id,
        expert_id: expert.id,
        expert_slug: expert.name,
        expert_topic: expert.topic,
        expert_persona_name: expert.persona_name,
        expert_status: expert.status,
        title: null,
        message_count: 0,
        created_at: new Date().toISOString(),
        last_message_at: new Date().toISOString(),
        messages: [],
      }
      state.conversations.set(id, conversation)
      return json(res, 200, summary(conversation))
    }
  }

  // ── conversations ──
  if (path === '/conversations' && method === 'GET') {
    return json(res, 200, [...state.conversations.values()].map(summary))
  }
  const conversationMatch = /^\/conversations\/([^/]+)(\/messages)?$/.exec(path)
  if (conversationMatch) {
    const id = conversationMatch[1]
    const conversation = state.conversations.get(id)
    if (!conversation) return json(res, 404, { detail: 'Conversation not found' })

    if (!conversationMatch[2]) {
      if (method === 'GET') return json(res, 200, conversation)
      if (method === 'PATCH') {
        conversation.title = JSON.parse((await body(req)).toString()).title
        return json(res, 200, summary(conversation))
      }
      if (method === 'DELETE') {
        state.conversations.delete(id)
        return noContent(res)
      }
    }
    if (conversationMatch[2] === '/messages' && method === 'POST') {
      const { question } = JSON.parse((await body(req)).toString())
      return streamChat(req, res, id, question)
    }
  }

  return json(res, 404, { detail: `No mock route for ${method} ${path}` })
}

function summary(conversation) {
  const { messages: _messages, ...rest } = conversation
  return rest
}

function session(email) {
  return {
    access_token: 'mock-access',
    refresh_token: 'mock-refresh',
    token_type: 'bearer',
    expires_in: 3600,
    expires_at: null,
    user: { id: '11111111-1111-1111-1111-111111111111', email },
  }
}

/** The server's own slugify — the client never does this. */
function slugify(topic) {
  return topic
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80)
}

await seed()

createServer((req, res) => {
  handle(req, res).catch((error) => {
    console.error('[mock-api]', error)
    if (!res.headersSent) json(res, 500, { detail: String(error) })
    else res.end()
  })
}).listen(PORT, () => {
  console.log(`[mock-api] listening on http://127.0.0.1:${PORT}`)
})
