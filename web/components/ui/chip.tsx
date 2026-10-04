import { cn } from '@/lib/cn'

/**
 * A filled chip, used for exactly two things: a citation marker `[n]` and the
 * ledger's decision column. Everything else that might want a chip gets plain
 * text instead, which is why this has no variant for "tag" or "label".
 *
 * The tones are monochrome (web/AGENTS.md, "Colour"): what is kept is filled,
 * what is dropped is hollow — the fill-against-hairline idiom the map uses for
 * primary and secondary — and the word in the chip says which.
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
        'inline-flex h-(--chip-h) shrink-0 items-center rounded-full px-2 text-xs font-medium',
        TONES[tone],
        className
      )}
    >
      {children}
    </span>
  )
}

const TONES = {
  neutral: 'bg-raised text-fg-2',
  ok: 'bg-raised text-fg',
  bad: 'border border-border text-fg-3',
  warn: 'bg-raised text-fg-2',
  expert: 'bg-expert-soft text-expert',
} as const
