'use client'

import Link from 'next/link'
import { useState } from 'react'

import { CODE_LENGTH, CodeInput, FormNotice } from '@/components/auth/auth-parts'
import { PasswordInput, PasswordMeter } from '@/components/auth/password-input'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { ClientApiError, apiSend, errorCode, messageFor } from '@/lib/api/client'
import { authHref } from '@/lib/auth/links'
import { passwordSchema } from '@/lib/auth/password'

/**
 * The reset code and the new password, on one page and in one request, so a
 * code cannot be spent on a password that then fails validation. Success signs
 * the person in and signs every other device out (the API does the second).
 */
export function ResetForm({ email, next }: { email: string; next: string }) {
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [retryAfter, setRetryAfter] = useState<number | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [spent, setSpent] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setNotice(null)
    setRetryAfter(null)
    const parsed = passwordSchema.safeParse(password)
    if (!parsed.success) {
      setPasswordError(parsed.error.issues[0]?.message ?? 'Choose a different password')
      return
    }
    setPasswordError(null)
    if (code.length !== CODE_LENGTH) {
      setNotice('Enter the six-digit code from the email.')
      return
    }
    setSubmitting(true)
    try {
      await apiSend('/api/auth/password/reset', 'POST', { email, token: code, password })
      window.location.assign(next)
      return
    } catch (error) {
      if (error instanceof ClientApiError && error.status === 429) {
        setRetryAfter(error.retryAfter)
        setNotice('Too many attempts. Wait a moment and try again.')
      } else if (errorCode(error) === 'invalid_code') {
        setNotice(messageFor(error, 'That code is wrong or has expired.'))
        setCode('')
      } else if (errorCode(error) === 'weak_password' || errorCode(error) === 'same_password') {
        // The code was accepted and spent on the way; a new one is needed.
        setPasswordError(messageFor(error, 'Choose a different password.'))
        setSpent(true)
      } else {
        setNotice(messageFor(error, 'Could not reset the password. Try again.'))
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="text-center">
        <CardTitle>Choose a new password</CardTitle>
        <CardDescription>
          If there is an account for <span className="text-fg-2">{email}</span>, we have emailed it
          a six-digit code.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={(event) => void submit(event)} noValidate>
          <FieldGroup className="gap-4">
            <Field>
              <FieldLabel>Code</FieldLabel>
              <CodeInput value={code} onChange={setCode} autoFocus label="Six-digit reset code" />
            </Field>
            <Field data-invalid={passwordError ? true : undefined}>
              <FieldLabel htmlFor="new-password">New password</FieldLabel>
              <PasswordInput
                id="new-password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                aria-invalid={passwordError ? true : undefined}
              />
              {passwordError ? (
                <FieldError reserve>{passwordError}</FieldError>
              ) : (
                <PasswordMeter value={password} email={email} />
              )}
            </Field>
            <Button
              type="submit"
              variant="primary"
              size="lg"
              className="w-full"
              loading={submitting}
            >
              Set password and sign in
            </Button>
            <FormNotice notice={notice} retryAfter={retryAfter} />
            <FieldDescription className="text-center">
              {spent ? 'That code has been used. ' : 'No code? '}
              <Link href={authHref('/login/forgot', { email, next })}>Send a new one</Link>
            </FieldDescription>
          </FieldGroup>
        </form>
      </CardContent>
    </Card>
  )
}
