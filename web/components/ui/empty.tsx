import { cn } from '@/lib/cn'

/**
 * An empty state: one faint icon, one sentence, one button. Never a paragraph
 * explaining the feature — the sentence says what to do next and the button
 * does it.
 */
export function Empty({
  icon: Icon,
  children,
  action,
  className,
}: {
  icon?: React.ComponentType<{ className?: string }>
  children: React.ReactNode
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-col items-center gap-3 px-6 py-12 text-center', className)}>
      {Icon && <Icon className="size-7 text-fg-4" aria-hidden="true" />}
      <p className="max-w-sm text-sm text-fg-3">{children}</p>
      {action}
    </div>
  )
}
