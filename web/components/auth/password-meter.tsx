'use client'

import { cn } from '@/lib/cn'
import { STRENGTH_LABEL, passwordStrength, type Strength } from '@/lib/auth/password'

// Separate from `PasswordInput` so the sign-in page, which has no meter, does
// not load the strength rules.

const BAR: Record<Strength, string> = {
  0: 'bg-border',
  1: 'bg-bad',
  2: 'bg-warn',
  3: 'bg-ok',
  4: 'bg-ok',
}

/** Four segments and a word. Advisory: it never blocks a submit. */
export function PasswordMeter({ value, email }: { value: string; email?: string | null }) {
  const strength = passwordStrength(value, email)
  if (!value)
    return (
      <p className="min-h-4 text-xs text-fg-3">
        At least 8 characters. A few unrelated words works well.
      </p>
    )
  return (
    <div className="flex min-h-4 items-center gap-2" aria-live="polite">
      <div className="flex flex-1 gap-1" aria-hidden="true">
        {[1, 2, 3, 4].map((segment) => (
          <span
            key={segment}
            className={cn(
              'h-1 flex-1 rounded-full transition-colors duration-(--dur-2)',
              strength >= segment ? BAR[strength] : 'bg-border'
            )}
          />
        ))}
      </div>
      <span className="w-16 text-right text-xs text-fg-3">
        <span className="sr-only">Password strength: </span>
        {STRENGTH_LABEL[strength]}
      </span>
    </div>
  )
}
