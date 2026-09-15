'use client'

import { useEffect } from 'react'

/**
 * Keep `--vv-offset` in step with the software keyboard on iOS.
 *
 * Safari does not resize the layout viewport when the keyboard opens — it
 * resizes the *visual* viewport and scrolls the page under it. `100dvh` is
 * therefore still the full screen height, and a composer pinned to the bottom
 * ends up behind the keyboard. `interactive-widget=resizes-content` fixes this
 * on Android and is ignored here.
 *
 * The offset is written to the document root as a CSS variable rather than
 * returned as state, because the value changes on every frame of the keyboard
 * animation and re-rendering the transcript that many times would drop frames.
 * The composer reads it through `.pb-keyboard`.
 */
export function useVisualViewport() {
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return

    const root = document.documentElement
    let frame = 0

    const update = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        // How much of the layout viewport the keyboard (and any browser chrome
        // overlaying it) is covering. `offsetTop` covers the case where Safari
        // has scrolled the visual viewport down inside the layout one.
        const covered = Math.max(0, root.clientHeight - vv.height - vv.offsetTop)
        // Under a pixel is rounding, not a keyboard; writing it would thrash
        // the variable on every scroll.
        root.style.setProperty('--vv-offset', covered > 1 ? `${Math.round(covered)}px` : '0px')
      })
    }

    update()
    vv.addEventListener('resize', update)
    vv.addEventListener('scroll', update)
    return () => {
      cancelAnimationFrame(frame)
      vv.removeEventListener('resize', update)
      vv.removeEventListener('scroll', update)
      root.style.setProperty('--vv-offset', '0px')
    }
  }, [])
}
