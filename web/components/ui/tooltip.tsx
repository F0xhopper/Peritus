'use client'

import { Tooltip as BaseTooltip } from '@base-ui/react/tooltip'

import { cn } from '@/lib/cn'

/**
 * Tooltips exist from `lg` up only.
 *
 * There is no tap equivalent, by design: the rail's names appear as text in the
 * nav drawer at narrower widths, which is the tap form of the same information.
 * A tooltip that opens on tap fights the tap that was meant to navigate.
 *
 * 300ms delay, none between siblings — so running along the rail reads the
 * names without a stutter, but resting the pointer does not immediately
 * produce one.
 */
export function TooltipProvider({ children }: { children: React.ReactNode }) {
  return (
    <BaseTooltip.Provider delay={300} closeDelay={0}>
      {children}
    </BaseTooltip.Provider>
  )
}

export function Tooltip({
  children,
  content,
  side = 'right',
  className,
}: {
  children: React.ReactElement
  content: React.ReactNode
  side?: 'top' | 'bottom' | 'left' | 'right'
  className?: string
}) {
  return (
    <BaseTooltip.Root>
      <BaseTooltip.Trigger render={children} />
      <BaseTooltip.Portal>
        <BaseTooltip.Positioner side={side} sideOffset={8} className="z-50 hidden lg:block">
          <BaseTooltip.Popup
            className={cn(
              'max-w-64 rounded-chip border border-border bg-raised px-2 py-1 text-xs text-fg-2',
              'shadow-md shadow-black/25',
              'transition-[opacity,transform] duration-(--dur-1) ease-(--ease-out)',
              'data-starting-style:opacity-0 data-ending-style:opacity-0',
              // 2px toward the target, not a slide from far away.
              side === 'right' && 'data-starting-style:-translate-x-0.5',
              side === 'left' && 'data-starting-style:translate-x-0.5',
              side === 'bottom' && 'data-starting-style:-translate-y-0.5',
              side === 'top' && 'data-starting-style:translate-y-0.5',
              className,
            )}
          >
            {content}
          </BaseTooltip.Popup>
        </BaseTooltip.Positioner>
      </BaseTooltip.Portal>
    </BaseTooltip.Root>
  )
}
