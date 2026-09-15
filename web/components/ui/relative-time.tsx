import { formatDate, formatDateTime, relativeTime } from '@/lib/format'

/**
 * A timestamp rendered as "3m" or "2 Mar".
 *
 * `suppressHydrationWarning` is not papering over a mistake — it is the
 * intended escape hatch for exactly this case. A relative time is computed
 * against `Date.now()`, so the server's value and the client's are different by
 * construction, and React's text-mismatch check has no way to know that is
 * fine. Left unsuppressed it throws a hydration error (#418), and React then
 * discards the server HTML for that whole tree and re-renders it on the client —
 * which on a slow device is a visible flash, and in WebKit was enough to fail
 * the page outright.
 *
 * A `<time>` element with the ISO value in `dateTime` is also the right markup:
 * the exact instant stays machine-readable and available to assistive tech,
 * while the visible text stays the short human form. The `title` gives a mouse
 * user the full date without a tooltip component.
 */
export function RelativeTime({
  iso,
  className,
}: {
  iso: string | null | undefined
  className?: string
}) {
  if (!iso) return <span className={className}>—</span>
  return (
    <time
      dateTime={iso}
      title={formatDateTime(iso)}
      suppressHydrationWarning
      className={className}
    >
      {relativeTime(iso)}
    </time>
  )
}

/**
 * An absolute timestamp — "8 Sep", or "8 Sep, 14:02" with `withTime`.
 *
 * Suppressed for the same reason as the relative form, but for a narrower
 * reason: the text itself is engine-independent (`lib/format.ts` writes the
 * month names out rather than asking `Intl`), yet it is still rendered in
 * *local* time. A server in UTC and a reader in Auckland disagree about which
 * day a late-evening instant falls on, and that disagreement would again be a
 * hydration text mismatch. The `dateTime` attribute carries the exact instant,
 * so nothing is lost by letting the visible text settle on the client.
 */
export function DateText({
  iso,
  withTime = false,
  className,
}: {
  iso: string | null | undefined
  withTime?: boolean
  className?: string
}) {
  if (!iso) return <span className={className}>—</span>
  return (
    <time
      dateTime={iso}
      title={formatDateTime(iso)}
      suppressHydrationWarning
      className={className}
    >
      {withTime ? formatDateTime(iso) : formatDate(iso)}
    </time>
  )
}
