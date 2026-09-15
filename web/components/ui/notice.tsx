import { AlertTriangle, CircleAlert, Info, CircleCheck } from 'lucide-react'

import { cn } from '@/lib/cn'

/**
 * A tinted rounded notice: a failed build, a degraded stage, a 402 denial, a
 * provenance caveat.
 *
 * Tinted at 12% rather than filled, so a red panel does not shout over the
 * content it is annotating, and the icon carries the meaning for anyone who
 * cannot see the tint.
 */
export type NoticeTone = 'bad' | 'warn' | 'info' | 'ok'

const TONES: Record<NoticeTone, { wrap: string; icon: typeof Info }> = {
  bad: { wrap: 'border-bad/30 bg-bad/8 text-bad', icon: CircleAlert },
  warn: { wrap: 'border-warn/30 bg-warn/8 text-warn', icon: AlertTriangle },
  info: { wrap: 'border-info/30 bg-info/8 text-info', icon: Info },
  ok: { wrap: 'border-ok/30 bg-ok/8 text-ok', icon: CircleCheck },
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
      className={cn('rounded-card border px-3 py-2.5', wrap, className)}
    >
      <div className="flex gap-2.5">
        <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          {title && <p className="text-sm font-medium">{title}</p>}
          {children && (
            <div className={cn('text-sm text-fg-2', title && 'mt-1')}>{children}</div>
          )}
          {action && <div className="mt-2.5 flex flex-wrap gap-2">{action}</div>}
        </div>
      </div>
    </div>
  )
}
