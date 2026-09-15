import Link from 'next/link'

import { Wordmark } from '@/components/marketing/wordmark'

/**
 * The public pages.
 *
 * The **window** scrolls here, not a grid column — which is the one structural
 * difference from the app shell, and the reason these pages live in their own
 * route group rather than sharing a layout.
 */
export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh bg-bg">
      <header className="sticky top-0 z-30 border-b border-border-soft bg-bg/95 backdrop-blur-none">
        <div className="mx-auto flex h-14 w-full max-w-5xl items-center gap-4 px-4 md:px-6">
          <Link
            href="/"
            aria-label="Peritus home"
            className="inline-flex min-h-(--row-h) items-center"
          >
            <Wordmark className="h-5" />
          </Link>
          <nav className="ml-auto flex items-center gap-1 text-sm">
            <Link
              href="/#how"
              className="hidden h-(--row-h) items-center rounded-row px-2.5 text-fg-3 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg sm:inline-flex"
            >
              How it works
            </Link>
            <Link
              href="/login"
              className="inline-flex h-(--row-h) items-center rounded-row bg-accent px-3 font-medium text-accent-fg transition-[filter] duration-(--dur-1) hover:brightness-110"
            >
              Sign in
            </Link>
          </nav>
        </div>
      </header>

      <main>{children}</main>

      <footer className="mt-16 border-t border-border-soft">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-6 text-xs text-fg-3 md:px-6">
          <Wordmark className="h-3.5" markOnly />
          <span>Experts built from the evidence.</span>
          {/* 44px tall under a coarse pointer. The landing page's footer is always
              below the fold, so this went unnoticed until the share page — short
              enough to show it on an iPad — put these links on screen. */}
          <nav className="ml-auto flex gap-4 [&>a]:inline-flex [&>a]:items-center pointer-coarse:[&>a]:min-h-11">
            <Link href="/privacy" className="transition-colors hover:text-fg-3">
              Privacy
            </Link>
            <Link href="/terms" className="transition-colors hover:text-fg-3">
              Terms
            </Link>
            <a
              href="https://github.com/"
              target="_blank"
              rel="noopener noreferrer"
              className="transition-colors hover:text-fg-3"
            >
              GitHub
            </a>
          </nav>
        </div>
      </footer>
    </div>
  )
}
