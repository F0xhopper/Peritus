'use client'

import { OTPField } from '@base-ui/react/otp-field'
import { useEffect, useState } from 'react'

import { GoogleMark } from '@/components/auth/google-mark'
import { Notice } from '@/components/ui/notice'
import { cn } from '@/lib/cn'

/**
 * The pieces every sign-in, sign-up and recovery form shares.
 */

/**
 * "Continue with Google" — a plain `<a>`, not a fetch: OAuth is a redirect
 * dance and the browser has to be the thing that travels, and an anchor works
 * before hydration too.
 */
export function GoogleButton({
  href,
  children = 'Continue with Google',
  disabled = false,
}: {
  href: string
  children?: React.ReactNode
  disabled?: boolean
}) {
  return (
    <a
      href={href}
      aria-disabled={disabled || undefined}
      className={cn(
        'flex h-(--btn-lg) w-full items-center justify-center gap-2.5 rounded-row',
        'border border-border text-sm font-medium text-fg',
        'transition-colors duration-(--dur-1) hover:bg-raised',
        disabled && 'pointer-events-none opacity-50'
      )}
    >
      <GoogleMark className="size-4" />
      {children}
    </a>
  )
}

/**
 * The form-level error slot. A reserved `min-h`, so a notice appearing cannot
 * move the controls below it out from under a pointer or a thumb.
 */
export function FormNotice({
  notice,
  retryAfter = null,
  tone = 'bad',
  className,
}: {
  notice: string | null
  retryAfter?: number | null
  tone?: 'bad' | 'ok' | 'info'
  className?: string
}) {
  return (
    <div className={cn('min-h-2', className)}>
      {notice && (
        <Notice
          tone={tone}
          className="animate-in duration-(--dur-2) fade-in slide-in-from-bottom-1"
        >
          {notice}
          {retryAfter !== null && <Countdown key={retryAfter} seconds={retryAfter} />}
        </Notice>
      )}
    </div>
  )
}

/** A live countdown inside a 429 notice, so "wait" has a number on it. */
export function Countdown({ seconds }: { seconds: number }) {
  const left = useCountdown(seconds)
  if (left <= 0) return null
  return <span className="mt-1 block text-xs text-fg-3">Try again in {left}s.</span>
}

/** Seconds remaining from `start`, ticking once a second. Restart by changing `key`. */
export function useCountdown(start: number): number {
  const [left, setLeft] = useState(start)
  useEffect(() => {
    if (left <= 0) return
    const timer = setTimeout(() => setLeft((value) => value - 1), 1000)
    return () => clearTimeout(timer)
  }, [left])
  return left
}

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

/** The dev-mode card: this server has no Supabase, so there is nothing to sign in to. */
export function NoAuthNotice({ onContinue }: { onContinue: () => void }) {
  return (
    <div className="w-full max-w-sm rounded-panel border border-border bg-panel p-5">
      <Notice tone="info" title="This server does not require sign-in">
        It is running in development mode, so every request is the bootstrap admin. Open the app
        directly.
      </Notice>
      <button
        type="button"
        onClick={onContinue}
        className="mt-3 h-(--btn-lg) w-full rounded-row bg-accent text-sm font-medium text-accent-fg"
      >
        Continue
      </button>
    </div>
  )
}
