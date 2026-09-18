import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SimulationRequest, SimulationResponse } from '@/lib/graph/simulation.worker'

/**
 * The force layout that runs in a Web Worker.
 *
 * Untested until now because it is a worker, which is precisely why it was
 * worth testing: a bug here shows up as a graph that looks *plausible* — nodes
 * in the wrong place, a hub buried, an edge drawn to nothing — and no assertion
 * anywhere would notice. The Playwright graph test counts opaque pixels, which
 * catches a blank canvas and nothing subtler.
 *
 * Three properties, all of which are quiet when broken:
 *
 * - **Determinism.** `d3-force` seeds its initial arrangement deterministically,
 *   so the same graph must settle to the same layout. If it did not, every
 *   reload would move the reader's mental map of a corpus.
 * - **A truncated graph invents no geometry.** The node cap means edges can
 *   point outside the set; dropping them is right, creating phantom nodes for
 *   them is not.
 * - **Reduced motion settles before it paints.** The whole point of the
 *   `settled` path is that the first thing on screen is the final layout, not
 *   the start of two seconds of visible convergence.
 */

/** The worker's `self`, with the messages it posts collected. */
function workerHost() {
  const posted: SimulationResponse[] = []
  const host = {
    onmessage: null as ((event: MessageEvent<SimulationRequest>) => void) | null,
    postMessage(message: SimulationResponse) {
      // Copied, because the real `postMessage` transfers the buffer and the
      // worker allocates a fresh one immediately after.
      posted.push(
        message.type === 'tick' ? { ...message, positions: message.positions.slice() } : message
      )
    },
  }
  return { host, posted }
}

interface Worker {
  posted: SimulationResponse[]
  send: (request: SimulationRequest) => void
}

/** The worker under test, so `afterEach` can stop it before `self` disappears. */
let current: Worker | null = null

/** Load a fresh copy of the worker over a fresh host. Module state is global. */
async function loadWorker(): Promise<Worker> {
  const { host, posted } = workerHost()
  vi.stubGlobal('self', host)
  vi.resetModules()
  await import('@/lib/graph/simulation.worker')
  current = {
    posted,
    send(request: SimulationRequest) {
      host.onmessage?.({ data: request } as MessageEvent<SimulationRequest>)
    },
  }
  return current
}

const NODES = [
  { id: 1, degree: 5 },
  { id: 2, degree: 3 },
  { id: 3, degree: 1 },
  { id: 4, degree: 1 },
]
const LINKS = [
  { source: 1, target: 2, evidence: 4 },
  { source: 1, target: 3, evidence: 1 },
  { source: 2, target: 4, evidence: 2 },
]

function init(overrides: Partial<Extract<SimulationRequest, { type: 'init' }>> = {}) {
  return {
    type: 'init' as const,
    nodes: NODES,
    links: LINKS,
    width: 800,
    height: 600,
    settled: true,
    ...overrides,
  }
}

beforeEach(() => {
  vi.unstubAllGlobals()
  current = null
})

afterEach(() => {
  // Stop before `self` goes away. A running simulation ticks on a d3-timer,
  // and a tick after the stub is torn down throws `self is not defined` from
  // inside the timer — which is the real-world shape of the bug this asserts
  // against in `stop` below.
  current?.send({ type: 'stop' })
  current = null
  vi.unstubAllGlobals()
})

describe('the settled path, which is what reduced motion gets', () => {
  it('posts one laid-out frame and then ends', async () => {
    const worker = await loadWorker()
    worker.send(init())

    expect(worker.posted.map((m) => m.type)).toEqual(['tick', 'end'])
  })

  it('posts positions for every node, in node order, all finite', async () => {
    const worker = await loadWorker()
    worker.send(init())

    const tick = worker.posted[0] as Extract<SimulationResponse, { type: 'tick' }>
    expect(tick.positions).toHaveLength(NODES.length * 2)
    for (const value of tick.positions) expect(Number.isFinite(value)).toBe(true)
  })

  it('spreads the nodes rather than stacking them at the centre', async () => {
    // A layout that collapsed would still be "finite positions"; this is the
    // assertion that the forces actually ran.
    const worker = await loadWorker()
    worker.send(init())

    const tick = worker.posted[0] as Extract<SimulationResponse, { type: 'tick' }>
    const points = Array.from({ length: NODES.length }, (_, i) => [
      tick.positions[i * 2],
      tick.positions[i * 2 + 1],
    ])
    const distinct = new Set(points.map(([x, y]) => `${Math.round(x)},${Math.round(y)}`))
    expect(distinct.size).toBe(NODES.length)
  })

  it('settles to the same layout every time', async () => {
    const first = await loadWorker()
    first.send(init())
    const second = await loadWorker()
    second.send(init())

    const a = (first.posted[0] as Extract<SimulationResponse, { type: 'tick' }>).positions
    const b = (second.posted[0] as Extract<SimulationResponse, { type: 'tick' }>).positions
    expect(Array.from(b)).toEqual(Array.from(a))
  })
})

describe('a truncated graph', () => {
  it('drops an edge pointing outside the node set instead of inventing a node', async () => {
    const worker = await loadWorker()
    worker.send(init({ links: [...LINKS, { source: 1, target: 999, evidence: 9 }] }))

    const tick = worker.posted[0] as Extract<SimulationResponse, { type: 'tick' }>
    // Four nodes in, four nodes out — the dangling edge added no geometry.
    expect(tick.positions).toHaveLength(NODES.length * 2)
  })

  it('lays out a graph with no edges at all', async () => {
    // The state a brand-new expert is in before graph extraction runs.
    const worker = await loadWorker()
    worker.send(init({ links: [] }))

    expect(worker.posted.map((m) => m.type)).toEqual(['tick', 'end'])
  })
})

describe('the live path', () => {
  it('ticks repeatedly and reports a falling alpha', async () => {
    const worker = await loadWorker()
    worker.send(init({ settled: false }))
    // d3-force ticks on a timer, so let a few frames land.
    await new Promise((resolve) => setTimeout(resolve, 120))

    const ticks = worker.posted.filter(
      (m): m is Extract<SimulationResponse, { type: 'tick' }> => m.type === 'tick'
    )
    expect(ticks.length).toBeGreaterThan(1)
    // Alpha is the simulation's remaining energy; a layout that never cools is
    // one that never stops repainting.
    expect(ticks.at(-1)!.alpha).toBeLessThan(ticks[0].alpha)
  })
})

describe('stop', () => {
  it('is safe before anything was ever started', async () => {
    const worker = await loadWorker()
    expect(() => worker.send({ type: 'stop' })).not.toThrow()
  })

  it('leaves nothing running that could post after the canvas is gone', async () => {
    const worker = await loadWorker()
    worker.send(init({ settled: false }))
    await new Promise((resolve) => setTimeout(resolve, 60))

    worker.send({ type: 'stop' })
    const after = worker.posted.length
    // Reheat must not resurrect a stopped simulation, and nothing may tick.
    worker.send({ type: 'reheat', alpha: 0.5 })
    await new Promise((resolve) => setTimeout(resolve, 60))

    expect(worker.posted.length).toBe(after)
  })
})
