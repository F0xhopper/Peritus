'use client'

import { useEffect, useRef, useState } from 'react'

import { cn } from '@/lib/cn'
import { usePrefersReducedMotion } from '@/hooks/use-media-query'

/**
 * The hero: a real build log, replaying.
 *
 * Captured from an actual build rather than written as marketing copy, which is
 * the whole point — the claim is "we show you what we threw away", and the
 * evidence is a log with drop reasons and scores in it.
 *
 * Three behaviours that keep it from being an annoyance:
 *
 * - Intervals are compressed about 8×, so twenty seconds covers a build that
 *   took minutes, then it holds on the last frame rather than looping.
 * - It pauses off-screen via `IntersectionObserver`. A timer running behind the
 *   FAQ is pure battery drain.
 * - Under reduced motion it renders the **final frame immediately**, with no
 *   animation at all.
 */

interface ReplayRow {
  /** Milliseconds after the previous row, already compressed. */
  after: number
  kind: 'stage' | 'keep' | 'drop' | 'info' | 'ok'
  stage: string
  text: string
  scores?: string
}

const ROWS: ReplayRow[] = [
  { after: 0, kind: 'stage', stage: 'plan', text: 'Planning the search' },
  {
    after: 900,
    kind: 'ok',
    stage: 'plan',
    text: '7 key concepts: varroa biology, acaricide resistance, drone brood removal…',
  },
  { after: 500, kind: 'stage', stage: 'discover', text: 'Searching 11 sources' },
  { after: 420, kind: 'info', stage: 'discover', text: 'openalex: 34 candidates from 3 queries' },
  { after: 180, kind: 'info', stage: 'discover', text: 'pubmed: 19 candidates from 2 queries' },
  { after: 160, kind: 'info', stage: 'discover', text: 'web: 28 candidates from 4 queries' },
  { after: 300, kind: 'info', stage: 'discover', text: 'De-duplicated 17 candidates' },
  { after: 340, kind: 'info', stage: 'discover', text: 'Triaged 104 candidates, ranked 41' },
  { after: 460, kind: 'stage', stage: 'validate', text: 'Screening 30 sources' },
  {
    after: 380,
    kind: 'keep',
    stage: 'validate',
    text: 'Varroa destructor and honeybee viral loads: a five-year cohort',
    scores: 'q8.5 r9.0',
  },
  {
    after: 240,
    kind: 'drop',
    stage: 'validate',
    text: 'Top 10 beekeeping tips for spring — secondary commentary, no primary data',
    scores: 'q2.5 r4.0',
  },
  {
    after: 260,
    kind: 'keep',
    stage: 'validate',
    text: 'Amitraz resistance in field populations, 2019–2024',
    scores: 'q8.0 r8.5',
  },
  {
    after: 220,
    kind: 'drop',
    stage: 'validate',
    text: 'Hive supply catalogue — product listing, not a source',
    scores: 'q1.0 r2.0',
  },
  {
    after: 250,
    kind: 'keep',
    stage: 'validate',
    text: 'Drone brood removal as mechanical control: a randomised trial',
    scores: 'q7.5 r8.5',
  },
  {
    after: 230,
    kind: 'drop',
    stage: 'validate',
    text: 'duplicate of doi:10.1234/varroa-cohort',
    scores: 'q0.0 r0.0',
  },
  { after: 420, kind: 'info', stage: 'validate', text: 'Screening done — kept 21, dropped 9' },
  {
    after: 320,
    kind: 'ok',
    stage: 'discover',
    text: 'Coverage: 1 of 7 concepts still short — searching again',
  },
  {
    after: 300,
    kind: 'info',
    stage: 'discover',
    text: 'New queries from the corpus: "synthetic acaricide rotation efficacy"',
  },
  { after: 380, kind: 'stage', stage: 'chunk', text: 'Reading and indexing 21 sources' },
  { after: 520, kind: 'ok', stage: 'chunk', text: 'Chat ready — 21 sources, 412 passages' },
  { after: 400, kind: 'stage', stage: 'graph', text: 'Extracting concepts' },
  {
    after: 560,
    kind: 'ok',
    stage: 'graph',
    text: 'Graph ready — 187 concepts, 2 judged to disagree',
  },
  { after: 380, kind: 'ok', stage: 'persona', text: 'Voice written — Dr. Marta Belén' },
]

export function BuildLogReplay({ className }: { className?: string }) {
  const reducedMotion = usePrefersReducedMotion()
  const [shown, setShown] = useState(0)
  // Reduced motion shows the final frame: no animation, nothing to wait for.
  //
  // Derived, not seeded into `useState`: `usePrefersReducedMotion` answers
  // `false` during hydration — a media query is not knowable on the server —
  // so an initialiser that read it captured the wrong value, the effect below
  // then declined to advance the count, and the hero rendered **no log at
  // all** for exactly the readers who cannot see it animate.
  const visible = reducedMotion ? ROWS.length : shown
  const [inView, setInView] = useState(false)
  const wrapper = useRef<HTMLDivElement>(null)
  const scroller = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const element = wrapper.current
    if (!element) return
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), {
      threshold: 0.1,
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (reducedMotion || !inView || shown >= ROWS.length) return
    const timer = setTimeout(() => setShown((count) => count + 1), ROWS[shown].after || 120)
    return () => clearTimeout(timer)
  }, [reducedMotion, inView, shown])

  // Follow the tail, as the real log does.
  useEffect(() => {
    const element = scroller.current
    if (element) element.scrollTop = element.scrollHeight
  }, [visible])

  return (
    <div
      ref={wrapper}
      className={cn('overflow-hidden rounded-card border border-border bg-panel', className)}
    >
      <div className="flex h-8 items-center gap-2 border-b border-border-soft px-3">
        <span className="flex gap-1" aria-hidden="true">
          <span className="size-2 rounded-full bg-border" />
          <span className="size-2 rounded-full bg-border" />
          <span className="size-2 rounded-full bg-border" />
        </span>
        <span className="text-xs text-fg-3">
          varroa mite control in temperate beekeeping · standard
        </span>
      </div>
      <div
        ref={scroller}
        aria-label="A recorded build log"
        className="h-[280px] overflow-y-auto px-3 py-2 font-mono text-xs lg:h-[360px]"
      >
        {ROWS.slice(0, visible).map((row, index) => (
          <div
            key={index}
            className={cn(
              'flex items-baseline gap-2 py-0.5 leading-4',
              // Fade and rise per row, and only when it actually animates.
              !reducedMotion &&
                'motion-safe:animate-in motion-safe:duration-(--dur-2) motion-safe:fade-in motion-safe:slide-in-from-bottom-1'
            )}
          >
            <span
              aria-hidden="true"
              className={cn('w-3 shrink-0 text-center', MARK_COLOUR[row.kind])}
            >
              {MARK[row.kind]}
            </span>
            <span className="hidden w-16 shrink-0 text-fg-3 sm:inline">{row.stage}</span>
            <span className={cn('min-w-0 flex-1', TEXT_COLOUR[row.kind])}>{row.text}</span>
            {row.scores && <span className="shrink-0 text-fg-3">{row.scores}</span>}
          </div>
        ))}
        {visible >= ROWS.length && <p className="mt-2 text-fg-3">— end of log —</p>}
      </div>
    </div>
  )
}

const MARK: Record<ReplayRow['kind'], string> = {
  stage: '▸',
  keep: '✓',
  drop: '×',
  info: '·',
  ok: '✓',
}

const MARK_COLOUR: Record<ReplayRow['kind'], string> = {
  stage: 'text-accent',
  keep: 'text-ok',
  drop: 'text-bad',
  info: 'text-fg-3',
  ok: 'text-ok',
}

const TEXT_COLOUR: Record<ReplayRow['kind'], string> = {
  stage: 'text-fg',
  keep: 'text-fg-2',
  drop: 'text-fg-3',
  info: 'text-fg-3',
  ok: 'text-fg-2',
}
