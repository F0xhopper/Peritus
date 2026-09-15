'use client'

import { useEffect } from 'react'

/**
 * Marks `<body>` as the app shell while an app route is mounted.
 *
 * The attribute (not a class) drives `body[data-shell="app"] { overflow: hidden }`
 * in globals.css. It is set here rather than on the root layout because the
 * marketing pages *do* scroll the window and share that `<body>`, and it is
 * removed on unmount so navigating from the app out to `/privacy` restores
 * normal scrolling.
 */
export function ShellBody() {
  useEffect(() => {
    document.body.dataset.shell = 'app'
    return () => {
      delete document.body.dataset.shell
    }
  }, [])
  return null
}
