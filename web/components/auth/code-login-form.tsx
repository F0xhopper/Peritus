'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { useForm } from 'react-hook-form'

import { FormNotice, NoAuthNotice } from '@/components/auth/auth-parts'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { ClientApiError, apiVoid, messageFor } from '@/lib/api/client'
import { authHref } from '@/lib/auth/links'
import { z } from '@/lib/validation'

/**
 * Sign in with an emailed six-digit code — no password.
 *
 * The original way in, and still the only one the CLI and TUI have. It also
 * creates an account for a new address when the server allows sign-ups, which
 * is why an invite-only refusal is the API's own sentence, passed through.
 */

const schema = z.object({
  email: z.string().trim().min(1, 'Enter your email address').email('That is not an email address'),
})

type Values = z.infer<typeof schema>

export function CodeLoginForm({
  next,
  initialEmail,
  authEnabled,
}: {
  next: string
  initialEmail: string
  authEnabled: boolean
}) {
  const router = useRouter()
  const [notice, setNotice] = useState<string | null>(null)
  const [retryAfter, setRetryAfter] = useState<number | null>(null)

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { email: initialEmail },
    mode: 'onSubmit',
  })

  const onSubmit = form.handleSubmit(async ({ email }) => {
    setNotice(null)
    setRetryAfter(null)
    try {
      await apiVoid(
        '/api/auth/otp',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email }),
        },
        'Could not send a code. Try again.'
      )
      router.push(authHref('/login/verify', { email, next }))
    } catch (error) {
      if (error instanceof ClientApiError && error.status === 429) {
        // The API's own Retry-After, so the countdown matches the limiter.
        setRetryAfter(error.retryAfter)
        setNotice('Too many attempts. Wait a moment and try again.')
        return
      }
      setNotice(messageFor(error, 'Could not send a code. Try again.'))
    }
  })

  if (!authEnabled) return <NoAuthNotice onContinue={() => router.push(next)} />

  return (
    <div className="flex w-full max-w-sm flex-col gap-5">
      <Card>
        <CardHeader className="text-center">
          <CardTitle>Sign in with a code</CardTitle>
          <CardDescription>We email a six-digit code. No password needed.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} noValidate>
            <FieldGroup className="gap-4">
              <Field data-invalid={form.formState.errors.email ? true : undefined}>
                <FieldLabel htmlFor="email">Email</FieldLabel>
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
                <FieldError reserve errors={[form.formState.errors.email]} />
              </Field>
              <Button
                type="submit"
                variant="primary"
                size="lg"
                className="w-full"
                loading={form.formState.isSubmitting}
              >
                Send code
              </Button>
              <FormNotice notice={notice} retryAfter={retryAfter} />
              <FieldDescription className="text-center">
                <Link href={authHref('/login', { next })}>Sign in with a password</Link>
              </FieldDescription>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
