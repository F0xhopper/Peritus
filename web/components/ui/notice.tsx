import { AlertTriangle, CircleAlert, Info, CircleCheck } from 'lucide-react'

import { cn } from '@/lib/cn'

/**
 * A rounded notice: a failed build, a degraded stage, a 402 denial, a
 * provenance caveat.
 *
 * Monochrome (web/AGENTS.md, "Colour"): a panel with a hairline, the stronger
 * hairline for what has gone wrong, and the icon and the words carry the
 * meaning. It used to be tinted red, amber or green at 8%; a notice is the
 * one thing on a page that is *about* its state, and the icon already said it.
 */
export type NoticeTone = 'bad' | 'warn' | 'info' | 'ok'

const TONES: Record<NoticeTone, { wrap: string; icon: typeof Info }> = {
  bad: { wrap: 'border-border bg-panel text-fg', icon: CircleAlert },
  warn: { wrap: 'border-border bg-panel text-fg', icon: AlertTriangle },
  info: { wrap: 'border-border-soft bg-panel text-fg', icon: Info },
  ok: { wrap: 'border-border-soft bg-panel text-fg', icon: CircleCheck },
}

export function Notice({
  tone = 'info',
  title,
  children,
  action,
  className,
}: {
  tone?: NoticeTone
  title?: string
  children?: React.ReactNode
  action?: React.ReactNode
  className?: string
}) {
  const { wrap, icon: Icon } = TONES[tone]
  return (
    <div
      role={tone === 'bad' ? 'alert' : 'status'}
      className={cn('rounded-card border px-3.5 py-3', wrap, className)}
    >
      <div className="flex gap-2.5">
        <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          {title && <p className="text-sm font-medium">{title}</p>}
          {children && <div className={cn('text-sm text-fg-2', title && 'mt-1')}>{children}</div>}
          {action && <div className="mt-2.5 flex flex-wrap gap-2">{action}</div>}
        </div>
      </div>
    </div>
  )
}
