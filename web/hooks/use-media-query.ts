'use client'

import { useCallback, useSyncExternalStore } from 'react'

/**
 * A media query as React state.
 *
 * Built on `useSyncExternalStore` with a **server snapshot of `false`**, which
 * is the whole design constraint: the server cannot know the viewport, so every
 * layout decision has to be made in CSS and this hook may only decide
 * *behaviour* — whether a panel opens as a drawer or sits inline, whether a
 * tooltip or a tap sheet handles a hover affordance.
 *
 * Reading it to choose what to *render* would make the server output wrong at
 * every width and produce a visible jump on hydration. Both forms of a region
 * are in the HTML and toggled with `hidden lg:block`.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia(query)
      list.addEventListener('change', onChange)
      return () => list.removeEventListener('change', onChange)
    },
    [query]
  )

  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false
  )
}

/** The three shell tiers, named so components read as the design does. */
export const BREAKPOINTS = {
  md: '(min-width: 768px)',
  lg: '(min-width: 1024px)',
  xl: '(min-width: 1280px)',
  touch: '(pointer: coarse)',
  reducedMotion: '(prefers-reduced-motion: reduce)',
} as const

export function useIsDesktop() {
  return useMediaQuery(BREAKPOINTS.xl)
}

export function useIsLaptopUp() {
  return useMediaQuery(BREAKPOINTS.lg)
}

export function useIsTabletUp() {
  return useMediaQuery(BREAKPOINTS.md)
}

export function useIsTouch() {
  return useMediaQuery(BREAKPOINTS.touch)
}

export function usePrefersReducedMotion() {
  return useMediaQuery(BREAKPOINTS.reducedMotion)
}
