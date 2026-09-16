'use client'

import { useEffect, useState } from 'react'

import { Skeleton } from '@/components/ui/skeleton'
import { STAGE_LABEL } from '@/lib/build/reducer'
import { formatNumber, formatPercent, formatUsd, humanise, plural } from '@/lib/format'
import type { BuildUsage } from '@/lib/api/types'
import { ClientApiError, apiJson } from '@/lib/api/client'

/** What a person paid, in the currency they paid in. */
export interface BuildCredits {
  amount: number
  /** Held while running, spent once done, refunded when the build failed. */
  outcome: 'held' | 'spent' | 'refunded'
}

/** The metering stages, in the build's own stage names. */
const METER_STAGE: Record<string, string> = {
  plan: STAGE_LABEL.plan,
  triage: STAGE_LABEL.discover,
  validation: STAGE_LABEL.validate,
  contextualization: STAGE_LABEL.chunk,
  graph_extraction: STAGE_LABEL.graph,
  persona: STAGE_LABEL.persona,
  other: 'Other',
}

/**
 * What this build actually cost, by stage.
 *
 * Polled rather than server-rendered, because usage arrives *after* the stages
 * that spent it: the endpoint 404s until the job has metered anything, and on a
 * running build the numbers change every minute. Polling stops as soon as the
 * build is terminal and one final read has landed.
 *
 * It leads with what the reader paid — credits, held, spent or refunded — and
 * the provider spend against the cap in one sentence. The per-stage token
 * counts, the discovery forecast and the per-model rows are operator telemetry
 * and sit behind a disclosure: useful, and not the first thing a person who
 * paid in credits needs to decode.
 */
const POLL_MS = 15_000

export function CostPanel({
  slug,
  terminal,
  credits,
}: {
  slug: string
  terminal: boolean
  credits: BuildCredits | null
}) {
  const [usage, setUsage] = useState<BuildUsage | null>(null)
  const [state, setState] = useState<'loading' | 'absent' | 'ready'>('loading')

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const read = async () => {
      try {
        const next = await apiJson<BuildUsage>(
          `/api/experts/${encodeURIComponent(slug)}/build/usage`,
          { cache: 'no-store' }
        )
        if (cancelled) return
        setUsage(next)
        setState('ready')
      } catch (error) {
        if (cancelled) return
        // 404 is an answer, not a failure: this expert has no build job yet.
        // Anything else is a failed poll, and the next one may work — an error
        // state over a transient blip would be worse than showing nothing.
        if (error instanceof ClientApiError && error.status === 404) setState('absent')
      }
      // One more read after the build ends, then stop: the totals are final.
      if (!cancelled && !terminal) timer = setTimeout(read, POLL_MS)
    }

    void read()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [slug, terminal])

  if (state === 'loading') {
    return (
      <div className="space-y-2">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-4/5" />
      </div>
    )
  }

  const creditLine = credits && (
    <div>
      <p className="text-label tracking-[0.04em] text-fg-3 uppercase">Credits</p>
      <p className="mt-1 text-stat leading-none font-medium text-fg">
        {plural(credits.amount, 'credit')}
      </p>
      <p className="mt-1 text-xs text-fg-3">
        {credits.outcome === 'held'
          ? 'Held while the build runs — refunded in full if it fails.'
          : credits.outcome === 'spent'
            ? 'Spent on this build.'
            : 'Refunded — the build did not finish.'}
      </p>
    </div>
  )

  if (state === 'absent' || !usage) {
    return (
      <div className="space-y-4 text-sm">
        {creditLine}
        <p className="text-sm text-fg-3">
          Nothing spent yet. What the build costs appears here as each stage runs.
        </p>
      </div>
    )
  }

  const stages = usage.by_stage ?? []
  const max = stages.reduce((peak, row) => Math.max(peak, row.cost_usd), 0)

  return (
    <div className="space-y-4 text-sm">
      {creditLine}

      <div>
        <p className="text-label tracking-[0.04em] text-fg-3 uppercase">AI provider spend</p>
        <p className="mt-1 text-sm text-fg-2">
          {formatUsd(usage.cost_usd)}
          {usage.spend_cap_usd !== null && <> of a {formatUsd(usage.spend_cap_usd)} cap</>}
          {usage.cap_exceeded_at && <span className="text-bad"> · cap reached</span>}
        </p>
      </div>

      <details className="group">
        <summary className="cursor-pointer text-xs text-fg-3 transition-colors duration-(--dur-1) hover:text-fg-2">
          Details by stage and model
        </summary>
        <div className="mt-3 space-y-4">
      {stages.length > 0 && (
        <div>
          <p className="text-label tracking-[0.04em] text-fg-3 uppercase">By stage</p>
          <ul className="mt-1.5 space-y-1.5">
            {stages.map((row) => (
              <li key={row.stage}>
                <div className="flex items-baseline justify-between gap-2 text-xs">
                  <span className="min-w-0 truncate text-fg-2">
                    {METER_STAGE[row.stage] ?? humanise(row.stage)}
                  </span>
                  <span className="shrink-0 font-mono text-fg-3">{formatUsd(row.cost_usd)}</span>
                </div>
                {/* A 3px bar, scaled by transform so it fills on first paint
                    and never causes layout. */}
                <div className="mt-0.5 h-[3px] overflow-hidden rounded-full bg-raised">
                  <div
                    style={{ transform: `scaleX(${max > 0 ? row.cost_usd / max : 0})` }}
                    className="h-full w-full origin-left rounded-full bg-expert transition-transform duration-(--dur-3) ease-(--ease-out)"
                  />
                </div>
                <p className="mt-0.5 text-xs text-fg-3">
                  {formatNumber(row.calls)} calls · {formatNumber(row.input_tokens)} in ·{' '}
                  {formatNumber(row.output_tokens)} out
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {usage.discovery && (
        <div>
          <p className="text-label tracking-[0.04em] text-fg-3 uppercase">Search budget forecast</p>
          <dl className="mt-1.5 space-y-1 text-xs">
            <div className="flex justify-between gap-2">
              <dt className="text-fg-3">Estimated ingest</dt>
              <dd className="font-mono text-fg-2">
                {formatUsd(usage.discovery.estimated_ingest_usd)}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-fg-3">Actual ingest</dt>
              <dd className="font-mono text-fg-2">{formatUsd(usage.discovery.actual_ingest_usd)}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-fg-3">Forecast off by</dt>
              <dd
                className={
                  usage.discovery.estimator_error !== null && usage.discovery.estimator_error < 0
                    ? 'font-mono text-warn'
                    : 'font-mono text-fg-2'
                }
              >
                {formatPercent(usage.discovery.estimator_error, 1)}
              </dd>
            </div>
          </dl>
          <p className="mt-1.5 text-xs text-fg-3">
            Negative means the forecast was low: the search kept more sources than it expected to
            be able to afford.
          </p>
        </div>
      )}

      {usage.by_model && usage.by_model.length > 0 && (
        <div>
          <p className="text-label tracking-[0.04em] text-fg-3 uppercase">By model</p>
          <ul className="mt-1.5 space-y-1 text-xs">
            {usage.by_model.map((row) => (
              <li key={`${row.provider}:${row.model}:${row.mode}`} className="flex justify-between gap-2">
                <span className="min-w-0 truncate text-fg-3">
                  {row.model}
                  {row.mode === 'batch' && <span className="text-fg-3"> (batched)</span>}
                </span>
                <span className="shrink-0 font-mono text-fg-2">{formatUsd(row.cost_usd)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
        </div>
      </details>
    </div>
  )
}
