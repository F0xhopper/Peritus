import Link from 'next/link'

import { Wordmark } from '@/components/marketing/wordmark'

/**
 * The sign-in, sign-up and recovery pages: nothing on the page but the card.
 *
 * `min-h-dvh` rather than `h-dvh`: a 429 countdown or an invite-only notice can
 * make the card taller than a short landscape viewport, and the page has to
 * scroll rather than clip the submit button.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-bg px-6 py-10">
      {/* `min-h` from the row token: the mark itself is 20px, but this is a
          navigation link and has to be thumb-sized on touch. */}
      <Link
        href="/"
        aria-label="Peritus home"
        className="inline-flex min-h-(--row-h) items-center px-2"
      >
        <Wordmark className="h-5" />
      </Link>
      {children}
      <p className="text-center text-xs text-fg-3">
        <Link href="/privacy" className="transition-colors hover:text-fg-3">
          Privacy
        </Link>
        <span aria-hidden="true" className="mx-2">
          ·
        </span>
        <Link href="/terms" className="transition-colors hover:text-fg-3">
          Terms
        </Link>
      </p>
    </div>
  )
}
