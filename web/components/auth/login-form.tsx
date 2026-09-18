'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'

import { FormNotice, GoogleButton, NoAuthNotice } from '@/components/auth/auth-parts'
import { PasswordInput } from '@/components/auth/password-input'
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
import { useEnterApp } from '@/hooks/use-enter-app'
import { ClientApiError, apiSend, errorCode, messageFor } from '@/lib/api/client'
import { authHref } from '@/lib/auth/links'
import { z } from '@/lib/validation'

/**
 * Sign in — shadcn's `login-03` block: Google first, "or", then email and
 * password with the recovery link beside the password label.
 *
 * Password managers are the reason for the details: `autocomplete="username"`
 * on the email and `current-password` on the password, a real `<form>` with a
 * submit button, and no field that appears only after the first is filled.
 *
 * The emailed code is still here, one link down, for anyone who never set a
 * password — including everyone who signed up before passwords existed.
 */

const schema = z.object({
  email: z.string().trim().min(1, 'Enter your email address').email('That is not an email address'),
  password: z.string().min(1, 'Enter your password'),
})

type Values = z.infer<typeof schema>

export function LoginForm({
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
  const { entering, enter } = useEnterApp()

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { email: '', password: '' },
    mode: 'onSubmit',
  })
  const email = useWatch({ control: form.control, name: 'email' })

  const onSubmit = form.handleSubmit(async (values) => {
    setNotice(null)
    setRetryAfter(null)
    try {
      await apiSend('/api/auth/password/login', 'POST', values, 'Could not sign in. Try again.')
      enter(next)
    } catch (error) {
      if (errorCode(error) === 'email_not_confirmed') {
        router.push(authHref('/login/verify', { email: values.email, next, type: 'signup' }))
        return
      }
      if (error instanceof ClientApiError && error.status === 429) {
        setRetryAfter(error.retryAfter)
        setNotice('Too many attempts. Wait a moment and try again.')
        return
      }
      setNotice(messageFor(error, 'Could not sign in. Try again.'))
      form.setValue('password', '')
      form.setFocus('password')
    }
  })

  if (!authEnabled) return <NoAuthNotice onContinue={() => router.push(next)} />

  return (
    <div className="flex w-full max-w-sm flex-col gap-5">
      <Card>
        <CardHeader className="text-center">
          <CardTitle>Sign in to Peritus</CardTitle>
          <CardDescription>Welcome back. Use Google or your email.</CardDescription>
        </CardHeader>
        <CardContent>
          <FieldGroup>
            <Field>
              <GoogleButton
                href={authHref('/api/auth/google/start', { next })}
                disabled={!loginAvailable}
              />
            </Field>
            <FieldSeparator>or</FieldSeparator>
            <form onSubmit={onSubmit} noValidate>
              <FieldGroup className="gap-4">
                <Field data-invalid={form.formState.errors.email ? true : undefined}>
                  <FieldLabel htmlFor="email">Email</FieldLabel>
                  <Input
                    id="email"
                    type="email"
                    inputMode="email"
                    autoComplete="username"
                    autoFocus
                    placeholder="you@example.com"
                    aria-invalid={form.formState.errors.email ? true : undefined}
                    aria-describedby="email-error"
                    {...form.register('email')}
                  />
                  <FieldError id="email-error" reserve errors={[form.formState.errors.email]} />
                </Field>
                <Field data-invalid={form.formState.errors.password ? true : undefined}>
                  <div className="flex items-center">
                    <FieldLabel htmlFor="password">Password</FieldLabel>
                    <Link
                      href={authHref('/login/forgot', { email: email.trim() || undefined, next })}
                      className="ml-auto inline-flex items-center text-xs text-fg-3 underline-offset-4 hover:text-fg hover:underline pointer-coarse:min-h-11"
                    >
                      Forgot password?
                    </Link>
                  </div>
                  <PasswordInput
                    id="password"
                    autoComplete="current-password"
                    aria-invalid={form.formState.errors.password ? true : undefined}
                    aria-describedby="password-error"
                    {...form.register('password')}
                  />
                  <FieldError
                    id="password-error"
                    reserve
                    errors={[form.formState.errors.password]}
                  />
                </Field>
                <Button
                  type="submit"
                  variant="primary"
                  size="lg"
                  className="w-full"
                  loading={form.formState.isSubmitting || entering}
                  disabled={!loginAvailable}
                >
                  Sign in
                </Button>
              </FieldGroup>
            </form>
            <FormNotice notice={notice} retryAfter={retryAfter} />
            <FieldDescription className="text-center">
              No password?{' '}
              <Link href={authHref('/login/code', { email: email.trim() || undefined, next })}>
                Email me a sign-in code
              </Link>
            </FieldDescription>
          </FieldGroup>
        </CardContent>
      </Card>
      <FieldDescription className="text-center text-sm">
        New to Peritus? <Link href={authHref('/signup', { next })}>Create an account</Link>
      </FieldDescription>
    </div>
  )
}
