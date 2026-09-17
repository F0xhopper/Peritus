import { createServer } from 'node:http'

import { body, json, noContent, slugify } from './http.mjs'
import { newToken, seed, shareState, sharedCard } from './seed.mjs'
import { PICTURE_BYTES, PICTURE_SHA, bigGraph, fixture, pictureMeta, state } from './state.mjs'
import { startBuild, streamBuild, streamChat } from './streams.mjs'

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
 *
 * This file is the routing table and nothing else. The world it serves is in
 * `state.mjs`, how that world is built in `seed.mjs`, the two streams in
 * `streams.mjs`, and the response shapes in `http.mjs`.
 */

const PORT = Number(process.env.MOCK_API_PORT || 8787)

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
      // `total_matching` counts the whole corpus under this filter, as the API
      // does — not the handful of rows the fixture carries.
      const matching =
        decision === 'accepted'
          ? report.totals.accepted
          : decision === 'rejected'
            ? report.totals.rejected
            : report.totals.considered
      return json(res, 200, {
        ...report,
        expert: { name: expert.name, topic: expert.topic, tier: expert.tier },
        page: { ...report.page, decision, returned: sources.length, total_matching: matching },
        sources,
      })
    }
    // The stored retrieval trails for a conversation's answers, which is what
    // makes "how this was answered" survive a reload.
    if (rest === '/answer-audits' && method === 'GET') {
      if (!expert) return json(res, 404, { detail: 'Expert not found' })
      const events = await fixture('chat-events')
      const live = events.retrieval_audit
      const conversation = url.searchParams.get('conversation_id')
      return json(res, 200, {
        expert: { name: expert.name, topic: expert.topic, tier: expert.tier },
        page: { limit: 50, offset: 0, returned: 1, total_matching: 1, has_more: false },
        audits: [
          {
            audit_id: live.audit_id,
            conversation_id: conversation,
            question: 'How effective is drone brood removal on its own?',
            subqueries: live.subqueries,
            followup_queries: live.follow_ups,
            coverage_satisfied: live.coverage_verdict === 'adequate',
            second_pass: false,
            passages: {
              retrieved: live.passages_considered,
              duplicate_hits: 1,
              unique: live.passages_considered - 1,
              in_context: live.passages_in_prompt,
              cited: live.passages_cited,
              not_in_context: live.passages_considered - live.passages_in_prompt,
              context_cap: live.passages_in_prompt,
            },
            sources: { in_context: 8, cited: live.passages_cited },
            contradiction_traversed: true,
            answer_chars: 640,
            created_at: '2026-09-09T09:00:02.000Z',
          },
        ],
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
      const bodies = {
        ris: {
          body: 'TY  - JOUR\nTI  - Varroa destructor and honeybee viral loads\nER  - \n',
          type: 'application/x-research-info-systems',
          extension: 'ris',
        },
        bibtex: {
          body: '@article{peritus804,\n  title = {Varroa destructor and honeybee viral loads}\n}\n',
          type: 'application/x-bibtex',
          extension: 'bib',
        },
        csv: {
          body: 'id,decision,title,drop_reason\n804,accepted,"Varroa destructor and honeybee viral loads",\n',
          type: 'text/csv',
          extension: 'csv',
        },
      }
      const chosen = bodies[format] ?? bodies.csv
      res.writeHead(200, {
        'Content-Type': `${chosen.type}; charset=utf-8`,
        'Content-Disposition': `attachment; filename="${slug}-all.${chosen.extension}"`,
        'X-Peritus-Export-Rows': '1',
      })
      return res.end(chosen.body)
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
