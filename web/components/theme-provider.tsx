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
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemes
      attribute="data-theme"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      {children}
    </NextThemes>
  )
}
