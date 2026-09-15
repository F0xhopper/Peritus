'use client'

import { cn } from '@/lib/cn'
import { TIMELINE, type StageState } from '@/lib/build/reducer'

/**
 * The six-segment progress row.
 *
 * Each segment fills left to right with `scaleX` — a transform, so it costs no
 * layout — and the active one carries a 20%-wide sweep that loops. Under
 * reduced motion the sweep becomes a static half-fill (the `.animate-sweep`
 * rule in globals.css), so "in progress" is still visible without movement.
 *
 * On a phone it is a `snap-x` strip with the active segment centred: six labels
 * do not fit across 360px, and shrinking them to fit makes all six unreadable
 * rather than one readable.
 */
export function StageTimeline({
  stages,
  activeStage,
  className,
}: {
  stages: StageState[]
  activeStage: string | null
  className?: string
}) {
  return (
    <ol
      className={cn(
        'flex snap-x snap-mandatory gap-1.5 overflow-x-auto pb-1 md:snap-none md:overflow-visible',
        className,
      )}
    >
      {TIMELINE.map((segment, index) => {
        const state = stages[index] ?? { key: segment.key, progress: 0, status: 'pending' as const }
        const active = activeStage === segment.key
        return (
          <li
            key={segment.key}
            data-snap={active ? 'center' : undefined}
            className={cn(
              'min-w-24 flex-1 shrink-0 snap-center md:min-w-0 md:snap-align-none',
            )}
          >
            <p
              className={cn(
                'mb-1 truncate text-xs transition-colors duration-(--dur-1)',
                state.status === 'done' && 'text-fg-2',
                state.status === 'active' && 'text-fg',
                state.status === 'degraded' && 'text-warn',
                state.status === 'failed' && 'text-bad',
                state.status === 'pending' && 'text-fg-3',
              )}
            >
              {segment.label}
            </p>
            {/* The track. The fill is a scaleX transform on a child, so the
                track's own box never changes and nothing reflows. */}
            <div className="relative h-1 overflow-hidden rounded-full bg-raised">
              <div
                style={{ transform: `scaleX(${state.status === 'failed' ? 1 : state.progress})` }}
                className={cn(
                  'h-full w-full origin-left rounded-full',
                  'transition-transform duration-(--dur-3) ease-(--ease-out)',
                  state.status === 'failed'
                    ? 'bg-bad'
                    : state.status === 'degraded'
                      ? 'bg-warn'
                      : 'bg-expert',
                )}
              />
              {active && state.status === 'active' && (
                <span
                  aria-hidden="true"
                  className="animate-sweep absolute inset-y-0 left-0 w-1/5 bg-expert/60"
                />
              )}
            </div>
            {state.detail && (
              <p className="mt-1 truncate text-xs text-fg-3" title={state.detail}>
                {state.detail}
              </p>
            )}
          </li>
        )
      })}
    </ol>
  )
}
