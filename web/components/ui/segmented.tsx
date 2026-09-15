'use client'

import { cn } from '@/lib/cn'

/**
 * The decision filter on the ledger, and any other two-to-four-way choice.
 *
 * A segmented control at every width — it is the same control on a phone, just
 * with 44px targets from `--row-h`. The active segment is a rounded `--raised`
 * fill that does not slide between options: a sliding pill would animate on
 * every filter change, and the design reserves movement for things appearing.
 */
export interface SegmentedOption<T extends string> {
  value: T
  label: string
  /** Rendered as a tabular number after the label. */
  count?: number | null
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  className,
  label,
}: {
  options: SegmentedOption<T>[]
  value: T
  onChange: (value: T) => void
  className?: string
  label: string
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn('inline-flex items-center gap-0.5 rounded-row bg-panel p-0.5', className)}
    >
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option.value)}
            className={cn(
              // `--row-h`, not the wrapper minus its padding: the segment is
              // what a thumb aims at, so it is the thing that has to clear the
              // 44px floor. The wrapper is then 2px taller on each side.
              'inline-flex h-(--row-h) items-center gap-1.5 rounded-[6px] px-2.5 text-sm',
              'transition-colors duration-(--dur-1)',
              active ? 'bg-raised text-fg' : 'text-fg-3 hover:text-fg-2',
            )}
          >
            {option.label}
            {option.count !== undefined && option.count !== null && (
              <span className={cn('text-xs', active ? 'text-fg-3' : 'text-fg-3')}>
                {option.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
