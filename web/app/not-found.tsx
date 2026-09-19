import Link from 'next/link'

/**
 * The root 404, for an address outside both the app shell and the marketing
 * pages. Deliberately plain: it has no shell to sit in.
 */
export default function NotFound() {
  return (
    <div className="grid min-h-dvh place-items-center px-6">
      <div className="max-w-sm text-center">
        <p className="font-mono text-sm text-fg-3">404</p>
        <h1 className="mt-2 text-lg font-medium text-fg">Nothing at this address</h1>
        <p className="mt-1.5 text-sm text-fg-3">
          The page may have moved, or the link may be wrong.
        </p>
        <Link
          href="/"
          className="mt-4 inline-flex h-(--btn-lg) items-center rounded-full border border-border px-4 text-sm text-fg-2 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
        >
          Back to the start
        </Link>
      </div>
    </div>
  )
}
