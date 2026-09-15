'use client'

import { RotateCcw } from 'lucide-react'
import { useEffect } from 'react'

import { Button, ButtonLink } from '@/components/ui/button'
import { Notice } from '@/components/ui/notice'

/**
 * The app shell's error boundary.
 *
 * `retry` (stable since Next 16.3 — it was `unstable_retry` in 16.2) re-fetches
 * and re-renders the boundary's children inside a Transition, so client state
 * *outside* the boundary survives. That is the difference between "try again"
 * and "reload the page".
 *
 * The digest is shown because a server-component error reaches the client as a
 * generic message with an identifier, and that identifier is the only way to
 * find the matching server log.
 */
export default function AppError({
  error,
  retry,
}: {
  error: Error & { digest?: string }
  retry: () => void
}) {
  useEffect(() => {
    console.error('[app]', error)
  }, [error])

  return (
    <div className="flex flex-1 items-center justify-center p-4">
      <div className="w-full max-w-md">
        <Notice tone="bad" title="Something went wrong">
          <p>{error.message || 'The page could not be loaded.'}</p>
          {error.digest && (
            <p className="mt-1.5 font-mono text-xs text-fg-3">digest {error.digest}</p>
          )}
        </Notice>
        <div className="mt-3 flex gap-2">
          <Button variant="primary" onClick={() => retry()}>
            <RotateCcw className="size-3.5" />
            Try again
          </Button>
          <ButtonLink variant="ghost" href="/experts">
            Back to Home
          </ButtonLink>
        </div>
      </div>
    </div>
  )
}
