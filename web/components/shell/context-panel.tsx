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
 *
 * **Inline from `xl`, though it re-centres the transcript when it opens.** An
 * overlay from 1,280 to 1,535 would hold the text still, and it was tried: it
 * also puts a backdrop over the answer the passage is evidence *for*, at the
 * commonest desktop width there is. Reading the sentence and its passage
 * together is the point of the panel, so the shift stays.
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
  // A dismissal lasts as long as the slot that was dismissed. This component
  // lives in the layout and outlives every page, so without this the flag was
  // for ever: close any panel anywhere, and the build page's Cost panel — which
  // fills the slot without asking it to open — never showed inline again.
  const owner = content?.owner ?? null
  const [seenOwner, setSeenOwner] = useState(owner)
  if (owner !== seenOwner) {
    setSeenOwner(owner)
    setDismissed(false)
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
        // The sidebar's mirror: on the ground, with a hairline against the page.
        className="scroll-col hidden w-context shrink-0 border-l border-border-soft bg-bg xl:block"
      >
        <div className="sticky top-0 z-10 flex h-topbar items-center gap-2 border-b border-border-soft bg-bg px-4">
          <h2 className="min-w-0 flex-1 truncate text-label tracking-[0.04em] text-fg-3 uppercase">
            {content.title}
          </h2>
          <button
            type="button"
            onClick={close}
            aria-label="Close panel"
            className={cn(
              'grid size-(--icon-btn-sm) place-items-center rounded-chip text-fg-3',
              'transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg'
            )}
          >
            <X className="size-3.5" />
          </button>
        </div>
        <div className="p-4">{content.node}</div>
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

let nextOwner = 0

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
  // One number per mount. Not `useId`, which is derived from the position in
  // the tree and so comes back the same when a page is left and returned to.
  const [owner] = useState(() => (nextOwner += 1))

  // An effect, not a render-time call: publishing writes to the layout's state,
  // and doing that during this component's render is a React error.
  useEffect(() => {
    publish({ owner, title, snapPoints, onClose, node: children })
    return () => publish(null)
  }, [owner, title, snapPoints, onClose, children, publish])

  useEffect(() => {
    if (open) setContextOpen(true)
  }, [open, setContextOpen])

  return null
}
