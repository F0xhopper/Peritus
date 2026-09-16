'use client'

import { ArrowRight } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import type { ShareAccept } from '@/lib/api/types'
import { ClientApiError, apiSend, messageFor } from '@/lib/api/client'

/**
 * Open a shared expert: record that this person holds the link, then go to it.
 *
 * A POST from a click, never a side effect of rendering the page — a link
 * preview fetcher or a prefetch must not be able to put an expert in someone's
 * workspace. A 404 here means the link was turned off between the page render
 * and the click, so the page is refreshed into its "not active" state.
 */
export function OpenSharedExpert({ token }: { token: string }) {
  const router = useRouter()
  const [opening, setOpening] = useState(false)

  const open = async () => {
    setOpening(true)
    try {
      const { slug } = await apiSend<ShareAccept>(
        `/api/share/${encodeURIComponent(token)}/accept`,
        'POST'
      )
      router.push(`/experts/${encodeURIComponent(slug)}`)
      // The rail and the sidebar are the app layout's data; without this a
      // cached layout would not list the expert just added.
      router.refresh()
    } catch (error) {
      // 401: not signed in, so sign in and come back here.
      if (error instanceof ClientApiError && error.status === 401) {
        router.push(`/login?next=${encodeURIComponent(`/share/${token}`)}`)
        return
      }
      // 404: the link was turned off between this page rendering and the click,
      // so re-render it into its "not active" state.
      if (error instanceof ClientApiError && error.status === 404) {
        router.refresh()
        return
      }
      toast.error(messageFor(error, 'Could not open that expert. Try again.'))
      setOpening(false)
    }
  }

  return (
    <Button
      variant="primary"
      size="lg"
      loading={opening}
      minWidth={148}
      onClick={() => void open()}
    >
      Open the expert
      <ArrowRight className="size-3.5" />
    </Button>
  )
}
