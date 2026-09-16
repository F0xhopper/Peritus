'use client'

import { ChevronRight } from 'lucide-react'
import { useId, useState } from 'react'

import { cn } from '@/lib/cn'

/**
 * The one accepted layout animation: `grid-template-rows` from `0fr` to `1fr`.
 *
 * Only for content under roughly 300px tall — the tier picker's options, a
 * collapsed fetcher group, an FAQ answer. Above that the animation is long
 * enough to be a wait rather than a confirmation, and the section should just
 * appear. `--dur-2` becomes 0ms under reduced motion, so it snaps.
 */
export function Collapse({
  open,
  children,
  className,
}: {
  open: boolean
  children: React.ReactNode
  className?: string
}) {
  return (
    <div data-open={open} className={cn('collapse-grid', className)} aria-hidden={!open}>
      <div>{children}</div>
    </div>
  )
}

/** A collapse with its own disclosure row, for a log group or a settings block. */
export function Disclosure({
  summary,
  children,
  defaultOpen = false,
  count,
  className,
}: {
  summary: React.ReactNode
  children: React.ReactNode
  defaultOpen?: boolean
  count?: number
  className?: string
}) {
  const [open, setOpen] = useState(defaultOpen)
  const id = useId()

  return (
    <div className={className}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className="flex h-(--row-h) w-full items-center gap-1.5 rounded-row px-1.5 text-left text-sm text-fg-2 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
      >
        <ChevronRight
          aria-hidden="true"
          className={cn(
            'size-3.5 shrink-0 text-fg-3 transition-transform duration-(--dur-2) ease-(--ease-out)',
            open && 'rotate-90'
          )}
        />
        <span className="min-w-0 flex-1 truncate">{summary}</span>
        {count !== undefined && <span className="text-xs text-fg-3">{count}</span>}
      </button>
      <div id={id}>
        <Collapse open={open}>{children}</Collapse>
      </div>
    </div>
  )
}
