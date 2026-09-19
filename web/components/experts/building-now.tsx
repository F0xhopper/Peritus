'use client'

import { ArrowRight } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useState } from 'react'

import { Avatar } from '@/components/identity/avatar'
import { useBuildEvents } from '@/hooks/use-build-events'
import { cn } from '@/lib/cn'
import { formatElapsed } from '@/lib/format'
import { displayName } from '@/lib/persona'
import { TIMELINE } from '@/lib/build/reducer'
import type { ExpertSummary } from '@/lib/api/types'

/**
 * A live card on Home for an expert that is queued or building.
 *
 * Reads the same durable event log the build page does, so the stage here and
 * the log there cannot disagree. The elapsed seconds tick with no motion at
 * all — a number changing is already a change; animating it would make Home
 * restless while a build runs for several minutes.
 *
 * The expert's own Overview shows it too, with a `heading` in place of the
 * avatar and the name — that page is already headed by both, and what it lacked
 * was any way to the build once the expert could answer.
 */
export function BuildingNow({
  expert,
  heading,
  className,
}: {
  expert: ExpertSummary
  /** Replaces the avatar and name, for a page that already shows them. */
  heading?: string
  className?: string
}) {
  const { state, reconnecting } = useBuildEvents(expert.name)
  const elapsed = useElapsed(expert.created_at)

  const stageIndex = state.activeStage ? TIMELINE.findIndex((s) => s.key === state.activeStage) : -1
  const stageLabel =
    stageIndex >= 0 ? TIMELINE[stageIndex].label : state.terminal ? 'Finishing' : 'Waiting to start'
  // A batched build can genuinely run for hours, so the counter is never
  // capped — but past six hours it stops reading as routine progress.
  const slow = elapsed > 6 * 3600
  const detail = slow
    ? 'taking much longer than usual'
    : stageIndex >= 0
      ? state.stages[stageIndex]?.detail
      : undefined

  return (
    <Link
      href={`/experts/${expert.name}/build`}
      className={cn(
        'flex items-center gap-3 rounded-card border border-border-soft bg-panel p-3',
        'transition-colors duration-(--dur-1) hover:bg-raised',
        className
      )}
    >
      {heading ? (
        <span
          aria-hidden="true"
          className="animate-pulse-dot mx-1 size-2 shrink-0 rounded-full bg-warn"
        />
      ) : (
        <span className="relative">
          <Avatar expert={expert} size={32} />
          <span
            aria-hidden="true"
            className="animate-pulse-dot pointer-events-none absolute inset-0 rounded-card ring-2 ring-warn"
          />
        </span>
      )}

      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-fg">
          {heading ?? displayName(expert)}
        </span>
        {/* The stage text crossfades on change; nothing slides. */}
        <span key={stageLabel} className="mt-0.5 flex items-center gap-1.5 text-xs">
          <span className="animate-in text-warn duration-(--dur-2) fade-in">{stageLabel}</span>
          {detail && <span className="truncate text-fg-3">{detail}</span>}
          {reconnecting && <span className="text-fg-3">reconnecting…</span>}
        </span>
      </span>

      <span className="shrink-0 text-xs text-fg-3">{formatElapsed(elapsed)}</span>
      <ArrowRight aria-hidden="true" className="size-3.5 shrink-0 text-fg-4" />

      {state.chatReady && (
        <span className="shrink-0 rounded-chip bg-ok/12 px-1.5 py-0.5 text-xs text-ok">
          Can answer
        </span>
      )}
    </Link>
  )
}

/** Seconds since an ISO timestamp, ticking once a second. */
function useElapsed(since: string): number {
  const [seconds, setSeconds] = useState(() => secondsSince(since))
  useEffect(() => {
    const timer = setInterval(() => setSeconds(secondsSince(since)), 1000)
    return () => clearInterval(timer)
  }, [since])
  return seconds
}

function secondsSince(iso: string): number {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return 0
  return Math.max(0, Math.floor((Date.now() - then) / 1000))
}
