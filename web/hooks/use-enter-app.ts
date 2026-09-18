'use client'

import { useCallback, useEffect, useState } from 'react'

/**
 * The hand-off from a sign-in form into the app.
 *
 * A full navigation, not `router.push`: the session cookies were set on the
 * response that just came back, and `proxy.ts` has to see them on the way in.
 * That navigation takes as long as the app's first render — the shell's four
 * API calls — and the form used to drop out of its pending state the moment the
 * sign-in call returned, so for that whole wait the page sat there with an idle
 * button, looking as though nothing had happened. `entering` holds the button
 * in its loading state until the document is replaced.
 *
 * Reset on a back-forward-cache restore, or pressing Back from the app would
 * return to a form spinning forever.
 */
export function useEnterApp() {
  const [entering, setEntering] = useState(false)

  useEffect(() => {
    const reset = (event: PageTransitionEvent) => {
      if (event.persisted) setEntering(false)
    }
    window.addEventListener('pageshow', reset)
    return () => window.removeEventListener('pageshow', reset)
  }, [])

  const enter = useCallback((href: string) => {
    setEntering(true)
    window.location.assign(href)
  }, [])

  return { entering, enter }
}
