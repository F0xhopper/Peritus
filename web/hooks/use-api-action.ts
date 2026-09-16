'use client'

import { useRouter } from 'next/navigation'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'

import { messageFor } from '@/lib/api/client'

/**
 * The shape every mutation in this app had written out by hand: disable the
 * button, call the API, toast, refresh the layout, re-enable the button —
 * including on the paths that threw.
 *
 * Twenty-seven sites did this, and the differences between them were not
 * deliberate. Some forgot the `finally`, so a failed action left its button
 * spinning. Some reported "Something went wrong" over an API response that had
 * said exactly what was wrong.
 *
 * `refresh` is on by default because it is right by default: the rail, the
 * sidebar and the counts belong to the server layout, so a mutation that does
 * not refresh leaves the page showing the state before it.
 */
export interface ApiActionOptions<T> {
  /** Toast on success. A function receives what the action returned. */
  success?: string | ((result: T) => string)
  /** Toast on failure, when the API gave no message of its own. */
  error?: string
  /** `router.refresh()` after a success. Default true. */
  refresh?: boolean
  /** Runs after a success, before the refresh — navigate, close a dialog. */
  onSuccess?: (result: T) => void
  /** Handle the failure instead of toasting it (a form with its own error row). */
  onError?: (message: string, error: unknown) => void
}

export function useApiAction<Args extends unknown[], T>(
  action: (...args: Args) => Promise<T>,
  options: ApiActionOptions<T> = {}
): { run: (...args: Args) => Promise<T | undefined>; pending: boolean } {
  const { success, error: fallback = 'Something went wrong.', refresh = true } = options
  const { onSuccess, onError } = options
  const router = useRouter()
  const [pending, setPending] = useState(false)

  const run = useCallback(
    async (...args: Args) => {
      setPending(true)
      try {
        const result = await action(...args)
        if (success) toast.success(typeof success === 'function' ? success(result) : success)
        onSuccess?.(result)
        if (refresh) router.refresh()
        return result
      } catch (err) {
        const message = messageFor(err, fallback)
        if (onError) onError(message, err)
        else toast.error(message)
        return undefined
      } finally {
        // Always: a button left spinning after a failure is the bug this
        // wrapper exists to make impossible.
        setPending(false)
      }
    },
    [action, fallback, onError, onSuccess, refresh, router, success]
  )

  return { run, pending }
}
