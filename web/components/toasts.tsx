'use client'

import { Toaster } from 'sonner'

import { useMediaQuery } from '@/hooks/use-media-query'

/**
 * Toasts sit bottom-right on desktop and top-centre on phones, where the
 * bottom of the screen belongs to the composer and a toast over it would cover
 * the thing the user is typing into.
 */
export function Toasts() {
  const isPhone = useMediaQuery('(max-width: 767px)')
  return (
    <Toaster
      position={isPhone ? 'top-center' : 'bottom-right'}
      offset={isPhone ? 12 : 20}
      // The palette is ours; sonner's own themes do not know about the tokens.
      toastOptions={{
        classNames: {
          toast:
            'rounded-card border border-border bg-raised text-fg-2 text-sm shadow-lg shadow-black/40',
          title: 'text-fg font-medium',
          description: 'text-fg-3',
          // `--accent`, not `--expert`: a toast is global chrome and can appear
          // over a page that has no expert, where `--expert` is the root
          // fallback rather than anyone's colour.
          actionButton: 'rounded-full bg-accent text-accent-fg text-xs px-2.5 py-1',
          cancelButton: 'rounded-full bg-panel text-fg-3 text-xs px-2.5 py-1',
          error: 'text-bad',
          success: 'text-ok',
        },
      }}
    />
  )
}
