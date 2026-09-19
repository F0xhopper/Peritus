'use client'

import { ChevronRight } from 'lucide-react'

import { KindIcon } from '@/components/knowledge/kind-icon'
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
            aria-label={`${source.title} — open details`}
            className={cn(
              // Surface, not border — depth comes from the panel step, and the
              // selected card is the one that gains a ring.
              'w-full rounded-card border border-border-soft bg-panel p-3 text-left',
              'transition-colors duration-(--dur-1)',
              selectedId === source.id ? 'ring-1 ring-fg-3 ring-inset' : 'hover:bg-raised'
            )}
          >
            <span className="flex items-start gap-2.5">
              {/* The kind, before the title: what a thumb-scrolled list is
                  sorted by at a glance. */}
              <span className="mt-px grid size-7 shrink-0 place-items-center rounded-chip bg-raised text-fg-3">
                <KindIcon type={source.source_type} />
              </span>
              <span className="min-w-0 flex-1 text-sm text-fg-2">{source.title}</span>
              {/* The card opens a record; the chevron is what says so. */}
              <ChevronRight aria-hidden="true" className="mt-0.5 size-3.5 shrink-0 text-fg-4" />
            </span>

            <p className="mt-1 pl-[2.375rem] text-xs text-fg-3">
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
