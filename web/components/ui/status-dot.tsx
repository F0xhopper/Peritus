import { cn } from '@/lib/cn'
import type { ExpertStatus, Readiness } from '@/lib/api/types'

/**
 * The 8px status dot.
 *
 * Readiness, where it is known, wins over status: an expert that is still
 * "building" but has reached `chat_ready` is answerable *now*, and showing it as
 * merely in-progress hides a usable expert. See the four rules in
 * web-production.md.
 */
export type DotState = 'queued' | 'building' | 'chat-ready' | 'ready' | 'failed' | 'stalled'

/**
 * `buildActive` is the API's `build_active`: whether a job really exists. An
 * expert whose row says queued or building with no job behind it is not
 * building — it stalled, or was built outside the queue — and showing it as
 * live put a five-day "Queued" counter over a working expert. Where the
 * readiness says it can answer, it is simply ready.
 */
export function dotState(
  status: ExpertStatus,
  readiness?: Readiness,
  buildActive?: boolean | null,
): DotState {
  if (status === 'failed') return 'failed'
  if (status === 'ready') return 'ready'
  const answerable = Boolean(readiness && readiness !== 'pending')
  if (buildActive === false) return answerable ? 'ready' : 'stalled'
  if (answerable) return 'chat-ready'
  if (status === 'building') return 'building'
  return 'queued'
}

/** True when a build is genuinely in flight — the rail pulse, Home's "Building now". */
export function isBuilding(expert: {
  status: ExpertStatus
  readiness?: Readiness
  build_active?: boolean | null
}): boolean {
  const state = dotState(expert.status, expert.readiness, expert.build_active)
  return state === 'queued' || state === 'building' || state === 'chat-ready'
}

const STYLES: Record<DotState, { className: string; label: string }> = {
  queued: { className: 'bg-warn/60 animate-pulse-dot', label: 'Waiting to start' },
  building: { className: 'bg-warn animate-pulse-dot', label: 'Building' },
  // Outline, not filled: answerable, but the build is still going.
  'chat-ready': {
    className: 'bg-transparent ring-1 ring-ok ring-inset',
    label: 'Can answer · still building',
  },
  ready: { className: 'bg-ok', label: 'Ready' },
  failed: { className: 'bg-bad', label: 'Build failed' },
  stalled: { className: 'bg-fg-3', label: 'Build never started' },
}

/** The words for a state, for the places that print it beside the dot. */
export function stateLabel(state: DotState): string {
  return STYLES[state].label
}

export function StatusDot({
  state,
  className,
  label,
}: {
  state: DotState
  className?: string
  /** Render the word beside the dot, as coloured text. */
  label?: boolean
}) {
  const style = STYLES[state]
  if (!label) {
    return (
      <span
        role="img"
        aria-label={style.label}
        className={cn('size-2 shrink-0 rounded-full', style.className, className)}
      />
    )
  }
  return (
    <span className={cn('inline-flex items-center gap-1.5', className)}>
      <span aria-hidden="true" className={cn('size-2 shrink-0 rounded-full', style.className)} />
      <span className={cn('text-sm', STATE_TEXT[state])}>{style.label}</span>
    </span>
  )
}

/** Colour as text, not as a filled chip — see web-design.md §3. */
const STATE_TEXT: Record<DotState, string> = {
  queued: 'text-warn',
  building: 'text-warn',
  'chat-ready': 'text-ok',
  ready: 'text-ok',
  failed: 'text-bad',
  stalled: 'text-fg-2',
}

export { STATE_TEXT as statusTextClass }
