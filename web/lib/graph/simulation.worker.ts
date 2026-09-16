/// <reference lib="webworker" />

import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force'

/**
 * The force layout, in a Web Worker.
 *
 * The main thread never runs the simulation. `d3-force` is a tight numeric loop
 * over every node and every edge on every tick, and running it on the main
 * thread means the pan gesture and the canvas paint are competing with it for
 * the same 16ms — which is exactly how a 300-node graph ends up at 20fps on a
 * phone. Here the worker ticks and posts a `Float32Array` of positions, and the
 * main thread only ever draws.
 *
 * Positions are transferred, not cloned: the buffer is handed over on each post
 * and a fresh one allocated, so a 300-node graph costs no copy per frame.
 *
 * Under reduced motion the worker runs the whole simulation to rest *before*
 * posting anything, so the layout appears settled rather than visibly
 * converging.
 */

interface WorkerNode extends SimulationNodeDatum {
  id: number
  degree: number
}

interface WorkerLink extends SimulationLinkDatum<WorkerNode> {
  source: number | WorkerNode
  target: number | WorkerNode
  evidence: number
}

export type SimulationRequest =
  | {
      type: 'init'
      nodes: { id: number; degree: number; x?: number; y?: number }[]
      links: { source: number; target: number; evidence: number }[]
      width: number
      height: number
      /** Settle before the first post, for `prefers-reduced-motion`. */
      settled: boolean
    }
  | { type: 'reheat'; alpha: number }
  | { type: 'resize'; width: number; height: number }
  | { type: 'stop' }

export type SimulationResponse =
  | {
      type: 'tick'
      /** `[x0, y0, x1, y1, …]` in node order. Transferred, not copied. */
      positions: Float32Array
      alpha: number
    }
  | { type: 'end' }

let simulation: Simulation<WorkerNode, WorkerLink> | null = null
let nodes: WorkerNode[] = []
let buffer = new Float32Array(0)

function post() {
  if (buffer.length !== nodes.length * 2) buffer = new Float32Array(nodes.length * 2)
  for (let i = 0; i < nodes.length; i += 1) {
    buffer[i * 2] = nodes[i].x ?? 0
    buffer[i * 2 + 1] = nodes[i].y ?? 0
  }
  const message: SimulationResponse = {
    type: 'tick',
    positions: buffer,
    alpha: simulation?.alpha() ?? 0,
  }
  // Transfer the buffer; allocate a new one for the next tick.
  self.postMessage(message, [buffer.buffer])
  buffer = new Float32Array(0)
}

self.onmessage = (event: MessageEvent<SimulationRequest>) => {
  const request = event.data

  if (request.type === 'init') {
    simulation?.stop()
    nodes = request.nodes.map((node) => ({ ...node }))
    const byId = new Map(nodes.map((node) => [node.id, node]))
    // An edge to a node outside the cap is dropped rather than creating a
    // phantom node — the API already returns only edges between capped nodes,
    // but a truncated graph must not invent geometry either way.
    const links: WorkerLink[] = request.links
      .filter((link) => byId.has(link.source) && byId.has(link.target))
      .map((link) => ({ ...link }))

    simulation = forceSimulation<WorkerNode, WorkerLink>(nodes)
      .force(
        'link',
        forceLink<WorkerNode, WorkerLink>(links)
          .id((node) => node.id)
          // A well-evidenced edge pulls harder, so the graph's spine is the
          // part the corpus actually supports.
          .strength((link) => Math.min(0.9, 0.15 + link.evidence * 0.08))
          .distance(48)
      )
      // Busy nodes push harder, which is what keeps hubs legible instead of
      // buried under their own neighbours.
      .force(
        'charge',
        forceManyBody<WorkerNode>().strength((node) => -60 - node.degree * 12)
      )
      .force('center', forceCenter(request.width / 2, request.height / 2).strength(0.06))
      .force(
        'collide',
        forceCollide<WorkerNode>().radius((node) => 6 + Math.sqrt(node.degree) * 2)
      )
      .stop()

    if (request.settled) {
      // 300 ticks is well past convergence for the node counts this page caps
      // at, and it costs a few hundred milliseconds once rather than two
      // seconds of visible motion.
      simulation.tick(300)
      post()
      self.postMessage({ type: 'end' } satisfies SimulationResponse)
      return
    }

    simulation.on('tick', post).on('end', () => {
      self.postMessage({ type: 'end' } satisfies SimulationResponse)
    })
    simulation.restart()
    return
  }

  if (request.type === 'reheat') {
    // Existing nodes keep their positions; only the energy goes back up, so a
    // limit change does not scatter a layout the reader has been looking at.
    simulation?.alpha(request.alpha).restart()
    return
  }

  if (request.type === 'resize') {
    simulation?.force('center', forceCenter(request.width / 2, request.height / 2).strength(0.06))
    simulation?.alpha(0.15).restart()
    return
  }

  if (request.type === 'stop') {
    simulation?.stop()
    simulation = null
    nodes = []
  }
}
