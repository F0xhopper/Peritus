import Link from 'next/link'

import { Wordmark } from '@/components/marketing/wordmark'

/**
 * The public pages.
 *
 * The **window** scrolls here, not a grid column — which is the one structural
 * difference from the app shell, and the reason these pages live in their own
 * route group rather than sharing a layout.
 *
 * The bar is opaque on purpose. A translucent one needs `backdrop-filter` to be
 * legible over the hero's light, and that is a full-width filter pass on every
 * scrolled frame of the one page with a performance budget.
 */

const SECTIONS = [
  { href: '/#how', label: 'How it works' },
  { href: '/#record', label: 'The record' },
  { href: '/#depth', label: 'Depth' },
  { href: '/#faq', label: 'Questions' },
]

const FOOTER: { heading: string; links: { href: string; label: string; external?: boolean }[] }[] =
  [
    { heading: 'Product', links: SECTIONS },
    {
      heading: 'Account',
      links: [
        { href: '/login', label: 'Sign in' },
        { href: '/signup', label: 'Create an account' },
      ],
    },
    {
      heading: 'Legal',
      links: [
        { href: '/privacy', label: 'Privacy' },
        { href: '/terms', label: 'Terms' },
        { href: 'https://github.com/', label: 'GitHub', external: true },
      ],
    },
  ]

const mono = 'font-mono text-label tracking-[0.14em] uppercase'

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh bg-bg">
      <header className="sticky top-0 z-30 border-b border-border-soft bg-bg">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-6 px-4 md:px-8">
          <Link
            href="/"
            aria-label="Peritus home"
            className="inline-flex min-h-(--row-h) items-center"
          >
            <Wordmark className="h-6" />
          </Link>
          <nav aria-label="Sections" className="hidden items-center gap-1 lg:flex">
            {SECTIONS.map((section) => (
              <Link
                key={section.href}
                href={section.href}
                className={`${mono} inline-flex h-(--row-h) items-center rounded-full px-3 text-fg-3 transition-colors duration-(--dur-1) hover:text-fg`}
              >
                {section.label}
              </Link>
            ))}
          </nav>
          <nav aria-label="Account" className="ml-auto flex items-center gap-1.5 text-sm">
            <Link
              href="/login"
              className="inline-flex h-(--row-h) items-center rounded-full px-3.5 text-fg-2 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
            >
              Sign in
            </Link>
            <Link
              href="/signup"
              className="inline-flex h-(--row-h) items-center rounded-full bg-accent px-4 font-medium text-accent-fg transition-opacity duration-(--dur-1) hover:opacity-90"
            >
              Sign up
            </Link>
          </nav>
        </div>
      </header>

      <main>{children}</main>

      <footer className="border-t border-border-soft">
        <div className="mx-auto grid w-full max-w-6xl gap-x-8 gap-y-10 px-4 py-14 md:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] md:px-8 md:py-20">
          <div>
            <Wordmark className="h-6" />
            <p className="mk-display mt-6 max-w-[12ch] text-[clamp(1.75rem,3.2vw,2.5rem)] text-fg">
              Experts built from the evidence.
            </p>
          </div>
          {/* 44px tall under a coarse pointer. The landing page's footer is always
              below the fold, so this went unnoticed until the share page — short
              enough to show it on an iPad — put these links on screen. */}
          <div className="grid grid-cols-2 gap-x-8 gap-y-8 sm:grid-cols-3">
            {FOOTER.map((column) => (
              <nav key={column.heading} aria-label={column.heading}>
                <p className={`${mono} text-fg-3`}>{column.heading}</p>
                <div className="mt-3 flex flex-col items-start">
                  {column.links.map((link) =>
                    link.external ? (
                      <a
                        key={link.href}
                        href={link.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex min-h-8 items-center text-sm text-fg-2 transition-colors duration-(--dur-1) hover:text-fg pointer-coarse:min-h-11"
                      >
                        {link.label}
                      </a>
                    ) : (
                      <Link
                        key={link.href}
                        href={link.href}
                        className="inline-flex min-h-8 items-center text-sm text-fg-2 transition-colors duration-(--dur-1) hover:text-fg pointer-coarse:min-h-11"
                      >
                        {link.label}
                      </Link>
                    )
                  )}
                </div>
              </nav>
            ))}
          </div>
        </div>
        <div className="border-t border-border-soft">
          <p className={`${mono} mx-auto w-full max-w-6xl px-4 py-5 text-fg-3 md:px-8`}>
            Peritus — no answer without a citation
          </p>
        </div>
      </footer>
    </div>
  )
}
