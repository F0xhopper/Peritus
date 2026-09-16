'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'

import { Button } from '@/components/ui/button'
import { FieldError, Input, Label } from '@/components/ui/input'
import { Notice } from '@/components/ui/notice'
import { GoogleMark } from '@/components/auth/google-mark'
import { cn } from '@/lib/cn'
import { z } from '@/lib/validation'
import { ClientApiError, apiVoid, messageFor } from '@/lib/api/client'

/**
 * The sign-in card.
 *
 * The one layout rule that matters: the error slot has a reserved `min-h`, so a
 * wrong-email or rate-limit notice appearing **cannot move the Continue
 * button**. That is the CLS the login page is measured on, and it is also a
 * correctness issue — a button that shifts under a pointer mid-click submits
 * something else.
 *
 * Google is a full-page navigation to `/api/auth/google/start`, not a fetch:
 * OAuth is a redirect dance and the browser has to be the thing that travels.
 * A plain `<a>` therefore, so it works before hydration too.
 */

const schema = z.object({
  email: z.string().trim().min(1, 'Enter your email address').email('That is not an email address'),
})

type Values = z.infer<typeof schema>

export function LoginCard({
  next,
  initialError,
  loginAvailable,
  authEnabled,
}: {
  next: string
  initialError: string | null
  loginAvailable: boolean
  authEnabled: boolean
}) {
  const router = useRouter()
  const [notice, setNotice] = useState<string | null>(initialError)
  const [retryAfter, setRetryAfter] = useState<number | null>(null)

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { email: '' },
    mode: 'onSubmit',
  })

  const onSubmit = form.handleSubmit(async ({ email }) => {
    setNotice(null)
    setRetryAfter(null)
    try {
      // `apiVoid`: the API answers 204, so there is no body to decode.
      await apiVoid(
        '/api/auth/otp',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email }),
        },
        'Could not send a code. Try again.'
      )
      router.push(
        `/login/verify?email=${encodeURIComponent(email)}&next=${encodeURIComponent(next)}`
      )
    } catch (error) {
      if (error instanceof ClientApiError && error.status === 429) {
        // The API's own Retry-After, so the countdown matches the limiter
        // rather than guessing at it.
        setRetryAfter(error.retryAfter)
        setNotice('Too many attempts. Wait a moment and try again.')
        return
      }
      // A 503 here is "sign-in is not configured on this server", and the
      // invite-only refusal is a sentence the API writes — both arrive as the
      // error's message, which is why this does not second-guess it.
      setNotice(messageFor(error, 'Could not send a code. Try again.'))
    }
  })

  if (!authEnabled) {
    return (
      <Card>
        <Notice tone="info" title="This server does not require sign-in">
          It is running in development mode, so every request is the bootstrap admin. Open the app
          directly.
        </Notice>
        <Button variant="primary" className="mt-3 w-full" onClick={() => router.push(next)}>
          Continue
        </Button>
      </Card>
    )
  }

  return (
    <Card>
      <h1 className="text-lg font-medium text-fg">Sign in to Peritus</h1>
      <p className="mt-1 text-sm text-fg-3">We email a six-digit code. No password to remember.</p>

      <form onSubmit={onSubmit} className="mt-5 space-y-1.5" noValidate>
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          inputMode="email"
          autoComplete="email"
          autoFocus
          placeholder="you@example.com"
          aria-invalid={form.formState.errors.email ? true : undefined}
          {...form.register('email')}
        />
        <FieldError>{form.formState.errors.email?.message}</FieldError>

        <Button
          type="submit"
          variant="primary"
          size="lg"
          className="w-full"
          loading={form.formState.isSubmitting}
        >
          Continue
        </Button>
      </form>

      {/* Below the button, so a notice appearing can never move Continue. Only
          a small slot is reserved: the full height of a notice left a visible
          hole on a phone, and what it protected — the Google button shifting
          down after a failed Continue — is not a click anyone is mid-way through. */}
      <div className="min-h-8 pt-3">
        {notice && (
          <Notice
            tone="bad"
            className="animate-in duration-(--dur-2) fade-in slide-in-from-bottom-1"
          >
            {notice}
            {retryAfter !== null && <Countdown seconds={retryAfter} />}
          </Notice>
        )}
      </div>

      <div className="flex items-center gap-3" aria-hidden="true">
        <span className="h-px flex-1 bg-border-soft" />
        <span className="text-xs text-fg-3">or</span>
        <span className="h-px flex-1 bg-border-soft" />
      </div>

      <a
        href={`/api/auth/google/start?next=${encodeURIComponent(next)}`}
        aria-disabled={!loginAvailable}
        className={cn(
          'mt-4 flex h-(--btn-lg) w-full items-center justify-center gap-2.5 rounded-row',
          'border border-border text-sm font-medium text-fg',
          'transition-colors duration-(--dur-1) hover:bg-raised',
          !loginAvailable && 'pointer-events-none opacity-50'
        )}
      >
        <GoogleMark className="size-4" />
        Continue with Google
      </a>
    </Card>
  )
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="w-full max-w-[360px] rounded-panel border border-border bg-panel p-5">
      {children}
    </div>
  )
}

/** A live countdown inside a 429 notice, so "wait" has a number on it. */
function Countdown({ seconds }: { seconds: number }) {
  const [left, setLeft] = useState(seconds)

  useEffect(() => {
    if (left <= 0) return
    const timer = setTimeout(() => setLeft((value) => value - 1), 1000)
    return () => clearTimeout(timer)
  }, [left])

  if (left <= 0) return null
  return <span className="mt-1 block text-xs text-fg-3">Try again in {left}s.</span>
}
