/**
 * The two shapes the Overview is built out of.
 *
 * Kept together, and apart from the page, because they are what makes it read
 * as a document rather than a dashboard: a definition list of `label · value`
 * rows, and prose sections under a heading. Neither knows about an expert.
 */

/** One `label · value` row. Stacks label-over-value below 480px. */
export function Property({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="contents">
      <dt className="text-fg-3 min-[480px]:text-right">{label}</dt>
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
