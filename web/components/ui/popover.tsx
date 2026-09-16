'use client'

import { Popover as BasePopover } from '@base-ui/react/popover'

import { cn } from '@/lib/cn'

export const PopoverRoot = BasePopover.Root
export const PopoverTrigger = BasePopover.Trigger

/** A popover, shadowed like a menu. Used for the citation preview at `lg`+. */
export function PopoverContent({
  children,
  className,
  side = 'top',
  align = 'center',
}: {
  children: React.ReactNode
  className?: string
  side?: 'top' | 'bottom' | 'left' | 'right'
  align?: 'start' | 'center' | 'end'
}) {
  return (
    <BasePopover.Portal>
      <BasePopover.Positioner side={side} align={align} sideOffset={6} className="z-50">
        <BasePopover.Popup
          className={cn(
            'max-w-80 origin-(--transform-origin) rounded-panel border border-border bg-raised p-3',
            'text-sm text-fg-2 shadow-lg shadow-black/25 outline-none',
            'transition-[opacity,transform] duration-(--dur-2) ease-(--ease-out)',
            'data-starting-style:scale-[0.98] data-starting-style:opacity-0',
            'data-ending-style:opacity-0 data-ending-style:duration-(--dur-1)',
            className
          )}
        >
          {children}
        </BasePopover.Popup>
      </BasePopover.Positioner>
    </BasePopover.Portal>
  )
}
