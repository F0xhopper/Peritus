'use client'

import { Menu as BaseMenu } from '@base-ui/react/menu'

import { cn } from '@/lib/cn'

/**
 * The row and card overflow menu.
 *
 * Enters with opacity and a 2% scale from the anchor corner and *exits by
 * fading only* — an exit that also moves reads as a second animation the user
 * has to wait through (web-design.md §9).
 */

export const MenuRoot = BaseMenu.Root
export const MenuTrigger = BaseMenu.Trigger

export function MenuContent({
  children,
  className,
  align = 'end',
  side = 'bottom',
}: {
  children: React.ReactNode
  className?: string
  align?: 'start' | 'center' | 'end'
  side?: 'top' | 'bottom' | 'left' | 'right'
}) {
  return (
    <BaseMenu.Portal>
      <BaseMenu.Positioner side={side} align={align} sideOffset={4} className="z-50">
        <BaseMenu.Popup
          className={cn(
            'min-w-44 origin-(--transform-origin) rounded-panel border border-border bg-raised p-1',
            'shadow-lg shadow-black/25 outline-none',
            'transition-[opacity,transform] duration-(--dur-2) ease-(--ease-out)',
            'data-starting-style:scale-[0.98] data-starting-style:opacity-0',
            'data-ending-style:opacity-0 data-ending-style:duration-(--dur-1)',
            className,
          )}
        >
          {children}
        </BaseMenu.Popup>
      </BaseMenu.Positioner>
    </BaseMenu.Portal>
  )
}

export function MenuItem({
  children,
  onClick,
  tone = 'default',
  className,
  disabled,
  closeOnClick = true,
}: {
  children: React.ReactNode
  onClick?: () => void
  tone?: 'default' | 'danger'
  className?: string
  disabled?: boolean
  closeOnClick?: boolean
}) {
  return (
    <BaseMenu.Item
      onClick={onClick}
      disabled={disabled}
      closeOnClick={closeOnClick}
      className={cn(
        'flex h-(--row-h) cursor-default items-center gap-2 rounded-row px-2 text-sm outline-none',
        'transition-colors duration-(--dur-1)',
        tone === 'danger'
          ? 'text-bad data-highlighted:bg-bad/12'
          : 'text-fg-2 data-highlighted:bg-border data-highlighted:text-fg',
        'data-disabled:pointer-events-none data-disabled:opacity-50',
        className,
      )}
    >
      {children}
    </BaseMenu.Item>
  )
}

/** A menu item that navigates. Needs `nativeButton={false}` with `render`. */
export function MenuLinkItem({
  children,
  render,
  className,
}: {
  children: React.ReactNode
  render: React.ReactElement
  className?: string
}) {
  return (
    <BaseMenu.Item
      nativeButton={false}
      render={render}
      className={cn(
        'flex h-(--row-h) items-center gap-2 rounded-row px-2 text-sm text-fg-2 outline-none',
        'transition-colors duration-(--dur-1) data-highlighted:bg-border data-highlighted:text-fg',
        className,
      )}
    >
      {children}
    </BaseMenu.Item>
  )
}

export function MenuSeparator({ className }: { className?: string }) {
  return <BaseMenu.Separator className={cn('my-1 h-px bg-border-soft', className)} />
}

/**
 * A labelled group of items.
 *
 * The `Group` wrapper is not decoration: Base UI's `GroupLabel` throws if it is
 * not inside one, because the label is wired to the group with
 * `aria-labelledby` and a bare label would name nothing. Taking `children` here
 * rather than exposing the two parts separately makes that impossible to get
 * wrong at a call site.
 */
export function MenuLabel({
  children,
  label,
}: {
  /** The items the label describes. */
  children?: React.ReactNode
  label?: React.ReactNode
}) {
  // Called with only a label in a few places, where the following items are
  // siblings rather than children; the group then labels itself and the items
  // read as belonging to it visually.
  return (
    <BaseMenu.Group>
      <BaseMenu.GroupLabel className="px-2 pt-1.5 pb-1 text-label tracking-[0.04em] text-fg-3 uppercase">
        {label ?? children}
      </BaseMenu.GroupLabel>
      {label ? children : null}
    </BaseMenu.Group>
  )
}
