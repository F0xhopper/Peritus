'use client'

import { Drawer } from '@base-ui/react/drawer'
import { X } from 'lucide-react'
import { usePathname } from 'next/navigation'
import { useEffect, useRef } from 'react'

import { cn } from '@/lib/cn'

/**
 * The one sliding surface: the phone nav drawer, the tablet sidebar drawer, the
 * overlay context panel, and every bottom sheet.
 *
 * Built on Base UI's `Drawer`, which brings the focus trap, the scroll lock,
 * Escape, the swipe-to-dismiss gesture, snap points, and the Android back
 * button — all of it driven by CSS transitions keyed on `data-*` attributes
 * rather than JavaScript timers, so an interrupted open reverses cleanly and
 * `prefers-reduced-motion` is honoured by zeroing `--dur-3` with no branch here.
 *
 * `side="left"` is navigation, `side="bottom"` is context. A bottom sheet takes
 * `snapPoints` so a cited passage can be read at 50% with the answer still
 * visible behind it, which is the whole reason the panel is a sheet and not a
 * full-screen dialog on a phone.
 */

export interface SheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  side?: 'left' | 'bottom' | 'right'
  children: React.ReactNode
  /** Required for the focus trap's accessible name. */
  title: string
  /** Hide the visible title row (the nav drawer supplies its own header). */
  hideTitle?: boolean
  description?: string
  /**
   * Fractions of the viewport height. `[0.5, 0.92]` is the default context
   * sheet; the graph passes `[0.4, 0.92]` so the canvas stays usable.
   */
  snapPoints?: (number | string)[]
  className?: string
  /** A 20px strip on the screen edge that starts the open gesture. */
  swipeToOpen?: boolean
  /**
   * Where focus goes when the sheet closes.
   *
   * Base UI returns focus to its own `Drawer.Trigger`, but every sheet here is
   * opened from a button in another subtree, so the element has to be named or
   * a keyboard user is dropped at the top of the document on Escape.
   */
  finalFocus?: React.RefObject<HTMLElement | null>
}

export function Sheet({
  open,
  onOpenChange,
  side = 'bottom',
  children,
  title,
  hideTitle,
  description,
  snapPoints,
  className,
  swipeToOpen,
  finalFocus,
}: SheetProps) {
  const vertical = side === 'bottom'

  return (
    <Drawer.Root
      open={open}
      onOpenChange={onOpenChange}
      swipeDirection={vertical ? 'down' : side === 'left' ? 'left' : 'right'}
      snapPoints={vertical ? snapPoints : undefined}
    >
      {swipeToOpen && (
        <Drawer.SwipeArea
          className={cn(
            'fixed inset-y-0 z-30 w-5 pan-y md:hidden',
            side === 'left' ? 'left-0' : 'right-0',
          )}
        />
      )}
      <Drawer.Portal>
        {/* Flat 50% black. No blur — it costs a full-screen filter pass on
            every frame of the drag for no legibility gain. */}
        <Drawer.Backdrop
          className={cn(
            'fixed inset-0 z-40 min-h-dvh bg-black',
            'opacity-[calc(0.5*(1-var(--drawer-swipe-progress)))]',
            'transition-opacity duration-(--dur-3) ease-(--ease-out)',
            'data-swiping:duration-0',
            'data-starting-style:opacity-0 data-ending-style:opacity-0',
          )}
        />
        <Drawer.Viewport
          className={cn(
            'fixed inset-0 z-40 flex',
            vertical ? 'items-end justify-center touch-none' : 'items-stretch',
            side === 'left' && 'justify-start',
            side === 'right' && 'justify-end',
          )}
        >
          <Drawer.Popup
            finalFocus={finalFocus}
            className={cn(
              'relative flex min-h-0 flex-col bg-panel text-fg-2 outline-none',
              'transition-transform duration-(--dur-3) ease-(--ease-out)',
              'data-ending-style:duration-[calc(var(--drawer-swipe-strength)*var(--dur-3))]',
              vertical && [
                'w-full max-h-[calc(100dvh-1rem)] rounded-t-panel border-t border-border',
                // The snap offset and the live drag are one transform, so the
                // finger and the sheet never disagree.
                '[transform:translateY(calc(var(--drawer-snap-point-offset)+var(--drawer-swipe-movement-y)))]',
                '[padding-bottom:max(0px,calc(var(--drawer-snap-point-offset)+var(--drawer-swipe-movement-y)))]',
                'data-starting-style:[transform:translateY(calc(100%+2px))]',
                'data-ending-style:[transform:translateY(calc(100%+2px))]',
              ],
              side === 'left' && [
                'h-full w-[85vw] max-w-80 border-r border-border',
                '[transform:translateX(var(--drawer-swipe-movement-x))]',
                'data-starting-style:[transform:translateX(-100%)]',
                'data-ending-style:[transform:translateX(-100%)]',
              ],
              side === 'right' && [
                'h-full w-full max-w-context border-l border-border',
                '[transform:translateX(var(--drawer-swipe-movement-x))]',
                'data-starting-style:[transform:translateX(100%)]',
                'data-ending-style:[transform:translateX(100%)]',
              ],
              className,
            )}
          >
            {vertical && (
              // The drag handle. `touch-none` on the header and `touch-auto` on
              // the content below is what lets the sheet be dragged by its top
              // while its body scrolls normally.
              <div className="shrink-0 touch-none select-none px-4 pt-2.5 pb-3">
                <div className="mx-auto mb-2.5 h-1 w-10 rounded-full bg-border" />
                <SheetHeader title={title} hideTitle={hideTitle} description={description} />
              </div>
            )}
            {!vertical && (
              <div className="shrink-0 px-4 pt-3 pb-2">
                <SheetHeader title={title} hideTitle={hideTitle} description={description} />
              </div>
            )}
            <Drawer.Content
              className={cn(
                'min-h-0 flex-1 touch-auto overflow-y-auto overscroll-contain',
                vertical ? 'px-4 pb-safe-4' : 'px-3 pb-safe-4',
              )}
            >
              {children}
            </Drawer.Content>
            <ClosesOnNavigation onOpenChange={onOpenChange} />
          </Drawer.Popup>
        </Drawer.Viewport>
      </Drawer.Portal>
    </Drawer.Root>
  )
}

function SheetHeader({
  title,
  hideTitle,
  description,
}: {
  title: string
  hideTitle?: boolean
  description?: string
}) {
  return (
    <div className="flex items-start justify-between gap-2">
      <div className="min-w-0">
        <Drawer.Title className={cn('truncate text-sm font-medium text-fg', hideTitle && 'sr-only')}>
          {title}
        </Drawer.Title>
        {description && (
          <Drawer.Description className="mt-0.5 text-xs text-fg-3">{description}</Drawer.Description>
        )}
      </div>
      <Drawer.Close
        aria-label="Close"
        className={cn(
          'grid size-(--icon-btn) shrink-0 place-items-center rounded-row text-fg-3',
          'transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg',
          hideTitle && '-mt-0.5',
        )}
      >
        <X className="size-4" />
      </Drawer.Close>
    </div>
  )
}

/**
 * Any navigation closes the sheet.
 *
 * A drawer left open over the page the user has just navigated to is the single
 * most common drawer bug. Keying on `usePathname` catches every route change,
 * including the Android back gesture.
 *
 * The `openedAt` ref is load-bearing: this component lives inside the popup, so it
 * *mounts when the sheet opens*, and an effect that closed on its first run
 * would shut every sheet in the same frame it appeared. Only a pathname that
 * differs from the one the sheet opened on counts as a navigation.
 */
function ClosesOnNavigation({ onOpenChange }: { onOpenChange: (open: boolean) => void }) {
  const pathname = usePathname()
  const openedAt = useRef(pathname)

  useEffect(() => {
    if (pathname !== openedAt.current) onOpenChange(false)
  }, [pathname, onOpenChange])

  return null
}
