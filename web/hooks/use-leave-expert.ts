'use client'

import { useRouter } from 'next/navigation'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'

/**
 * A viewer removes a shared expert from their workspace.
 *
 * Not a delete: the expert, and the viewer's own chats with it, are untouched,
 * and opening the link again brings it back. No confirm for the same reason.
 * `router.refresh()` because the rail and the sidebar belong to the layout.
 */
export function useLeaveExpert(slug: string, name: string) {
  const router = useRouter()
  const [leaving, setLeaving] = useState(false)

  const leave = useCallback(async () => {
    setLeaving(true)
    try {
      const res = await fetch(`/api/experts/${encodeURIComponent(slug)}/access`, {
        method: 'DELETE',
      })
      if (!res.ok) throw new Error()
      toast.success(`Removed ${name}. Open the link again to bring it back.`)
      router.push('/experts')
      router.refresh()
    } catch {
      toast.error('Could not remove that expert.')
    } finally {
      setLeaving(false)
    }
  }, [name, router, slug])

  return { leave, leaving }
}
