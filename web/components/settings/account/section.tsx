import { cn } from '@/lib/cn'

/** One Settings section: a heading, a line of explanation, then its controls. */
export function SettingsSection({
  id,
  title,
  description,
  children,
  className,
}: {
  id?: string
  title: string
  description?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section
      id={id}
      className={cn('mt-10 scroll-mt-16', className)}
      aria-labelledby={id && `${id}-title`}
    >
      <h2 id={id && `${id}-title`} className="text-lg font-medium text-fg">
        {title}
      </h2>
      {description && <p className="mt-1 text-sm text-fg-3">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  )
}

/** A label/value row, as the rest of Settings lays them out. */
export function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <dt className="w-28 shrink-0 text-fg-3">{label}</dt>
      <dd className="min-w-0 flex-1 text-fg-2">{children}</dd>
    </div>
  )
}
