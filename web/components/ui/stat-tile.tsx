import { cn } from '@/lib/cn'

/**
 * The four tiles on Home, and nowhere else.
 *
 * A container-query component: it reads its own width, not the viewport, so the
 * same tile is right in a 2×2 grid on a phone and in a four-across row on a
 * desktop without either caller knowing (web-design.md §8).
 */
export function StatTile({
  label,
  value,
  hint,
  tone,
  className,
}: {
  label: string
  value: string | number
  hint?: string
  tone?: 'ok' | 'warn' | 'bad' | 'info' | 'expert'
  className?: string
}) {
  // A `dl`, because that is what a label and a value are. It also gives the
  // tile a role-based handle that does not collide with the same word used as a
  // heading or a sidebar row elsewhere on the page.
  return (
    <dl className={cn('container-tile rounded-card bg-panel p-3', className)}>
      <dt className="text-label tracking-[0.04em] text-fg-3 uppercase">{label}</dt>
      <dd
        className={cn(
          'mt-1.5 text-stat leading-none font-medium',
          tone ? TONES[tone] : 'text-fg',
        )}
      >
        {value}
      </dd>
      {/* The hint is the first thing to go when the tile is narrow. */}
      {hint && (
        <dd className="mt-1 hidden truncate text-xs text-fg-3 @[9rem]:block">{hint}</dd>
      )}
    </dl>
  )
}

const TONES = {
  ok: 'text-ok',
  warn: 'text-warn',
  bad: 'text-bad',
  info: 'text-info',
  expert: 'text-expert',
} as const
