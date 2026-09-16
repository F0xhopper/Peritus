/**
 * The two shapes the Overview is built out of.
 *
 * Kept together, and apart from the page, because they are what makes it read
 * as a document rather than a dashboard: a definition list of `label · value`
 * rows, and prose sections under a heading. Neither knows about an expert.
 */

/**
 * One `label · value` row.
 *
 * Two columns at every width, including 360px. It used to stack
 * label-over-value below 480px "rather than squeeze two columns into 360px" —
 * but every label here is eight characters or fewer, and the stack turned six
 * properties into twelve lines that took most of a phone's first screen before
 * anything a reader came for. The value wraps instead.
 */
export function Property({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="contents">
      <dt className="text-right text-fg-3">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  )
}

/** A prose section under a heading. */
export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="text-lg font-medium text-fg">{title}</h2>
      <div className="mt-2 space-y-2 text-base leading-relaxed text-fg-2">{children}</div>
    </section>
  )
}
