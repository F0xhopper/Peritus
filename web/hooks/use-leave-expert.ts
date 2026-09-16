'use client'

import { useRouter } from 'next/navigation'

import { useApiAction } from '@/hooks/use-api-action'
import { apiVoid } from '@/lib/api/client'

/**
 * A viewer removes a shared expert from their workspace.
 *
 * Not a delete: the expert, and the viewer's own chats with it, are untouched,
 * and opening the link again brings it back. No confirm for the same reason.
 * The refresh `useApiAction` does by default is what the rail and the sidebar
 * need, since both belong to the layout.
 */
export function useLeaveExpert(slug: string, name: string) {
  const router = useRouter()
  const { run, pending } = useApiAction(
    () =>
      apiVoid(
        `/api/experts/${encodeURIComponent(slug)}/access`,
        { method: 'DELETE' },
        'Could not remove that expert.'
      ),
    {
      success: `Removed ${name}. Open the link again to bring it back.`,
      error: 'Could not remove that expert.',
      onSuccess: () => router.push('/experts'),
    }
  )

  return { leave: run, leaving: pending }
}
