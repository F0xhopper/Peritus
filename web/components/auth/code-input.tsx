'use client'

import { OTPField } from '@base-ui/react/otp-field'

import { cn } from '@/lib/cn'

// Its own module, apart from `auth-parts`: the sign-in page has no code cells,
// and importing OTPField through a shared file put it in that page's bundle —
// enough to push /login past its 200ms blocking-time budget.

export const CODE_LENGTH = 6

/**
 * Six code cells, on Base UI's `OTPField`: `one-time-code` so iOS offers the
 * code from Mail, a numeric keypad, paste filling every cell, arrow and
 * backspace between cells, and `onComplete` on the sixth digit.
 */
export function CodeInput({
  value,
  onChange,
  onComplete,
  autoFocus = false,
  label = 'Six-digit code',
  ref,
  disabled,
}: {
  value: string
  onChange: (value: string) => void
  onComplete?: (value: string) => void
  autoFocus?: boolean
  label?: string
  ref?: React.Ref<HTMLDivElement>
  disabled?: boolean
}) {
  return (
    <OTPField.Root
      ref={ref}
      aria-label={label}
      length={CODE_LENGTH}
      value={value}
      onValueChange={onChange}
      onValueComplete={onComplete ? (next: string) => onComplete(next) : undefined}
      inputMode="numeric"
      validationType="numeric"
      autoComplete="one-time-code"
      disabled={disabled}
      className="flex justify-between gap-1.5"
    >
      {Array.from({ length: CODE_LENGTH }, (_, index) => (
        <OTPField.Input
          key={index}
          autoFocus={autoFocus && index === 0}
          aria-label={index === 0 ? undefined : `Digit ${index + 1} of ${CODE_LENGTH}`}
          className={cn(
            'h-12 w-full max-w-12 min-w-0 rounded-row border border-border bg-raised',
            'text-center font-mono text-base text-fg',
            'transition-colors duration-(--dur-1)',
            'focus:border-expert focus:outline-none',
            'data-filled:bg-border'
          )}
        />
      ))}
    </OTPField.Root>
  )
}
