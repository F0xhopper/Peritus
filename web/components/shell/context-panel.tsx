'use client'

import { X } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Sheet } from '@/components/shell/sheet'
import { useContextSlot, useShell } from '@/components/shell/shell-context'
import { cn } from '@/lib/cn'
import { useIsDesktop, useIsLaptopUp } from '@/hooks/use-media-query'

/**
 * The right panel, in its three forms.
 *
 * - `xl` and up: an inline `<aside>` in the grid. It appears at once and its
 *   content fades in; there is no layout animation, because animating a grid
 *   column would reflow the centre column on every frame.
 * - `lg`: an overlay sheet from the right with a backdrop.
 * - below `lg`: a bottom sheet at 50% / 92%, so a cited passage can be read
 *   with the answer still visible behind it.
 *
 * The page that publishes the content never learns which of the three it got.
 */
export function ContextPanel() {
  const { content } = useContextSlot()
  const { contextOpen, setContextOpen, closeContext } = useShell()
  const isDesktop = useIsDesktop()
  const isLaptopUp = useIsLaptopUp()

  // The inline form used to render whenever a page had published anything, so
  // its × did nothing: it set `contextOpen`, which only the overlay and sheet
  // read, while the page went on publishing the same selection. Closing now
  // dismisses the inline panel too, until the page next asks for it to open.
  const [dismissed, setDismissed] = useState(false)
  const [wasOpen, setWasOpen] = useState(contextOpen)
  if (contextOpen !== wasOpen) {
    setWasOpen(contextOpen)
    if (contextOpen) setDismissed(false)
  }

  if (!content) return null

  const close = () => {
    setDismissed(true)
    closeContext()
    content.onClose?.()
  }

  if (isDesktop) {
    if (dismissed) return null
    return (
      <aside
        aria-label={content.title}
        className="scroll-col hidden w-context shrink-0 bg-panel xl:block"
      >
        <div className="sticky top-0 z-10 flex h-topbar items-center gap-2 bg-panel px-3">
          <h2 className="min-w-0 flex-1 truncate text-label tracking-[0.04em] text-fg-3 uppercase">
            {content.title}
          </h2>
          <button
            type="button"
            onClick={close}
            aria-label="Close panel"
            className={cn(
              'grid size-(--icon-btn-sm) place-items-center rounded-chip text-fg-3',
              'transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg',
            )}
          >
            <X className="size-3.5" />
          </button>
        </div>
        <div className="p-3">{content.node}</div>
      </aside>
    )
  }

  return (
    <Sheet
      open={contextOpen}
      onOpenChange={(open) => {
        setContextOpen(open)
        if (!open) content.onClose?.()
      }}
      side={isLaptopUp ? 'right' : 'bottom'}
      title={content.title}
      snapPoints={isLaptopUp ? undefined : (content.snapPoints ?? [0.5, 0.92])}
    >
      {content.node}
    </Sheet>
  )
}

/**
 * Publish content into the panel from a page.
 *
 * A component rather than a hook so it can sit in JSX beside the thing it
 * describes — which keeps "what is in the panel right now" next to the
 * selection that drives it, instead of in an effect at the top of the page.
 */
export function ContextSlot({
  title,
  snapPoints,
  onClose,
  children,
  /** Also open the overlay and sheet forms, not just fill the inline one. */
  open = false,
}: {
  title: string
  snapPoints?: number[]
  onClose?: () => void
  children: React.ReactNode
  open?: boolean
}) {
  const { publish } = useContextSlot()
  const { setContextOpen } = useShell()

  // An effect, not a render-time call: publishing writes to the layout's state,
  // and doing that during this component's render is a React error.
  useEffect(() => {
    publish({ title, snapPoints, onClose, node: children })
    return () => publish(null)
  }, [title, snapPoints, onClose, children, publish])

  useEffect(() => {
    if (open) setContextOpen(true)
  }, [open, setContextOpen])

  return null
}
