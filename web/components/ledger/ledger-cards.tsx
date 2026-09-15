'use client'

import { Chip } from '@/components/ui/chip'
import { cn } from '@/lib/cn'
import { describeDiscovery, sourceKind } from '@/lib/source-kind'
import { formatScore, hostOf } from '@/lib/format'
import type { LedgerSource } from '@/lib/api/types'

/**
 * The ledger below `md`.
 *
 * Carries every field the table does except rubric version and DOI, which live
 * in the row's detail sheet — those two are the only ones nobody scans a list
 * for. The two score bars are horizontal here rather than vertical: a card has
 * width to spare and no column to align to.
 */
export function LedgerCards({
  sources,
  onSelect,
  selectedId,
  pending,
}: {
  sources: LedgerSource[]
  onSelect: (source: LedgerSource) => void
  selectedId: number | null
  pending: boolean
}) {
  return (
    <ul
      className={cn(
        'space-y-2 transition-opacity duration-(--dur-1)',
        pending && 'opacity-60',
      )}
    >
      {sources.map((source) => (
        <li key={source.id}>
          <button
            type="button"
            onClick={() => onSelect(source)}
            className={cn(
              // Surface, not border — depth comes from the panel step, and the
              // selected card is the one that gains a ring.
              'w-full rounded-card bg-panel p-3 text-left',
              'transition-colors duration-(--dur-1)',
              selectedId === source.id ? 'ring-1 ring-fg-3 ring-inset' : 'hover:bg-raised',
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <span className="min-w-0 flex-1 text-sm text-fg-2">{source.title}</span>
              {source.decision === 'accepted' ? (
                <Chip tone="ok">Kept</Chip>
              ) : (
                <Chip tone="bad">Dropped</Chip>
              )}
            </div>

            <p className="mt-1 text-xs text-fg-3">
              {sourceKind(source.source_type)}
              {source.url && <> · {hostOf(source.url)}</>}
              {source.full_text_method === 'abstract' && (
                <> · <span className="text-warn">abstract only</span></>
              )}
            </p>

            <dl className="mt-2 space-y-1.5">
              <ScoreRow
                label="Quality"
                value={source.quality_score}
                accepted={source.decision === 'accepted'}
              />
              <ScoreRow
                label="Relevance"
                value={source.relevance_score}
                accepted={source.decision === 'accepted'}
              />
            </dl>

            {source.drop_reason && (
              <p className="mt-2 text-xs text-fg-3">{source.drop_reason}</p>
            )}
            {source.discovered_via && (
              <p className="mt-1 text-xs text-fg-3">{describeDiscovery(source.discovered_via)}</p>
            )}
          </button>
        </li>
      ))}
    </ul>
  )
}

function ScoreRow({
  label,
  value,
  accepted,
}: {
  label: string
  value: number | null
  accepted: boolean
}) {
  return (
    <div className="flex items-center gap-2">
      <dt className="w-16 shrink-0 text-xs text-fg-3">{label}</dt>
      <dd className="flex min-w-0 flex-1 items-center gap-2">
        <span className="h-1 min-w-0 flex-1 overflow-hidden rounded-full bg-raised">
          <span
            style={{ transform: `scaleX(${value === null ? 0 : Math.min(1, value / 10)})` }}
            className={cn(
              'block h-full w-full origin-left rounded-full',
              accepted ? 'bg-ok' : 'bg-bad',
              'motion-safe:transition-transform motion-safe:duration-(--dur-3) motion-safe:ease-(--ease-out)',
            )}
          />
        </span>
        <span className="w-7 shrink-0 text-right font-mono text-xs text-fg-2">
          {formatScore(value)}
        </span>
      </dd>
    </div>
  )
}
