'use client'

import { zoom, zoomIdentity, type D3ZoomEvent, type ZoomBehavior } from 'd3-zoom'
import { select } from 'd3-selection'
// Side-effect import: `d3-transition` augments `Selection` with `.transition()`,
// which drives the pan-and-zoom to a focused thing.
import 'd3-transition'
import { useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react'

import { Avatar } from '@/components/identity/avatar'
import { usePrefersReducedMotion } from '@/hooks/use-media-query'
import { cn } from '@/lib/cn'
import type { ExpertWithCatalog, MapResponse } from '@/lib/api/types'
import { ORBIT, type BrainLayout } from '@/lib/brain/layout'
import type { LayoutRequest, LayoutResponse } from '@/lib/brain/layout.worker'
import {
  IDLE_AFTER_MS,
  IDLE_FRAME_MS,
  advance,
  disengage,
  engage,
  initialMotion,
  isMoving,
  lcg,
  unproject,
  type Motion,
  type Pulse,
  type View,
} from '@/lib/brain/motion'
import { paintBrain, readBrainColours, type Hit } from '@/lib/brain/paint'
import {
  arrivalPulses,
  burstPulses,
  entrancePulses,
  hitFor,
  hitKey,
  hitPoint,
  hitTest,
  idlePulse,
  mapSummary,
  selectionFor,
  selectionPulses,
  type BurstEffect,
} from '@/lib/brain/scene'
import type { BrainSelection, Lit } from '@/lib/brain/selection'

/**
 * The expert's map, on a canvas — docs/plans/expert-brain.md, phases 3–6.
 *
 * The layout is computed once, in a worker, and never moves; everything that
 * moves is the *view* of it. **Idle is alive, engaged is still**: untouched,
 * the map is drawn tilted and turns once in eight minutes, and a dendrite fires
 * now and then; the first pointer movement, touch, wheel or selection flattens
 * it and turns it back to rest, and it stays flat until six seconds pass with
 * no pointer movement and nothing open (`lib/brain/motion.ts`).
 *
 * **Cost.** A flat map with nothing firing paints nothing per frame, as the old
 * graph did. The idle loop runs at 30fps and stops when the document is hidden
 * or the canvas is off-screen or has no size — which is also what keeps a map
 * behind `display: none` (the List view, at first paint) from doing anything at
 * all. Under reduced motion nothing turns, tilts or fires, and a selection
 * lights instantly.
 *
 * **Never trust a pending `requestAnimationFrame` id as "a frame is coming"**
 * (web/AGENTS.md): the loop cancels and re-arms, and repaints on
 * `visibilitychange`, exactly as the graph canvas learned to.
 *
 * The loop reads everything through `live`, a ref refreshed after each render,
 * so `requestDraw` is stable: a layout arriving or a selection changing must
 * never re-run the effects that own the motion state and reset it.
 *
 * Hit-testing inverts the live transform — unzoom, unscale y, unrotate — so a
 * click during the flatten still lands on what is under it.
 */

export interface BrainCanvasHandle {
  /** Flatten, then pan and zoom to a thing. */
  focus: (selection: BrainSelection) => void
  /** Flatten and hold still — a keypress in the search counts as engaging. */
  engage: () => void
  /** Zoom about the centre of the view: the page's + and − buttons. */
  zoomBy: (factor: number) => void
  /** Back to the whole map, centred — and the view is the map's again to refit. */
  reset: () => void
}

/** How long before idle firing picks another dendrite. */
const FIRE_EVERY_MS = 800
/** Room around the orbit when fitting, for labels and the floating controls. */
const FIT_MARGIN = 58

/** A one-off effect, fired once per `key`. */
export type Burst = BurstEffect

interface Live {
  still: boolean
  labels: boolean
  map: MapResponse
  layout: BrainLayout | null
  lit: Lit | null
  selection: BrainSelection | null
  reducedMotion: boolean
  labelBudget: number
}

export function BrainCanvas({
  map,
  expert,
  selection,
  lit,
  cited = false,
  onSelect,
  handleRef,
  still = false,
  interactive = true,
  labels = true,
  bursts,
  onDropFile,
  className,
}: {
  map: MapResponse
  expert: ExpertWithCatalog
  selection: BrainSelection | null
  lit: Lit | null
  /** Whether `lit` is an answer's citations (phase 7): the entrance fires from them. */
  cited?: boolean
  onSelect: (selection: BrainSelection | null) => void
  handleRef?: React.RefObject<BrainCanvasHandle | null>
  /**
   * Flat and unturned, with no idle firing: the build page while a build runs
   * (expert-brain-interactive.md). Growth is the motion; turning the scene as
   * well would have arriving sources chase a moving target. Going false tilts
   * the map into its idle orbit, once.
   */
  still?: boolean
  /** False: hover names things, clicks select nothing (a build in progress). */
  interactive?: boolean
  /** False: no labels but the one under the pointer (the 280px build form). */
  labels?: boolean
  /** One-off effects from the event log: candidates judged, sources being read. */
  bursts?: Burst[]
  /** A file dropped on the map (fine pointer only) — the owner adding a source. */
  onDropFile?: (file: File) => void
  className?: string
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const nucleusRef = useRef<HTMLDivElement>(null)
  const reducedMotion = usePrefersReducedMotion()

  // A layout is only ever drawn with the map it was computed from. After a
  // refresh (a source added, a sector expanded) the new map arrives a moment
  // before its layout, and painting one against the other indexes past the end
  // of the layout's arrays.
  const [scene, setScene] = useState<{ map: MapResponse; layout: BrainLayout } | null>(null)
  const layout = scene?.layout ?? null
  const drawn = scene?.map ?? map
  const [sized, setSized] = useState(false)
  const [labelBudget, setLabelBudget] = useState(8)

  const live = useRef<Live>({
    map: drawn,
    layout,
    lit,
    selection,
    reducedMotion,
    labelBudget,
    still,
    labels,
  })
  const size = useRef({ width: 0, height: 0, dpr: 1 })
  const zoomState = useRef({ k: 1, x: 0, y: 0 })
  const fitScale = useRef(1)
  const zoomBehaviour = useRef<ZoomBehavior<HTMLCanvasElement, unknown> | null>(null)
  const userMoved = useRef(false)
  const motion = useRef<Motion>(initialMotion(0, true))
  const pulses = useRef<Pulse[]>([])
  const hovered = useRef<Hit | null>(null)
  const frame = useRef(0)
  const lastPaint = useRef(0)
  const lastFire = useRef(0)
  const gesture = useRef(false)
  const onScreen = useRef(true)
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const random = useRef(lcg(7))
  const glow = useRef<{ colour: string; sprite: HTMLCanvasElement } | null>(null)
  const entered = useRef(false)
  // What the view is centred on, so a resize (the panel opening beside the
  // map) keeps it centred. Cleared by the reader's own pan or zoom.
  const focused = useRef<{ x: number; y: number; k: number } | null>(null)

  // ── the loop ──────────────────────────────────────────────────────────────

  const currentView = useCallback(
    (): View => ({
      ...zoomState.current,
      tilt: motion.current.tilt,
      rotation: motion.current.rotation,
    }),
    []
  )

  const paint = useCallback(
    (now: number) => {
      const canvas = canvasRef.current
      const context = canvas?.getContext('2d')
      const state = live.current
      if (!canvas || !context || !state.layout || !size.current.width) return
      const colours = readBrainColours(canvas)
      const view = currentView()
      paintBrain(context, {
        map: state.map,
        layout: state.layout,
        view,
        ...size.current,
        colours,
        lit: state.lit,
        selected: hitFor(state.map, state.selection),
        hovered: hovered.current,
        pulses: pulses.current,
        now,
        labelBudget: state.labels ? state.labelBudget : 0,
        labels: state.labels,
        glow: glowSprite(glow, colours.fg),
      })
      // The nucleus is DOM (the avatar already resolves picture, drawing and
      // monogram), so it follows the view here rather than being painted.
      const nucleus = nucleusRef.current
      if (nucleus) {
        // Sized with the map: 44px where the map fits a laptop, about half that
        // where it fits a phone, never a blot over the ring.
        const scale = Math.max(0.45, Math.min(2.4, view.k * 1.1))
        nucleus.style.transform = `translate(${view.x}px, ${view.y}px) translate(-50%, -50%) scale(${scale})`
        nucleus.style.opacity = state.lit ? '0.5' : '1'
      }
    },
    [currentView]
  )

  /**
   * One frame, and the loop while anything moves. Cancels and re-arms rather
   * than trusting a pending id. Throttled to 30fps unless a gesture or the
   * flatten is in flight, which want every frame.
   */
  const requestDraw = useCallback(() => {
    const tick = (time: number) => {
      frame.current = 0
      const state = live.current
      const throttle = !gesture.current && motion.current.ease === null
      const due = !throttle || time - lastPaint.current >= IDLE_FRAME_MS - 2
      if (due) {
        lastPaint.current = time
        motion.current = advance(motion.current, time)
        pulses.current = pulses.current.filter((pulse) => time < pulse.start + pulse.duration)
        if (!state.reducedMotion && !motion.current.engaged && state.layout) {
          if (time - lastFire.current >= FIRE_EVERY_MS) {
            lastFire.current = time
            const pulse = idlePulse(state.map, state.layout, random.current, time)
            if (pulse) pulses.current.push(pulse)
          }
        }
        paint(time)
      }
      const running =
        document.visibilityState === 'visible' &&
        onScreen.current &&
        size.current.width > 0 &&
        (gesture.current ||
          pulses.current.length > 0 ||
          (!state.reducedMotion && isMoving(motion.current)) ||
          (!state.reducedMotion && state.map.sources.some((source) => source.pending)))
      // A frame the throttle skipped is still owed. Stopping here dropped the
      // layout's first paint under reduced motion, where nothing else re-arms
      // the loop: the map stayed blank until something was touched.
      if (running || !due) frame.current = requestAnimationFrame(tick)
    }
    if (frame.current) cancelAnimationFrame(frame.current)
    frame.current = requestAnimationFrame(tick)
  }, [paint])

  useEffect(() => {
    live.current = { map: drawn, layout, lit, selection, reducedMotion, labelBudget, still, labels }
    requestDraw()
  }, [drawn, layout, lit, selection, reducedMotion, labelBudget, still, labels, requestDraw])

  // ── engagement ────────────────────────────────────────────────────────────

  const scheduleIdle = useCallback(() => {
    if (idleTimer.current) clearTimeout(idleTimer.current)
    if (live.current.reducedMotion || live.current.still) return
    idleTimer.current = setTimeout(() => {
      idleTimer.current = null
      // Nothing open: back to the idle orbit. Something open: stay still.
      if (live.current.selection !== null) return
      motion.current = disengage(motion.current, performance.now())
      requestDraw()
    }, IDLE_AFTER_MS)
  }, [requestDraw])

  const engageNow = useCallback(() => {
    if (live.current.reducedMotion) return
    motion.current = engage(motion.current, performance.now())
    scheduleIdle()
    requestDraw()
  }, [scheduleIdle, requestDraw])

  // Reduced motion is flat from the first frame; otherwise every visit opens
  // on the same idle frame.
  const wasStill = useRef(still)
  useEffect(() => {
    const now = performance.now()
    if (reducedMotion) {
      motion.current = initialMotion(now, true)
      pulses.current = []
    } else if (still) {
      motion.current = initialMotion(now, true)
    } else if (wasStill.current) {
      // The build has finished: tilt into the idle orbit, once.
      motion.current = disengage(motion.current, now)
    } else {
      motion.current = initialMotion(now, false)
    }
    wasStill.current = still
    requestDraw()
  }, [reducedMotion, still, requestDraw])

  // A selection engages and fires one pulse down each lit dendrite — once, not
  // looping. Clearing it starts the idle countdown.
  const selectionKey = hitKey(hitFor(map, selection))
  useEffect(() => {
    const state = live.current
    if (!selectionKey) {
      scheduleIdle()
      return
    }
    engageNow()
    if (!state.reducedMotion && state.layout && state.lit && !cited) {
      pulses.current = selectionPulses(state.map, state.layout, state.lit, performance.now())
      requestDraw()
    }
  }, [selectionKey, cited, engageNow, scheduleIdle, requestDraw])

  // ── size, visibility ──────────────────────────────────────────────────────

  const fit = useCallback(() => {
    const canvas = canvasRef.current
    const behaviour = zoomBehaviour.current
    const { width, height } = size.current
    if (!canvas || !behaviour || !width || !height) return
    const k = Math.min(width, height) / (2 * (ORBIT + FIT_MARGIN))
    fitScale.current = k
    select(canvas).call(behaviour.transform, zoomIdentity.translate(width / 2, height / 2).scale(k))
  }, [])

  const centreOn = useCallback((target: { x: number; y: number; k: number }, duration: number) => {
    const canvas = canvasRef.current
    const behaviour = zoomBehaviour.current
    const { width, height } = size.current
    if (!canvas || !behaviour || !width || !height) return
    const transform = zoomIdentity
      .translate(width / 2 - target.x * target.k, height / 2 - target.y * target.k)
      .scale(target.k)
    if (duration === 0) select(canvas).call(behaviour.transform, transform)
    else select(canvas).transition().duration(duration).call(behaviour.transform, transform)
  }, [])

  // Size the canvas to its container. **No size, no work**: the map sits
  // behind `display: none` wherever the List view is the default, and the old
  // graph fell back to 800×600 and ran its whole simulation there.
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
      setSized(rect.width > 0 && rect.height > 0)
      if (focused.current) centreOn(focused.current, 0)
      else if (!userMoved.current) fit()
      requestDraw()
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(wrapper)
    return () => observer.disconnect()
  }, [fit, centreOn, requestDraw])

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') requestDraw()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [requestDraw])

  useEffect(() => {
    const wrapper = wrapperRef.current
    if (!wrapper || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(([entry]) => {
      onScreen.current = entry?.isIntersecting ?? true
      if (onScreen.current) requestDraw()
    })
    observer.observe(wrapper)
    return () => observer.disconnect()
  }, [requestDraw])

  // Permanent labels at every width, but fewer below `lg`, where the canvas
  // is small.
  useEffect(() => {
    const query = window.matchMedia('(min-width: 1024px)')
    const update = () => setLabelBudget(query.matches ? 18 : 8)
    update()
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  useEffect(
    () => () => {
      if (frame.current) cancelAnimationFrame(frame.current)
      if (idleTimer.current) clearTimeout(idleTimer.current)
    },
    []
  )

  // ── the layout ────────────────────────────────────────────────────────────

  useEffect(() => {
    if (!sized) return
    const worker = new Worker(new URL('@/lib/brain/layout.worker.ts', import.meta.url), {
      type: 'module',
    })
    const generation = map.concepts.length * 1_000_003 + map.sources.length
    worker.onmessage = (event: MessageEvent<LayoutResponse>) => {
      if (event.data.generation !== generation) return
      setScene({ map, layout: event.data.layout })
      worker.terminate()
    }
    worker.postMessage({ type: 'layout', map, generation } satisfies LayoutRequest)
    return () => worker.terminate()
  }, [map, sized])

  // On first load pulses run inward — orbit to cloud to ring — once. It is the
  // one moment the picture says what it is. From a cited answer they run from
  // the cited sources instead.
  const previousSources = useRef<Set<number> | null>(null)
  useEffect(() => {
    if (!scene) return
    const now = performance.now()
    const reduced = live.current.reducedMotion
    if (!entered.current) {
      entered.current = true
      // While a build is growing the map there is no entrance: the growth is.
      if (!reduced && !live.current.still) {
        pulses.current =
          cited && lit
            ? selectionPulses(scene.map, scene.layout, lit, now)
            : entrancePulses(scene.map, scene.layout, now)
      }
    } else if (!reduced && previousSources.current) {
      // A source that has just arrived — ingested in a build, or added by its
      // owner — sends one pulse inward down each of its dendrites.
      const known = previousSources.current
      const arrived = scene.map.sources.filter((source) => !source.pending && !known.has(source.id))
      if (arrived.length) {
        pulses.current = [
          ...pulses.current,
          ...arrivalPulses(scene.map, scene.layout, new Set(arrived.map((s) => s.id)), now),
        ]
      }
    }
    previousSources.current = new Set(
      scene.map.sources.filter((source) => !source.pending).map((source) => source.id)
    )
    requestDraw()
  }, [scene, lit, cited, requestDraw])

  // One-off effects from the build log, each fired once.
  const firedBursts = useRef<Set<string> | null>(null)
  useEffect(() => {
    if (!scene) return
    // The first frame already holds everything before it — a replayed prefix
    // on a reconnect or a mid-build page load — so those fire nothing.
    if (firedBursts.current === null) {
      firedBursts.current = new Set((bursts ?? []).map((burst) => burst.key))
      return
    }
    if (!bursts?.length || live.current.reducedMotion) return
    const now = performance.now()
    const fired = firedBursts.current
    const fresh = bursts.filter((burst) => !fired.has(burst.key))
    if (!fresh.length) return
    for (const burst of fresh) fired.add(burst.key)
    pulses.current = [...pulses.current, ...burstPulses(scene.map, scene.layout, fresh, now)]
    requestDraw()
  }, [bursts, scene, requestDraw])

  // ── pan, pinch, wheel ─────────────────────────────────────────────────────

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const behaviour = zoom<HTMLCanvasElement, unknown>()
      .scaleExtent([0.08, 8])
      .on('zoom', (event: D3ZoomEvent<HTMLCanvasElement, unknown>) => {
        zoomState.current = { k: event.transform.k, x: event.transform.x, y: event.transform.y }
        requestDraw()
      })
      .on('start', (event: D3ZoomEvent<HTMLCanvasElement, unknown>) => {
        // A real gesture (not a programmatic fit or focus) hands the view over.
        if (event.sourceEvent) {
          userMoved.current = true
          focused.current = null
          engageNow()
        }
        gesture.current = true
        requestDraw()
      })
      .on('end', () => {
        gesture.current = false
        requestDraw()
      })
    zoomBehaviour.current = behaviour
    const target = select(canvas)
    target.call(behaviour)
    // A double tap is a tap twice here, not a zoom.
    target.on('dblclick.zoom', null)
    fit()
    return () => {
      target.on('.zoom', null)
      zoomBehaviour.current = null
    }
  }, [requestDraw, engageNow, fit])

  // ── hit-testing ───────────────────────────────────────────────────────────

  const hitAt = useCallback(
    (clientX: number, clientY: number): Hit | null => {
      const canvas = canvasRef.current
      const state = live.current
      if (!canvas || !state.layout) return null
      const rect = canvas.getBoundingClientRect()
      const view = currentView()
      const [x, y] = unproject(clientX - rect.left, clientY - rect.top, view)
      // Slack in screen pixels, in layout units at this zoom, so a target stays
      // thumb-sized at every zoom level.
      return hitTest(state.map, state.layout, x, y, 8 / view.k)
    },
    [currentView]
  )

  useImperativeHandle(
    handleRef,
    () => ({
      engage: engageNow,
      focus: (target: BrainSelection) => {
        const canvas = canvasRef.current
        const behaviour = zoomBehaviour.current
        const state = live.current
        const hit = hitFor(state.map, target)
        if (!canvas || !behaviour || !state.layout || !hit) return
        engageNow()
        const [x, y] = hitPoint(state.layout, hit)
        // Framed on the flat map at rest, which is where the flatten is going.
        const k = Math.max(zoomState.current.k, fitScale.current * 1.3)
        userMoved.current = true
        focused.current = { x, y, k }
        centreOn(focused.current, state.reducedMotion ? 0 : 320)
      },
      zoomBy: (factor: number) => {
        const canvas = canvasRef.current
        const behaviour = zoomBehaviour.current
        if (!canvas || !behaviour) return
        engageNow()
        // The reader's own zoom, like a wheel: a resize no longer refits it.
        userMoved.current = true
        focused.current = null
        const target = select(canvas)
        if (live.current.reducedMotion) target.call(behaviour.scaleBy, factor)
        else target.transition().duration(200).call(behaviour.scaleBy, factor)
      },
      reset: () => {
        engageNow()
        userMoved.current = false
        focused.current = null
        fit()
      },
    }),
    [engageNow, centreOn, fit]
  )

  return (
    <div
      ref={wrapperRef}
      className={cn('relative h-full w-full overflow-hidden', className)}
      onDragOver={
        onDropFile
          ? (event) => {
              if (event.dataTransfer.types.includes('Files')) event.preventDefault()
            }
          : undefined
      }
      onDrop={
        onDropFile
          ? (event) => {
              const file = event.dataTransfer.files[0]
              if (!file) return
              event.preventDefault()
              onDropFile(file)
            }
          : undefined
      }
    >
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={mapSummary(map)}
        // Every gesture belongs to the map.
        className="h-full w-full touch-none"
        onPointerMove={(event) => {
          if (event.pointerType === 'mouse') engageNow()
          const hit = hitAt(event.clientX, event.clientY)
          if (hitKey(hit) !== hitKey(hovered.current)) {
            hovered.current = hit
            if (canvasRef.current) {
              canvasRef.current.style.cursor = hit && interactive ? 'pointer' : ''
            }
            requestDraw()
          }
        }}
        onPointerDown={engageNow}
        onPointerLeave={() => {
          if (hovered.current !== null) {
            hovered.current = null
            requestDraw()
          }
        }}
        onClick={(event) => {
          if (!interactive) return
          const hit = hitAt(event.clientX, event.clientY)
          onSelect(hit ? selectionFor(live.current.map, hit) : null)
        }}
      />
      {/* The nucleus: the expert itself, over the canvas centre. Decorative
          here — the page's heading names the expert. */}
      <div
        ref={nucleusRef}
        aria-hidden="true"
        className="pointer-events-none absolute top-0 left-0 grid place-items-center transition-opacity duration-(--dur-2)"
        style={{ transform: 'translate(-9999px, -9999px)' }}
      >
        <div className="absolute size-36 rounded-full bg-[radial-gradient(circle,var(--fg-4)_0%,transparent_65%)] opacity-40" />
        <Avatar expert={expert} size={44} className="relative" eager />
      </div>
    </div>
  )
}

/** The spine's glow, pre-rendered once per theme and drawn with `drawImage`. */
function glowSprite(
  cache: React.RefObject<{ colour: string; sprite: HTMLCanvasElement } | null>,
  colour: string
): HTMLCanvasElement | null {
  if (cache.current?.colour === colour) return cache.current.sprite
  const sprite = document.createElement('canvas')
  sprite.width = sprite.height = 64
  const context = sprite.getContext('2d')
  if (!context) return null
  const gradient = context.createRadialGradient(32, 32, 0, 32, 32, 32)
  gradient.addColorStop(0, colour)
  gradient.addColorStop(1, 'transparent')
  context.fillStyle = gradient
  context.globalAlpha = 0.6
  context.fillRect(0, 0, 64, 64)
  cache.current = { colour, sprite }
  return sprite
}
