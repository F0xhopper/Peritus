import type { Metadata, Viewport } from 'next'
import { Inter } from 'next/font/google'
import { GeistMono } from 'geist/font/mono'

import { HistoryGuard } from '@/components/history-guard'
import { ThemeProvider } from '@/components/theme-provider'
import { Toasts } from '@/components/toasts'
import { WebVitals } from '@/components/web-vitals'

import './globals.css'

/**
 * `next/font` self-hosts Inter at build time and computes an adjusted fallback
 * metric, so the fallback face occupies the same space as the real one and text
 * never reflows when the webfont lands. That is most of the CLS budget on the
 * marketing pages.
 */
const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-inter',
  adjustFontFallback: true,
})

export const metadata: Metadata = {
  title: {
    default: 'Peritus — experts built from the evidence, with the receipts',
    template: '%s · Peritus',
  },
  description:
    'Peritus builds a subject expert from real sources, records every source it kept and every one it rejected, and answers with citations you can open.',
  applicationName: 'Peritus',
  robots: { index: true, follow: true },
  openGraph: {
    type: 'website',
    siteName: 'Peritus',
    title: 'Peritus — experts built from the evidence, with the receipts',
    description:
      'Type a topic. Peritus searches, screens and cites — and shows you the sources it threw away.',
    images: ['/og.svg'],
  },
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  // `cover` is what unlocks `env(safe-area-inset-*)`, which every pinned
  // bottom element in the app depends on.
  viewportFit: 'cover',
  // Chrome on Android shrinks the layout viewport for the keyboard with this.
  // iOS ignores it and resizes only the visual viewport — see
  // `useVisualViewport`, which is the other half of the keyboard handling.
  interactiveWidget: 'resizes-content',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      // `suppressHydrationWarning` is required by next-themes: it writes
      // `data-theme` on this element before React hydrates, so the server and
      // client markup differ here by design.
      suppressHydrationWarning
      className={`${inter.variable} ${GeistMono.variable} h-full`}
    >
      <body className="min-h-full">
        <HistoryGuard />
        <ThemeProvider>
          {children}
          <Toasts />
        </ThemeProvider>
        <WebVitals />
      </body>
    </html>
  )
}
