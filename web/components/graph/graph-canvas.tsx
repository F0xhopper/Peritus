'use client'

import { quadtree } from 'd3-quadtree'
import { zoom, zoomIdentity, type D3ZoomEvent, type ZoomBehavior } from 'd3-zoom'
import { select } from 'd3-selection'
// Side-effect import: `d3-transition` augments `Selection` with `.transition()`,
// which is what drives the 250ms pan-and-zoom to a focused node.
import 'd3-transition'
import { useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react'

import { cn } from '@/lib/cn'
import { paintGraph, readColours } from '@/lib/graph/paint'
import { usePrefersReducedMotion } from '@/hooks/use-media-query'
import type { SimulationRequest, SimulationResponse } from '@/lib/graph/simulation.worker'
import type { GraphEdge, GraphNode } from '@/lib/api/types'

/**
 * The concept graph, on a canvas.
 *
 * Canvas rather than SVG because 300 nodes and a thousand edges is 1,300 DOM
 * nodes the browser has to lay out, hit-test and style on every pan — and a
 * pan is every frame. Drawing is `requestAnimationFrame`, and only while the
 * simulation is hot or a gesture is in flight; a settled, untouched graph
 * paints nothing at all.
 *
 * Hit-testing goes through a `d3-quadtree` rebuilt when the layout settles, so
 * finding the node under a finger is a tree descent, not a scan of every node.
 *
 * `touch-action: none` on the canvas: the graph is the one surface that wants
 * every gesture for itself, and letting the page interpret a pinch would zoom
 * the document instead of the graph.
 *
 * **Drawing lives in `lib/graph/paint.ts`**, as a pure function of an explicit
 * state object. That is the part with real logic in it — the label collision
 * pass, the alpha ramp, the screen-space grid — and it is unit-tested there,
 * which it could not be while it read eight refs from this closure.
 *
 * The rest deliberately stays in one component. Splitting the worker and the
 * zoom binding into hooks was tried and reverted: they share `positions`,
 * `indexById`, `tree`, `hot` and `transform` between three concerns, and the
 * React Compiler forbids a hook mutating a ref it was handed. Every way around
 * that — a ref bag, a notify indirection — moved the coupling somewhere less
 * visible rather than removing it. The refs below are the component's state
 * machine, and they are clearer declared together than passed around.
 */

export interface GraphCanvasHandle {
  /** Pan and zoom to a node over 250ms. Used by search and by a node click. */
  focusNode: (id: number) => void
}

export function GraphCanvas({
  nodes,
  edges,
  selectedId,
  onSelect,
  onHover,
  handleRef,
  className,
}: {
  nodes: GraphNode[]
  edges: GraphEdge[]
  selectedId: number | null
  onSelect: (node: GraphNode | null) => void
  onHover: (node: GraphNode | null) => void
  handleRef?: React.RefObject<GraphCanvasHandle | null>
  className?: string
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const workerRef = useRef<Worker | null>(null)
  const positions = useRef<Float32Array>(new Float32Array(0))
  const transform = useRef(zoomIdentity)
  const zoomBehaviour = useRef<ZoomBehavior<HTMLCanvasElement, unknown> | null>(null)
  const tree = useRef<ReturnType<typeof quadtree<GraphNode>> | null>(null)
  const frame = useRef(0)
  const hot = useRef(true)
  const hovered = useRef<number | null>(null)
  const size = useRef({ width: 0, height: 0, dpr: 1 })
  const reducedMotion = usePrefersReducedMotion()
  // How many of the busiest nodes carry a permanent label.
  const [labelBudget, setLabelBudget] = useState(6)
  // Once someone pans or zooms, the layout is theirs: never re-fit under them.
  const userMoved = useRef(false)

  // Node order is the index into `positions`; the map is the reverse lookup for
  // focus and selection, which arrive as ids.
  const indexById = useRef(new Map<number, number>())
  useEffect(() => {
    indexById.current = new Map(nodes.map((node, index) => [node.id, index]))
  }, [nodes])

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context) return
    paintGraph(context, {
      nodes,
      edges,
      positions: positions.current,
      indexById: indexById.current,
      transform: transform.current,
      ...size.current,
      selectedId,
      hoveredId: hovered.current,
      labelBudget,
      colours: readColours(canvas),
    })
  }, [nodes, edges, selectedId, labelBudget])

  // The paint loop lives in a ref rather than as a self-referencing callback:
  // a `useCallback` that calls itself reads its own binding before it is
  // initialised, which is a temporal-dead-zone hazard as well as a lint error.
  const drawRef = useRef(draw)
  useEffect(() => {
    drawRef.current = draw
  }, [draw])

  /**
   * Schedule one paint, coalescing every request inside the same frame.
   *
   * It **cancels and re-arms** rather than returning early when a frame is
   * already pending, and that is the whole point: the early-return version
   * trusted `frame.current` to mean "a callback is coming", and a requested
   * frame that never runs is exactly what a browser gives you for a document
   * that is hidden, occluded, or mid-view-transition. One dropped callback left
   * a non-zero id behind, every later request was swallowed by the guard, and
   * the canvas stayed blank *forever* — with the simulation still ticking
   * behind it, which is precisely how this looked in the wild: a live node
   * count under an empty graph.
   *
   * Cancelling costs nothing and the coalescing is identical, because a fresh
   * request still cannot run more than once per frame.
   */
  const requestDraw = useCallback(() => {
    const tick = () => {
      frame.current = 0
      drawRef.current()
      // Keep painting only while there is something to paint: a settled,
      // untouched graph costs nothing per frame.
      if (hot.current) frame.current = requestAnimationFrame(tick)
    }
    if (frame.current) cancelAnimationFrame(frame.current)
    frame.current = requestAnimationFrame(tick)
  }, [])

  /**
   * Repaint when the tab comes back.
   *
   * A settled graph paints nothing per frame, so if the layout finishes while
   * the document is hidden — a background tab, another window in front — there
   * is no later event to draw it. Coming back to a blank canvas is the same
   * failure as above by a different route.
   */
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') requestDraw()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [requestDraw])

  // Size the canvas to its container at the device pixel ratio.
  useEffect(() => {
    const wrapper = wrapperRef.current
    const canvas = canvasRef.current
    if (!wrapper || !canvas) return

    const resize = () => {
      const rect = wrapper.getBoundingClientRect()
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      size.current = { width: rect.width, height: rect.height, dpr }
      canvas.width = Math.floor(rect.width * dpr)
      canvas.height = Math.floor(rect.height * dpr)
      canvas.style.width = `${rect.width}px`
      canvas.style.height = `${rect.height}px`
      workerRef.current?.postMessage({
        type: 'resize',
        width: rect.width,
        height: rect.height,
      } satisfies SimulationRequest)
      hot.current = true
      requestDraw()
    }

    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(wrapper)
    return () => observer.disconnect()
  }, [requestDraw])

  // Permanent labels at every width — an unlabelled graph is meaningless until
  // tapped — but half as many below `lg`, where the canvas is small.
  useEffect(() => {
    const query = window.matchMedia('(min-width: 1024px)')
    const update = () => setLabelBudget(query.matches ? 12 : 6)
    update()
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  const fitToCanvas = useCallback(() => {
    const canvas = canvasRef.current
    const behaviour = zoomBehaviour.current
    const pos = positions.current
    const { width, height } = size.current
    if (!canvas || !behaviour || pos.length < 2 || !width || !height) return
    let minX = Infinity
    let minY = Infinity
    let maxX = -Infinity
    let maxY = -Infinity
    for (let i = 0; i < pos.length; i += 2) {
      if (!Number.isFinite(pos[i]) || !Number.isFinite(pos[i + 1])) continue
      minX = Math.min(minX, pos[i])
      maxX = Math.max(maxX, pos[i])
      minY = Math.min(minY, pos[i + 1])
      maxY = Math.max(maxY, pos[i + 1])
    }
    if (!Number.isFinite(minX)) return
    // Room for labels under the nodes and the floating controls at the edges.
    const padding = 72
    const scale = Math.max(
      0.15,
      Math.min(
        2,
        (width - padding * 2) / Math.max(maxX - minX, 1),
        (height - padding * 2) / Math.max(maxY - minY, 1)
      )
    )
    const target = zoomIdentity
      .translate(width / 2, height / 2)
      .scale(scale)
      .translate(-(minX + maxX) / 2, -(minY + maxY) / 2)
    select(canvas).call(behaviour.transform, target)
  }, [])

  // The simulation. Re-initialised when the node set changes, seeded with the
  // positions the previous layout reached so a limit change reheats rather
  // than scatters.
  useEffect(() => {
    if (nodes.length === 0) return
    const worker = new Worker(new URL('@/lib/graph/simulation.worker.ts', import.meta.url), {
      type: 'module',
    })
    workerRef.current = worker

    const previous = positions.current
    const previousIndex = indexById.current
    const seeded = nodes.map((node) => {
      const old = previousIndex.get(node.id)
      if (old !== undefined && previous.length >= (old + 1) * 2) {
        return { id: node.id, degree: node.degree, x: previous[old * 2], y: previous[old * 2 + 1] }
      }
      return { id: node.id, degree: node.degree }
    })

    worker.onmessage = (event: MessageEvent<SimulationResponse>) => {
      if (event.data.type === 'tick') {
        positions.current = event.data.positions
        hot.current = event.data.alpha > 0.01
        requestDraw()
      } else {
        hot.current = false
        // The quadtree is rebuilt once the layout stops moving; rebuilding it
        // per tick would cost more than the hit-tests it serves.
        tree.current = quadtree<GraphNode>()
          .x((node) => positions.current[indexById.current.get(node.id)! * 2] ?? 0)
          .y((node) => positions.current[indexById.current.get(node.id)! * 2 + 1] ?? 0)
          .addAll(nodes)
        // Fit the settled layout to the canvas, unless the reader has already
        // moved it: a small graph otherwise sat in a tenth of the space.
        if (!userMoved.current) fitToCanvas()
        requestDraw()
      }
    }

    worker.postMessage({
      type: 'init',
      nodes: seeded,
      links: edges.map((edge) => ({
        source: edge.source,
        target: edge.target,
        evidence: edge.evidence,
      })),
      width: size.current.width || 800,
      height: size.current.height || 600,
      settled: reducedMotion,
    } satisfies SimulationRequest)

    return () => {
      worker.postMessage({ type: 'stop' } satisfies SimulationRequest)
      worker.terminate()
      workerRef.current = null
    }
  }, [nodes, edges, reducedMotion, requestDraw, fitToCanvas])

  // Pan, pinch and wheel, plus the programmatic focus transition.
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const behaviour = zoom<HTMLCanvasElement, unknown>()
      .scaleExtent([0.15, 6])
      .on('zoom', (event: D3ZoomEvent<HTMLCanvasElement, unknown>) => {
        transform.current = event.transform
        requestDraw()
      })
      .on('start', (event: D3ZoomEvent<HTMLCanvasElement, unknown>) => {
        // A real gesture (not a programmatic fit or focus) hands the view over.
        if (event.sourceEvent) userMoved.current = true
        hot.current = true
        requestDraw()
      })
      .on('end', () => {
        // Stop painting once the gesture ends and the simulation is cold.
        hot.current = false
        requestDraw()
      })

    zoomBehaviour.current = behaviour
    const selection = select(canvas)
    selection.call(behaviour)
    return () => {
      selection.on('.zoom', null)
      zoomBehaviour.current = null
    }
  }, [requestDraw])

  const nodeAt = useCallback((clientX: number, clientY: number): GraphNode | null => {
    const canvas = canvasRef.current
    if (!canvas || !tree.current) return null
    const rect = canvas.getBoundingClientRect()
    const [x, y] = transform.current.invert([clientX - rect.left, clientY - rect.top])
    // 12 screen pixels of slack, converted into layout space so the target
    // stays thumb-sized at every zoom level.
    return tree.current.find(x, y, 12 / transform.current.k) ?? null
  }, [])

  useImperativeHandle(
    handleRef,
    () => ({
      focusNode: (id: number) => {
        const canvas = canvasRef.current
        const behaviour = zoomBehaviour.current
        const index = indexById.current.get(id)
        if (!canvas || !behaviour || index === undefined) return
        const x = positions.current[index * 2]
        const y = positions.current[index * 2 + 1]
        if (!Number.isFinite(x) || !Number.isFinite(y)) return
        const { width, height } = size.current
        const target = zoomIdentity
          .translate(width / 2, height / 2)
          .scale(Math.max(1.2, transform.current.k))
          .translate(-x, -y)
        select(canvas)
          // 250ms, or instant under reduced motion.
          .transition()
          .duration(reducedMotion ? 0 : 250)
          .call(behaviour.transform, target)
      },
    }),
    [reducedMotion]
  )

  return (
    <div ref={wrapperRef} className={cn('relative h-full w-full', className)}>
      <canvas
        ref={canvasRef}
        // Every gesture belongs to the graph.
        className="h-full w-full touch-none"
        onPointerMove={(event) => {
          const node = nodeAt(event.clientX, event.clientY)
          const id = node?.id ?? null
          if (id !== hovered.current) {
            hovered.current = id
            onHover(node)
            requestDraw()
          }
        }}
        onPointerLeave={() => {
          if (hovered.current !== null) {
            hovered.current = null
            onHover(null)
            requestDraw()
          }
        }}
        onClick={(event) => {
          const node = nodeAt(event.clientX, event.clientY)
          onSelect(node)
          if (node) {
            // Centre what was just tapped, which on a phone is usually under
            // the finger at the edge of the canvas.
            handleRef?.current?.focusNode(node.id)
          }
        }}
      />
    </div>
  )
}
