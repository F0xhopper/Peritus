'use client'

import { cn } from '@/lib/cn'

/**
 * "Planning → searching → checking coverage → composing".
 *
 * Its own component, and fed from state the answer does not share, so a status
 * change never re-renders the transcript. The text crossfades with a 4px rise;
 * the `key` is what makes React remount and replay the entrance.
 */
export function StatusLine({
  status,
  visible,
  className,
}: {
  status: string | null
  visible: boolean
  className?: string
}) {
  if (!visible || !status) return null
  return (
    <p
      key={status}
      aria-live="polite"
      className={cn(
        'flex items-center gap-2 text-sm text-fg-3',
        'motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-(--dur-2)',
        className,
      )}
    >
      <span aria-hidden="true" className="animate-pulse-dot size-1.5 rounded-full bg-expert" />
      {status}
    </p>
  )
}
