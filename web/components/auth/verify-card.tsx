'use client'

import { OTPField } from '@base-ui/react/otp-field'
import Link from 'next/link'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Notice } from '@/components/ui/notice'
import { cn } from '@/lib/cn'

/**
 * The six-cell code input.
 *
 * On Base UI's `OTPField`, which already does the things a hand-rolled version
 * gets wrong: `autocomplete="one-time-code"` so iOS offers the code from the
 * Messages notification, a numeric keypad, paste filling every cell, arrow-key
 * and backspace movement between cells, and `onValueComplete` so the sixth
 * digit submits on its own — nobody should have to press a button after typing
 * a code.
 *
 * Cells shrink to 40px below 400px so six of them plus the gaps fit inside the
 * card's gutters on the narrowest phone.
 */
const CODE_LENGTH = 6
const RESEND_COOLDOWN = 30

export function VerifyCard({ email, next }: { email: string; next: string }) {
  const [code, setCode] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [cooldown, setCooldown] = useState(RESEND_COOLDOWN)
  const [resending, setResending] = useState(false)
  // Guards the auto-submit: `onValueComplete` can fire again if the user edits and
  // refills, and a second in-flight verify would burn the one-time code.
  const cells = useRef<HTMLDivElement>(null)
  const attempted = useRef<string | null>(null)

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = setTimeout(() => setCooldown((value) => value - 1), 1000)
    return () => clearTimeout(timer)
  }, [cooldown])

  const verify = async (value: string) => {
    if (value.length !== CODE_LENGTH || attempted.current === value) return
    attempted.current = value
    setSubmitting(true)
    setNotice(null)

    try {
      const res = await fetch('/api/auth/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, token: value }),
      })

      if (res.ok) {
        // A full navigation, not `router.push`: the session cookies were just
        // set on this response, and `proxy.ts` has to see them on the way in.
        window.location.assign(next)
        return
      }

      if (res.status === 429) {
        const seconds = Number(res.headers.get('retry-after'))
        setNotice(
          Number.isFinite(seconds) && seconds > 0
            ? `Too many attempts. Try again in ${seconds}s.`
            : 'Too many attempts. Wait a moment and try again.',
        )
      } else {
        const body = (await res.json().catch(() => null)) as { detail?: unknown } | null
        setNotice(
          typeof body?.detail === 'string'
            ? body.detail
            : 'That code is wrong or has expired. Ask for a new one.',
        )
      }
      // Clear the cells so the next attempt starts from an empty field rather
      // than the user having to select and delete six characters — and put the
      // cursor back in the first cell, not left on the sixth.
      setCode('')
      attempted.current = null
      requestAnimationFrame(() => cells.current?.querySelector<HTMLInputElement>('input')?.focus())
    } catch {
      setNotice('Could not reach Peritus. Check your connection.')
      attempted.current = null
    } finally {
      setSubmitting(false)
    }
  }

  const resend = async () => {
    setResending(true)
    setNotice(null)
    try {
      const res = await fetch('/api/auth/otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      if (res.status === 429) {
        const seconds = Number(res.headers.get('retry-after'))
        setCooldown(Number.isFinite(seconds) && seconds > 0 ? seconds : RESEND_COOLDOWN)
        setNotice('Too many requests — the countdown has been extended.')
      } else if (!res.ok) {
        setNotice('Could not send another code.')
      } else {
        setCooldown(RESEND_COOLDOWN)
        setCode('')
        attempted.current = null
      }
    } catch {
      setNotice('Could not reach Peritus.')
    } finally {
      setResending(false)
    }
  }

  return (
    <div className="w-full max-w-[360px] rounded-panel border border-border bg-panel p-5">
      <h1 className="text-lg font-medium text-fg">Enter your code</h1>
      <p className="mt-1 text-sm text-fg-3">
        We emailed six digits to <span className="text-fg-2">{email}</span>.
      </p>

      <form
        onSubmit={(event) => {
          event.preventDefault()
          void verify(code)
        }}
        className="mt-5"
      >
        <OTPField.Root
          ref={cells}
          aria-label="Six-digit sign-in code"
          length={CODE_LENGTH}
          value={code}
          onValueChange={setCode}
          onValueComplete={(value: string) => void verify(value)}
          inputMode="numeric"
          validationType="numeric"
          autoComplete="one-time-code"
          className="flex justify-between gap-1.5"
        >
          {Array.from({ length: CODE_LENGTH }, (_, index) => (
            <OTPField.Input
              key={index}
              autoFocus={index === 0}
              aria-label={index === 0 ? undefined : `Digit ${index + 1} of ${CODE_LENGTH}`}
              className={cn(
                'h-12 w-full min-w-0 max-w-12 rounded-row border border-border bg-raised',
                'text-center font-mono text-base text-fg',
                'transition-colors duration-(--dur-1)',
                'focus:border-expert focus:outline-none',
                // A filled cell reads as filled without a border change, so
                // the focus ring stays the only thing the eye tracks.
                'data-filled:bg-border',
              )}
            />
          ))}
        </OTPField.Root>

        <Button
          type="submit"
          variant="primary"
          size="lg"
          className="mt-4 w-full"
          loading={submitting}
          disabled={code.length !== CODE_LENGTH}
        >
          Sign in
        </Button>
      </form>

      {/* Reserved, as on the login card: an error here must not move the
          Resend link out from under a thumb. */}
      <div className="min-h-[3.75rem] pt-3">
        {notice && (
          <Notice
            tone="bad"
            className="animate-in fade-in slide-in-from-bottom-1 duration-(--dur-2)"
          >
            {notice}
          </Notice>
        )}
      </div>

      <div className="flex items-center justify-between gap-2 text-xs">
        <button
          type="button"
          onClick={() => void resend()}
          disabled={cooldown > 0 || resending}
          className="text-fg underline-offset-2 transition-opacity duration-(--dur-1) hover:underline disabled:text-fg-4 disabled:no-underline"
        >
          {cooldown > 0 ? `Resend in ${cooldown}s` : resending ? 'Sending…' : 'Resend code'}
        </button>
        <Link href="/login" className="text-fg-3 transition-colors hover:text-fg-2">
          Use a different email
        </Link>
      </div>
    </div>
  )
}
