'use client'

import { Orbit, Play } from 'lucide-react'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import { useEffect, useMemo, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { useMediaQuery, usePrefersReducedMotion } from '@/hooks/use-media-query'
import { apiJson } from '@/lib/api/client'
import type { ExpertWithCatalog, MapResponse } from '@/lib/api/types'
import { foldGrow, grownMap, initialGrowState, type GrowState } from '@/lib/brain/grow'
import type { BurstEffect } from '@/lib/brain/scene'

const BrainCanvas = dynamic(
  () => import('@/components/brain/brain-canvas').then((module) => module.BrainCanvas),
  { ssr: false }
)

/**
 * The build as the brain growing (docs/plans/expert-brain-interactive.md, G3–G4).
 *
 * Driven by the same durable log as the rest of the build page, through the
 * growth fold in `lib/brain/grow.ts`: the ring at `plan_ready`, each kept
 * source taking its place on the orbit, specks for candidates as they are
 * judged, sources pulsing as extraction reads them. **The cloud is not drawn
 * until the graph is ready** — which concepts clear the two-source bar is not
 * known before entity resolution — and then the real `/map` replaces the
 * grown one, in the frame the Knowledge page opens on.
 *
 * It stays flat and still for the whole build and tilts into its idle orbit
 * once, when the build is over. Read-only: hover names things, and working on
 * the expert is what the Knowledge page is for.
 *
 * The log, the timeline, the cost panel and every notice stay; this sits above
 * them. From `lg` it is a panel; below, a square capped at 280px with no labels —
 * presence, not a workspace.
 */
export function BuildBrain({
  expert,
  grow,
  finished,
  stage,
}: {
  expert: ExpertWithCatalog
  grow: GrowState
  /** The build is over — succeeded, failed or cancelled. */
  finished: boolean
  /** The current stage in words, announced politely at each boundary. */
  stage: string | null
}) {
  const wide = useMediaQuery('(min-width: 1024px)')
  const reducedMotion = usePrefersReducedMotion()
  const [real, setReal] = useState<MapResponse | null>(null)
  const [replay, setReplay] = useState<GrowState | null>(null)
  const replayTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Once the graph exists the real map is the truth: fetch it, once.
  const wantReal = grow.graphReady || (finished && expert.readiness === 'graph_ready')
  useEffect(() => {
    if (!wantReal) return
    let current = true
    apiJson<MapResponse>(`/api/experts/${encodeURIComponent(expert.name)}/map`)
      .then((map) => {
        // Only a computed map replaces the grown one: fetched a moment early,
        // the graph is not there yet and the answer would be emptier than what
        // the log has already drawn.
        if (current && map.computed) setReal(map)
      })
      .catch(() => {
        /* the grown map stays — it is true as far as it goes */
      })
    return () => {
      current = false
    }
  }, [wantReal, finished, expert.name])

  useEffect(
    () => () => {
      if (replayTimer.current) clearTimeout(replayTimer.current)
    },
    []
  )

  const shown = replay ?? grow
  const map = useMemo(
    () => (replay === null && real ? real : grownMap(shown, expert.name, expert.topic)),
    [replay, real, shown, expert.name, expert.topic]
  )

  // A candidate judged or a batch read, as one-off effects. Replayed prefixes
  // fire nothing: the canvas only fires keys it has not seen, and the first
  // frame it draws already holds the whole prefix.
  const bursts = useMemo<BurstEffect[]>(() => {
    const out: BurstEffect[] = []
    if (!finished || replay) {
      for (const judged of shown.judged) {
        out.push({ key: `j${judged.seq}`, kind: 'judged', passed: judged.passed })
      }
    }
    if (shown.reading) {
      out.push({ key: `r${shown.reading.seq}`, kind: 'read', sourceIds: shown.reading.sourceIds })
    }
    return out
  }, [shown, finished, replay])

  /** The stored events folded again at about thirty times speed (G4). */
  const startReplay = () => {
    if (replayTimer.current) clearTimeout(replayTimer.current)
    const events = grow.log
    if (reducedMotion || events.length === 0) return
    const spacing = Math.max(12, Math.min(60, 20_000 / events.length))
    let i = 0
    let state = initialGrowState()
    setReplay(state)
    const tick = () => {
      // Several events a tick on a long log, so a replay is seconds, not minutes.
      const batch = Math.max(1, Math.round(events.length / 400))
      for (let n = 0; n < batch && i < events.length; n += 1, i += 1) {
        state = foldGrow(state, events[i].seq, events[i].event)
      }
      setReplay(state)
      if (i < events.length) replayTimer.current = setTimeout(tick, spacing)
      else replayTimer.current = setTimeout(() => setReplay(null), 1200)
    }
    replayTimer.current = setTimeout(tick, spacing)
  }

  const hasPlan = map.syllabus.key_concepts.length > 0
  const summary = [
    stage,
    `${map.sources.length} ${map.sources.length === 1 ? 'source' : 'sources'} kept`,
    hasPlan ? `${map.syllabus.key_concepts.length} key concepts` : null,
    !real && grow.conceptsFound > 0 ? `${grow.conceptsFound} concepts found so far` : null,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <section
      aria-label="The expert, growing"
      className="relative mx-auto aspect-square w-full max-w-[280px] shrink-0 overflow-hidden rounded-card bg-panel lg:aspect-auto lg:h-[420px] lg:max-w-none"
    >
      {hasPlan ? (
        <BrainCanvas
          map={map}
          expert={expert}
          selection={null}
          lit={null}
          onSelect={() => undefined}
          interactive={false}
          still={!finished || replay !== null}
          labels={wide}
          bursts={bursts}
        />
      ) : (
        <p className="grid h-full place-items-center p-4 text-center text-xs text-fg-3">
          The map appears when the plan is ready.
        </p>
      )}
      {/* Stage boundaries only, never per event: a live region that speaks on
          every source would be a screen reader reading the log aloud. */}
      <p className="sr-only" aria-live="polite">
        {stage}
      </p>
      <div className="pointer-events-none absolute bottom-2 left-2 hidden max-w-[70%] rounded-row bg-panel/90 px-2 py-1 text-xs text-fg-3 lg:block">
        {summary}
      </div>
      {finished && (
        <div className="absolute top-2 right-2 flex gap-1">
          {grow.placeable && !reducedMotion && (
            <Button
              variant="ghost"
              size="sm"
              onClick={startReplay}
              aria-label="Replay the build"
              className="bg-panel/90"
            >
              <Play className="size-3" />
              <span className="hidden lg:inline">Replay</span>
            </Button>
          )}
          <Link
            href={`/experts/${expert.name}/knowledge?view=map`}
            className="inline-flex h-(--row-h) items-center gap-1.5 rounded-row bg-panel/90 px-2.5 text-xs text-fg-2 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
          >
            <Orbit className="size-3" />
            <span className="hidden lg:inline">Open the map</span>
            <span className="sr-only lg:hidden">Open the map</span>
          </Link>
        </div>
      )}
    </section>
  )
}
