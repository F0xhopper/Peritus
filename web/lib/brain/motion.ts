/**
 * How the map is looked at: the zoom, and the idle tilt and turn.
 *
 * docs/plans/expert-brain.md, "Motion". One rule: **idle is alive, engaged is
 * still.** The layout is a flat 2D map and never changes. When nobody is
 * touching it, it is *drawn* tilted — y × {@link IDLE_TILT}, so the rings read
 * as ellipses — and the whole scene turns as one rigid body about the nucleus,
 * one revolution in {@link REVOLUTION_MS}. The first sign of someone engaging
 * flattens it and turns it back to rest over {@link FLATTEN_MS}; it stays flat
 * until {@link IDLE_AFTER_MS} pass with no pointer movement and nothing open.
 *
 * Rings never turn against each other: a source sits near the concepts it
 * covers, and rotating one ring would destroy the only thing the angles mean.
 *
 * Pure: every function takes the time it should act at, so the state machine
 * is tested without a clock (`tests/brain-motion.test.ts`).
 */

export const IDLE_TILT = 0.62
export const REVOLUTION_MS = 8 * 60 * 1000
export const FLATTEN_MS = 400
/** A turn back to rest longer than a quarter revolution takes longer than 400ms. */
const FLATTEN_MAX_MS = 900
export const IDLE_AFTER_MS = 6000
/** The idle loop's frame budget: 30fps is plenty for under 5px/s at the rim. */
export const IDLE_FRAME_MS = 1000 / 30

/** Zoom, tilt and turn — everything between a layout point and a pixel. */
export interface View {
  /** d3-zoom's scale and translation. The translation is where the nucleus is. */
  k: number
  x: number
  y: number
  /** 1 is flat; {@link IDLE_TILT} is the idle ellipse. */
  tilt: number
  /** Radians, clockwise on screen. */
  rotation: number
}

export function project(px: number, py: number, view: View): [number, number] {
  const c = Math.cos(view.rotation)
  const s = Math.sin(view.rotation)
  const rx = px * c - py * s
  const ry = (px * s + py * c) * view.tilt
  return [view.x + rx * view.k, view.y + ry * view.k]
}

/** Screen → layout, through the live transform: unzoom, unscale y, unrotate. */
export function unproject(sx: number, sy: number, view: View): [number, number] {
  const lx = (sx - view.x) / view.k
  const ly = (sy - view.y) / view.k / (view.tilt || 1)
  const c = Math.cos(view.rotation)
  const s = Math.sin(view.rotation)
  return [lx * c + ly * s, -lx * s + ly * c]
}

/**
 * How near a layout point is to the viewer, in [-1, 1] (1 is the near rim),
 * times how tilted the view is. Near things are drawn slightly larger and
 * brighter; on a flat map this is 0 everywhere.
 */
export function nearness(px: number, py: number, view: View, radius: number): number {
  const amount = Math.max(0, Math.min(1, (1 - view.tilt) / (1 - IDLE_TILT)))
  if (amount === 0) return 0
  const ry = px * Math.sin(view.rotation) + py * Math.cos(view.rotation)
  return Math.max(-1, Math.min(1, ry / radius)) * amount
}

interface Ease {
  fromTilt: number
  toTilt: number
  fromRotation: number
  toRotation: number
  start: number
  duration: number
}

export interface Motion {
  tilt: number
  rotation: number
  /** Someone is engaging: flat and still until {@link IDLE_AFTER_MS} after the last input. */
  engaged: boolean
  ease: Ease | null
  /** When the idle turn was last advanced. */
  at: number
}

/** Every visit opens on the same frame: tilted, rotation zero. */
export function initialMotion(now: number, reducedMotion: boolean): Motion {
  return {
    tilt: reducedMotion ? 1 : IDLE_TILT,
    rotation: 0,
    engaged: reducedMotion,
    ease: null,
    at: now,
  }
}

/** Flatten and turn back to rest by the shortest way. Idempotent while engaged. */
export function engage(motion: Motion, now: number): Motion {
  const current = advance(motion, now)
  if (current.engaged && (current.ease === null || current.ease.toTilt === 1)) {
    return { ...current, engaged: true }
  }
  const turn = restDelta(current.rotation)
  const duration = Math.min(
    FLATTEN_MAX_MS,
    Math.max(FLATTEN_MS, (Math.abs(turn) / (Math.PI / 2)) * FLATTEN_MS)
  )
  return {
    ...current,
    engaged: true,
    ease: {
      fromTilt: current.tilt,
      toTilt: 1,
      fromRotation: current.rotation,
      toRotation: current.rotation + turn,
      start: now,
      duration,
    },
  }
}

/** Ease back into the idle tilt; the turn resumes from rest. */
export function disengage(motion: Motion, now: number): Motion {
  const current = advance(motion, now)
  if (!current.engaged) return current
  return {
    ...current,
    engaged: false,
    ease: {
      fromTilt: current.tilt,
      toTilt: IDLE_TILT,
      fromRotation: current.rotation,
      toRotation: current.rotation,
      start: now,
      duration: FLATTEN_MS * 2,
    },
  }
}

/** The state at `now`: the ease applied, and the idle turn advanced. */
export function advance(motion: Motion, now: number): Motion {
  let { tilt, rotation, ease } = motion
  if (ease) {
    const t = Math.min(1, Math.max(0, (now - ease.start) / ease.duration))
    const e = easeInOut(t)
    tilt = ease.fromTilt + (ease.toTilt - ease.fromTilt) * e
    rotation = ease.fromRotation + (ease.toRotation - ease.fromRotation) * e
    if (t >= 1) {
      ease = null
      if (motion.engaged) rotation = 0
    }
  } else if (!motion.engaged) {
    rotation += ((now - motion.at) / REVOLUTION_MS) * Math.PI * 2
  }
  return { ...motion, tilt, rotation: wrap(rotation), ease, at: now }
}

/** Whether anything moves on its own — i.e. whether the frame loop must run. */
export function isMoving(motion: Motion): boolean {
  return motion.ease !== null || !motion.engaged
}

/** The shortest turn from `rotation` back to rest (0). */
function restDelta(rotation: number): number {
  const turn = Math.PI * 2
  let delta = -(((rotation % turn) + turn) % turn)
  if (delta < -Math.PI) delta += turn
  return delta
}

function wrap(angle: number): number {
  const turn = Math.PI * 2
  const wrapped = ((angle % turn) + turn) % turn
  return wrapped > Math.PI ? wrapped - turn : wrapped
}

function easeInOut(t: number): number {
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2
}

// ── pulses ──────────────────────────────────────────────────────────────────

/**
 * One dot travelling down a dendrite — the whole "thinking" effect.
 *
 * Endpoints are layout points; the dot follows the same inward-bowed curve the
 * dendrite is drawn with. Never looped: a pulse runs once and is dropped.
 */
export interface Pulse {
  from: [number, number]
  to: [number, number]
  start: number
  duration: number
}

/** 400–700ms, longer for a longer dendrite, so a burst arrives staggered. */
export function pulseDuration(from: [number, number], to: [number, number]): number {
  const length = Math.hypot(to[0] - from[0], to[1] - from[1])
  return 400 + Math.min(300, length * 0.9)
}

/** Pulses still running at `now`, with their progress in [0, 1]. */
export function livePulses(pulses: Pulse[], now: number): { pulse: Pulse; t: number }[] {
  const out: { pulse: Pulse; t: number }[] = []
  for (const pulse of pulses) {
    const t = (now - pulse.start) / pulse.duration
    if (t >= 0 && t <= 1) out.push({ pulse, t })
  }
  return out
}

/** A deterministic sequence in [0, 1) for the idle firing (no `Math.random`). */
export function lcg(seed: number): () => number {
  let state = seed >>> 0 || 1
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0
    return state / 4294967296
  }
}
