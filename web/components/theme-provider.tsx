'use client'

import { ThemeProvider as NextThemes } from 'next-themes'

/**
 * Light and dark, system by default.
 *
 * `attribute="data-theme"` rather than a class, because the token blocks in
 * globals.css key on `[data-theme=dark]` / `[data-theme=light]` and need the
 * "system" case to write *nothing* so `prefers-color-scheme` decides.
 *
 * `disableTransitionOnChange` because the whole palette repaints at once:
 * transitioning it would make every surface on screen crossfade for 200ms,
 * which reads as a glitch rather than a setting taking effect.
 *
 * `scriptProps` marks the anti-flash script as a data block on the client.
 * next-themes renders it everywhere, but only the server copy ever runs; when
 * React creates the element in the browser (any client render of this subtree
 * that is not hydration) it logs "Encountered a script tag while rendering
 * React component" unless the `type` is non-JavaScript. The server still emits
 * a plain script, and the hydrated element keeps it: the script already carries
 * `suppressHydrationWarning`, and React does not patch attributes on hydrate.
 */
const scriptProps = typeof window === 'undefined' ? undefined : { type: 'text/plain' }

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemes
      attribute="data-theme"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      scriptProps={scriptProps}
    >
      {children}
    </NextThemes>
  )
}
