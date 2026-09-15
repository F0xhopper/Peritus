import { cn } from '@/lib/cn'

/**
 * A filled chip, used for exactly two things: a citation marker `[n]` and the
 * ledger's decision column. Everything else that might want a chip gets
 * coloured text instead (web-design.md §3), which is why this has no variant
 * for "tag" or "label".
 */
export function Chip({
  children,
  tone = 'neutral',
  className,
}: {
  children: React.ReactNode
  tone?: 'neutral' | 'ok' | 'bad' | 'warn' | 'expert'
  className?: string
}) {
  return (
    <span
      className={cn(
        'inline-flex h-(--chip-h) shrink-0 items-center rounded-chip px-1.5 text-xs font-medium',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

const TONES = {
  neutral: 'bg-raised text-fg-2',
  ok: 'bg-ok/12 text-ok',
  bad: 'bg-bad/12 text-bad',
  warn: 'bg-warn/12 text-warn',
  expert: 'bg-expert-soft text-expert',
} as const
