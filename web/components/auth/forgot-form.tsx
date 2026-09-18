'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { useForm } from 'react-hook-form'

import { FormNotice } from '@/components/auth/auth-parts'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { ClientApiError, apiVoid, messageFor } from '@/lib/api/client'
import { authHref } from '@/lib/auth/links'
import { z } from '@/lib/validation'

/**
 * Forgot password → a reset code by email. The next page says "if there is an
 * account for this address, a code is on its way", because that is all this
 * server will ever know to say.
 */

const schema = z.object({
  email: z.string().trim().min(1, 'Enter your email address').email('That is not an email address'),
})

export function ForgotForm({ next, initialEmail }: { next: string; initialEmail: string }) {
  const router = useRouter()
  const [notice, setNotice] = useState<string | null>(null)
  const [retryAfter, setRetryAfter] = useState<number | null>(null)
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { email: initialEmail },
  })

  const onSubmit = form.handleSubmit(async ({ email }) => {
    setNotice(null)
    setRetryAfter(null)
    try {
      await apiVoid(
        '/api/auth/password/forgot',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email }),
        },
        'Could not send a reset code. Try again.'
      )
      router.push(authHref('/login/reset', { email, next }))
    } catch (error) {
      if (error instanceof ClientApiError && error.status === 429) {
        setRetryAfter(error.retryAfter)
        setNotice('Too many attempts. Wait a moment and try again.')
        return
      }
      setNotice(messageFor(error, 'Could not send a reset code. Try again.'))
    }
  })

  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="text-center">
        <CardTitle>Reset your password</CardTitle>
        <CardDescription>We will email you a six-digit code to set a new one.</CardDescription>
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
              Send reset code
            </Button>
            <FormNotice notice={notice} retryAfter={retryAfter} />
            <FieldDescription className="text-center">
              Remembered it? <Link href={authHref('/login', { next })}>Back to sign in</Link>
            </FieldDescription>
          </FieldGroup>
        </form>
      </CardContent>
    </Card>
  )
}
