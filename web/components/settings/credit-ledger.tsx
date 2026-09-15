'use client'

import { cn } from '@/lib/cn'
import { formatUsd, humanise } from '@/lib/format'
import { DateText } from '@/components/ui/relative-time'
import type { LedgerEntry } from '@/lib/api/types'

/**
 * The credit history.
 *
 * A table at `md` and up, a card list below — a container-query component, so
 * it is right inside the 560px settings column and would be right in a wider
 * one without either caller knowing.
 *
 * `real cost` is the provider spend the build actually metered, next to the
 * credits it consumed. The two are deliberately shown together: credits are a
 * price, dollars are the cost, and only the pair says whether the price is
 * sane.
 */
export function CreditLedger({
  entries,
  className,
}: {
  entries: LedgerEntry[]
  className?: string
}) {
  return (
    <div className={cn('container-row', className)}>
      {/* Table form. */}
      <div className="hidden overflow-x-auto rounded-card bg-panel @md:block">
        <table className="w-full text-sm">
          <thead>
            <tr>
              {['When', 'What', 'Credits', 'Tier', 'Real cost'].map((label, index) => (
                <th
                  key={label}
                  scope="col"
                  className={cn(
                    'border-b border-border px-2 py-1.5 text-label tracking-[0.04em] text-fg-3 uppercase whitespace-nowrap',
                    index >= 2 ? 'text-right' : 'text-left',
                  )}
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr key={entry.id} className="h-(--table-row-h)">
                <td className="border-b border-border-soft px-2 whitespace-nowrap text-fg-3">
                  <DateText iso={entry.created_at} withTime />
                </td>
                <td className="border-b border-border-soft px-2">
                  <span className="text-fg-2">{humanise(entry.entry_type)}</span>
                  {entry.reason && (
                    <span className="ml-1.5 text-xs text-fg-3">{entry.reason}</span>
                  )}
                  {entry.job_id !== null && (
                    <span className="ml-1.5 text-xs text-fg-3">job {entry.job_id}</span>
                  )}
                </td>
                <td
                  className={cn(
                    'border-b border-border-soft px-2 text-right font-mono',
                    entry.delta > 0 ? 'text-ok' : entry.delta < 0 ? 'text-fg-2' : 'text-fg-3',
                  )}
                >
                  {entry.delta > 0 ? `+${entry.delta}` : entry.delta}
                </td>
                <td className="border-b border-border-soft px-2 text-right text-xs text-fg-3">
                  {entry.tier ? humanise(entry.tier) : '—'}
                </td>
                <td className="border-b border-border-soft px-2 text-right font-mono text-xs text-fg-3">
                  {formatUsd(entry.cost_usd)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Card form, below the container's `md`. */}
      <ul className="space-y-2 @md:hidden">
        {entries.map((entry) => (
          <li key={entry.id} className="rounded-card bg-panel p-2.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className="min-w-0 truncate text-sm text-fg-2">
                {humanise(entry.entry_type)}
              </span>
              <span
                className={cn(
                  'shrink-0 font-mono text-sm',
                  entry.delta > 0 ? 'text-ok' : 'text-fg-2',
                )}
              >
                {entry.delta > 0 ? `+${entry.delta}` : entry.delta}
              </span>
            </div>
            <p className="mt-0.5 text-xs text-fg-3">
              <DateText iso={entry.created_at} withTime />
              {entry.tier && <> · {entry.tier}</>}
              {entry.cost_usd !== null && <> · {formatUsd(entry.cost_usd)}</>}
            </p>
            {entry.reason && <p className="mt-1 text-xs text-fg-3">{entry.reason}</p>}
          </li>
        ))}
      </ul>
    </div>
  )
}
