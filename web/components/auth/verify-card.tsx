'use client'

import Link from 'next/link'
import { useRef, useState } from 'react'

import { CODE_LENGTH, CodeInput } from '@/components/auth/code-input'
import { FormNotice, useCountdown } from '@/components/auth/auth-parts'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ClientApiError, apiSend, apiVoid, messageFor } from '@/lib/api/client'
import { authHref } from '@/lib/auth/links'

/**
 * Enter an emailed code: a sign-in code (`type="email"`), or the code that
 * confirms a new account (`type="signup"`). The two differ only in words and
 * in which endpoint a resend goes to.
 *
 * The sixth digit submits on its own — nobody should have to press a button
 * after typing a code. A wrong code clears the cells and puts the cursor back
 * in the first one.
 */
const RESEND_COOLDOWN = 30

export type VerifyType = 'email' | 'signup'

const COPY: Record<VerifyType, { title: string; lead: string; action: string }> = {
  email: { title: 'Enter your code', lead: 'We emailed six digits to', action: 'Sign in' },
  signup: {
    title: 'Confirm your email',
    lead: 'To finish creating your account, enter the six digits we emailed to',
    action: 'Confirm',
  },
}

export function VerifyCard({
  email,
  next,
  type = 'email',
}: {
  email: string
  next: string
  type?: VerifyType
}) {
  const [code, setCode] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [cooldownKey, setCooldownKey] = useState(0)
  const [cooldownFrom, setCooldownFrom] = useState(RESEND_COOLDOWN)
  const [resending, setResending] = useState(false)
  // Guards the auto-submit: `onValueComplete` can fire again if the user edits
  // and refills, and a second in-flight verify would burn the one-time code.
  const cells = useRef<HTMLDivElement>(null)
  const attempted = useRef<string | null>(null)
  const copy = COPY[type]

  const verify = async (value: string) => {
    if (value.length !== CODE_LENGTH || attempted.current === value) return
    attempted.current = value
    setSubmitting(true)
    setNotice(null)

    try {
      await apiSend('/api/auth/verify', 'POST', { email, token: value, type })
      // A full navigation, not `router.push`: the session cookies were just
      // set on this response, and `proxy.ts` has to see them on the way in.
      window.location.assign(next)
      return
    } catch (error) {
      if (error instanceof ClientApiError && error.status === 429) {
        setNotice(
          error.retryAfter
            ? `Too many attempts. Try again in ${error.retryAfter}s.`
            : 'Too many attempts. Wait a moment and try again.'
        )
      } else if (error instanceof ClientApiError && error.status !== 0) {
        setNotice(messageFor(error, 'That code is wrong or has expired. Ask for a new one.'))
      } else {
        setNotice('Could not reach Peritus. Check your connection.')
        attempted.current = null
        setSubmitting(false)
        return
      }
      setCode('')
      attempted.current = null
      requestAnimationFrame(() => cells.current?.querySelector<HTMLInputElement>('input')?.focus())
    } finally {
      setSubmitting(false)
    }
  }

  const resend = async () => {
    setResending(true)
    setNotice(null)
    try {
      await apiVoid(type === 'signup' ? '/api/auth/resend' : '/api/auth/otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      setCooldownFrom(RESEND_COOLDOWN)
      setCooldownKey((key) => key + 1)
      setCode('')
      attempted.current = null
    } catch (error) {
      if (error instanceof ClientApiError && error.status === 429) {
        setCooldownFrom(error.retryAfter ?? RESEND_COOLDOWN)
        setCooldownKey((key) => key + 1)
        setNotice('Too many requests — the countdown has been extended.')
        return
      }
      setNotice(messageFor(error, 'Could not send another code.'))
    } finally {
      setResending(false)
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="text-center">
        <CardTitle>{copy.title}</CardTitle>
        <CardDescription>
          {copy.lead} <span className="text-fg-2">{email}</span>.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            void verify(code)
          }}
        >
          <CodeInput
            ref={cells}
            value={code}
            onChange={setCode}
            onComplete={(value) => void verify(value)}
            autoFocus
            label="Six-digit code"
          />
          <Button
            type="submit"
            variant="primary"
            size="lg"
            className="mt-4 w-full"
            loading={submitting}
            disabled={code.length !== CODE_LENGTH}
          >
            {copy.action}
          </Button>
        </form>

        {/* Reserved: an error here must not move Resend out from under a thumb. */}
        <FormNotice notice={notice} className="min-h-[3.75rem] pt-3" />

        <div className="flex items-center justify-between gap-2 text-xs">
          <ResendButton
            key={cooldownKey}
            from={cooldownFrom}
            resending={resending}
            onResend={() => void resend()}
          />
          <Link
            href={
              type === 'signup' ? authHref('/signup', { next }) : authHref('/login/code', { next })
            }
            className="text-fg-3 transition-colors hover:text-fg-2"
          >
            Use a different email
          </Link>
        </div>
        <p className="mt-4 text-xs text-fg-3">
          Nothing arrived? Check spam, or wait a minute before asking again.
        </p>
      </CardContent>
    </Card>
  )
}

function ResendButton({
  from,
  resending,
  onResend,
}: {
  from: number
  resending: boolean
  onResend: () => void
}) {
  const left = useCountdown(from)
  return (
    <button
      type="button"
      onClick={onResend}
      disabled={left > 0 || resending}
      className="inline-flex min-h-(--row-h) items-center text-fg underline-offset-2 transition-opacity duration-(--dur-1) hover:underline disabled:text-fg-4 disabled:no-underline"
    >
      {left > 0 ? `Resend in ${left}s` : resending ? 'Sending…' : 'Resend code'}
    </button>
  )
}
