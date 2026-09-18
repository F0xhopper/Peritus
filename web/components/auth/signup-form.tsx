'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'

import { FormNotice, GoogleButton, NoAuthNotice } from '@/components/auth/auth-parts'
import { PasswordInput } from '@/components/auth/password-input'
import { PasswordMeter } from '@/components/auth/password-meter'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldSeparator,
} from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { ClientApiError, apiSend, messageFor } from '@/lib/api/client'
import { authHref } from '@/lib/auth/links'
import { passwordSchema } from '@/lib/auth/password'
import { z } from '@/lib/validation'

/**
 * Create an account — shadcn's `signup` shape: Google, "or", then name, email
 * and password.
 *
 * One password field, not two. A confirm field catches a typo only by making
 * everyone type it twice; the show toggle catches it better, and "forgot
 * password" is one link away if it slips through anyway (NIST 800-63B leaves it
 * out; so do most current sign-up forms).
 *
 * Submitting moves on to the code page whether or not the address already has
 * an account — the API answers the same both ways, so this page cannot be used
 * to find out who is registered.
 */

const schema = z.object({
  name: z.string().trim().max(120, 'Keep it under 120 characters'),
  email: z.string().trim().min(1, 'Enter your email address').email('That is not an email address'),
  password: passwordSchema,
})

type Values = z.infer<typeof schema>

export function SignupForm({
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
    defaultValues: { name: '', email: '', password: '' },
    mode: 'onSubmit',
  })
  const [email, password] = useWatch({ control: form.control, name: ['email', 'password'] })
  const errors = form.formState.errors

  const onSubmit = form.handleSubmit(async (values) => {
    setNotice(null)
    setRetryAfter(null)
    try {
      const result = await apiSend<{ confirmation_required: boolean }>(
        '/api/auth/signup',
        'POST',
        values,
        'Could not create the account. Try again.'
      )
      if (!result.confirmation_required) {
        window.location.assign(next)
        return
      }
      router.push(authHref('/login/verify', { email: values.email, next, type: 'signup' }))
    } catch (error) {
      if (error instanceof ClientApiError && error.status === 429) {
        setRetryAfter(error.retryAfter)
        setNotice('Too many attempts. Wait a moment and try again.')
        return
      }
      setNotice(messageFor(error, 'Could not create the account. Try again.'))
    }
  })

  if (!authEnabled) return <NoAuthNotice onContinue={() => router.push(next)} />

  return (
    <div className="flex w-full max-w-sm flex-col gap-5">
      <Card>
        <CardHeader className="text-center">
          <CardTitle>Create your account</CardTitle>
          <CardDescription>Experts built from sources you can check.</CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field>
              <GoogleButton
                href={authHref('/api/auth/google/start', { next })}
                disabled={!loginAvailable}
              >
                Sign up with Google
              </GoogleButton>
            </Field>
            <FieldSeparator>or</FieldSeparator>
            <form onSubmit={onSubmit} noValidate>
              <FieldGroup className="gap-4">
                <Field>
                  <FieldLabel htmlFor="name">
                    Name <span className="font-normal text-fg-3">(optional)</span>
                  </FieldLabel>
                  <Input
                    id="name"
                    autoComplete="name"
                    autoFocus
                    placeholder="Ada Lovelace"
                    aria-invalid={errors.name ? true : undefined}
                    {...form.register('name')}
                  />
                  <FieldError errors={[errors.name]} />
                </Field>
                <Field data-invalid={errors.email ? true : undefined}>
                  <FieldLabel htmlFor="email">Email</FieldLabel>
                  <Input
                    id="email"
                    type="email"
                    inputMode="email"
                    autoComplete="email"
                    placeholder="you@example.com"
                    aria-invalid={errors.email ? true : undefined}
                    aria-describedby="email-error"
                    {...form.register('email')}
                  />
                  <FieldError id="email-error" reserve errors={[errors.email]} />
                </Field>
                <Field data-invalid={errors.password ? true : undefined}>
                  <FieldLabel htmlFor="password">Password</FieldLabel>
                  <PasswordInput
                    id="password"
                    autoComplete="new-password"
                    aria-invalid={errors.password ? true : undefined}
                    aria-describedby="password-help"
                    {...form.register('password')}
                  />
                  <div id="password-help">
                    {errors.password ? (
                      <FieldError reserve errors={[errors.password]} />
                    ) : (
                      <PasswordMeter value={password} email={email} />
                    )}
                  </div>
                </Field>
                <Button
                  type="submit"
                  variant="primary"
                  size="lg"
                  className="w-full"
                  loading={form.formState.isSubmitting}
                  disabled={!loginAvailable}
                >
                  Create account
                </Button>
              </FieldGroup>
            </form>
            <FormNotice notice={notice} retryAfter={retryAfter} />
          </FieldGroup>
        </CardContent>
      </Card>
      <FieldDescription className="text-center text-sm">
        Already have an account? <Link href={authHref('/login', { next })}>Sign in</Link>
      </FieldDescription>
      <FieldDescription className="px-6 text-center">
        By creating an account you agree to the <Link href="/terms">Terms</Link> and the{' '}
        <Link href="/privacy">Privacy policy</Link>.
      </FieldDescription>
    </div>
  )
}
