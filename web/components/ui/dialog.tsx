'use client'

import { Dialog as BaseDialog } from '@base-ui/react/dialog'
import { X } from 'lucide-react'

import { Sheet } from '@/components/shell/sheet'
import { cn } from '@/lib/cn'
import { useIsTabletUp } from '@/hooks/use-media-query'

/**
 * A dialog above `md` and a bottom sheet below it, from one call site.
 *
 * Every dialog in the product is adaptive this way (web-design.md §8), so a
 * page never has to know which form it is getting and a destructive confirm
 * lands above the safe area on a phone without the caller arranging it.
 *
 * This is the one place `useMediaQuery` decides what to *render* rather than
 * only how something behaves — and it is safe here because a dialog is closed
 * on first paint. Nothing is in the server HTML to be wrong, so the
 * server snapshot of `false` costs nothing.
 */

export interface DialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  children: React.ReactNode
  /** The action row. Pinned above the safe area in the sheet form. */
  footer?: React.ReactNode
  className?: string
  /** A destructive confirm the user must not dismiss by tapping the backdrop. */
  disablePointerDismissal?: boolean
}

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  className,
  disablePointerDismissal = false,
}: DialogProps) {
  const isTabletUp = useIsTabletUp()

  if (!isTabletUp) {
    return (
      <Sheet open={open} onOpenChange={onOpenChange} side="bottom" title={title} description={description}>
        <div className="pt-1">{children}</div>
        {footer && <div className="sticky bottom-0 mt-4 bg-panel pt-3 pb-safe">{footer}</div>}
      </Sheet>
    )
  }

  return (
    <BaseDialog.Root
      open={open}
      onOpenChange={onOpenChange}
      disablePointerDismissal={disablePointerDismissal}
      modal
    >
      <BaseDialog.Portal>
        <BaseDialog.Backdrop
          className={cn(
            'fixed inset-0 z-40 bg-black/50',
            'transition-opacity duration-(--dur-2) ease-(--ease-out)',
            'data-starting-style:opacity-0 data-ending-style:opacity-0',
            'data-ending-style:duration-(--dur-1)',
          )}
        />
        <BaseDialog.Popup
          className={cn(
            // Anchored by its top edge, not centred. A centred dialog whose
            // content changes height — Add a source's tabs are 60px apart in
            // height — jumps on every switch, and the tab row moves out from
            // under the pointer that just clicked it.
            'fixed top-[max(3rem,12vh)] left-1/2 z-50 w-[calc(100vw-3rem)] max-w-[460px]',
            'max-h-[calc(100dvh-max(3rem,12vh)-1.5rem)] -translate-x-1/2 overflow-y-auto',
            // The only shadowed elements are popovers and the palette, and a
            // dialog reads as one of those.
            'rounded-panel border border-border bg-panel p-4 shadow-xl shadow-black/30 outline-none',
            // Scale and opacity only. Exits fade without moving.
            'transition-[opacity,transform] duration-(--dur-2) ease-(--ease-out)',
            'data-starting-style:scale-[0.98] data-starting-style:opacity-0',
            'data-ending-style:opacity-0 data-ending-style:duration-(--dur-1)',
            className,
          )}
        >
          <div className="mb-3 flex items-start justify-between gap-3">
            <div className="min-w-0">
              <BaseDialog.Title className="text-lg font-medium text-fg">{title}</BaseDialog.Title>
              {description && (
                <BaseDialog.Description className="mt-1 text-sm text-fg-3">
                  {description}
                </BaseDialog.Description>
              )}
            </div>
            <BaseDialog.Close
              aria-label="Close"
              className="grid size-(--icon-btn) shrink-0 place-items-center rounded-row text-fg-3 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
            >
              <X className="size-4" />
            </BaseDialog.Close>
          </div>
          {children}
          {footer && <div className="mt-4 flex justify-end gap-2">{footer}</div>}
        </BaseDialog.Popup>
      </BaseDialog.Portal>
    </BaseDialog.Root>
  )
}

export { BaseDialog }
