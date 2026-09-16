'use client'

import { cn } from '@/lib/cn'
import { sourceKind } from '@/lib/source-kind'
import { hostOf } from '@/lib/format'
import type { LedgerSource } from '@/lib/api/types'

/**
 * The sources below `md`.
 *
 * Title, kind and host, with the rest of the record in the row's detail sheet —
 * a card list is scanned, not read.
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
    <ul className={cn('space-y-2 transition-opacity duration-(--dur-1)', pending && 'opacity-60')}>
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
              selectedId === source.id ? 'ring-1 ring-fg-3 ring-inset' : 'hover:bg-raised'
            )}
          >
            <span className="block text-sm text-fg-2">{source.title}</span>

            <p className="mt-1 text-xs text-fg-3">
              {sourceKind(source.source_type)}
              {source.url && <> · {hostOf(source.url)}</>}
              {source.passage_count > 0 && <> · {source.passage_count} passages</>}
            </p>
          </button>
        </li>
      ))}
    </ul>
  )
}
