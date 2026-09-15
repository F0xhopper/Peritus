import { Link2Off } from 'lucide-react'
import Link from 'next/link'

/**
 * An unknown, reset or turned-off link. One message for all three, on purpose:
 * saying "this link was turned off" would confirm that it once worked.
 */
export default function ShareNotFound() {
  return (
    <div className="mx-auto grid w-full max-w-sm place-items-center px-6 py-20 text-center">
      <Link2Off className="size-7 text-fg-4" aria-hidden="true" />
      <h1 className="mt-3 text-lg font-medium text-fg">This link is not active</h1>
      <p className="mt-1.5 text-sm text-fg-3">
        Its owner may have reset it or stopped sharing, or the link may be incomplete. Ask them
        for a new one.
      </p>
      <Link
        href="/"
        className="mt-5 inline-flex h-(--btn-lg) items-center rounded-row border border-border px-4 text-sm text-fg-2 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
      >
        What is Peritus?
      </Link>
    </div>
  )
}
