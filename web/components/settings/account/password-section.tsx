'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { toast } from 'sonner'

import { CODE_LENGTH, CodeInput } from '@/components/auth/code-input'
import { FormNotice } from '@/components/auth/auth-parts'
import { PasswordInput } from '@/components/auth/password-input'
import { PasswordMeter } from '@/components/auth/password-meter'
import { SettingsSection } from '@/components/settings/account/section'
import { Button } from '@/components/ui/button'
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { apiVoid, errorCode, messageFor } from '@/lib/api/client'
import { passwordSchema } from '@/lib/auth/password'
import type { Account } from '@/lib/api/types'

/**
 * Set a password, or change the one the account has.
 *
 * An account that has only used Google or a code has no password, and gets
 * "Set a password" with one field. One that has a password must type it to
 * change it. Either way a success signs every other device out (the API does
 * it), and the page says so.
 *
 * When Supabase wants fresh proof (its "secure password change"), the API
 * emails a code and answers 409; the form then asks for that code and sends
 * the same request again with it.
 */
export function PasswordSection({ account }: { account: Account }) {
  const router = useRouter()
  // `null` means the server cannot tell; treat it as "has one" so the current
  // field is offered, and let the API decide.
  const hasPassword = account.has_password !== false
  const [open, setOpen] = useState(false)
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [nonce, setNonce] = useState('')
  const [needsNonce, setNeedsNonce] = useState(false)
  const [fieldError, setFieldError] = useState<{ current?: string; next?: string }>({})
  const [notice, setNotice] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const reset = () => {
    setOpen(false)
    setCurrent('')
    setNext('')
    setNonce('')
    setNeedsNonce(false)
    setFieldError({})
    setNotice(null)
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setNotice(null)
    const errors: { current?: string; next?: string } = {}
    if (account.has_password === true && !current) errors.current = 'Enter your current password.'
    const parsed = passwordSchema.safeParse(next)
    if (!parsed.success) errors.next = parsed.error.issues[0]?.message
    if (needsNonce && nonce.length !== CODE_LENGTH) {
      setNotice('Enter the six-digit code from the email.')
      return
    }
    setFieldError(errors)
    if (errors.current || errors.next) return

    setPending(true)
    try {
      // `apiVoid`: the API answers 204.
      await apiVoid('/api/account/password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          password: next,
          current_password: current || null,
          nonce: needsNonce ? nonce : null,
        }),
      })
      toast.success(
        hasPassword
          ? 'Password changed. Your other devices have been signed out.'
          : 'Password set. You can now sign in with it.'
      )
      reset()
      router.refresh()
    } catch (error) {
      const code = errorCode(error)
      if (code === 'reauthentication_needed') {
        setNeedsNonce(true)
        setNonce('')
        setNotice(messageFor(error, 'Enter the code we emailed you.'))
      } else if (code === 'invalid_current_password' || code === 'current_password_required') {
        setFieldError({ current: messageFor(error, 'Your current password is incorrect.') })
      } else if (code === 'weak_password' || code === 'same_password') {
        setFieldError({ next: messageFor(error, 'Choose a different password.') })
      } else if (code === 'reauthentication_not_valid') {
        setNonce('')
        setNotice(messageFor(error, 'That code is wrong or has expired.'))
      } else {
        setNotice(messageFor(error, 'Could not update the password. Try again.'))
      }
    } finally {
      setPending(false)
    }
  }

  const resendNonce = async () => {
    try {
      await apiVoid('/api/account/reauthenticate', { method: 'POST' })
      toast.success('We sent another code.')
    } catch (error) {
      setNotice(messageFor(error, 'Could not send another code.'))
    }
  }

  return (
    <SettingsSection
      id="password"
      title="Password"
      description={
        hasPassword
          ? 'Sign in with your email and password, or keep using Google or an emailed code.'
          : 'You sign in with Google or an emailed code. Add a password to sign in with it too.'
      }
    >
      {!open ? (
        <Button variant="outline" onClick={() => setOpen(true)}>
          {hasPassword ? 'Change password' : 'Set a password'}
        </Button>
      ) : (
        <form onSubmit={(event) => void submit(event)} noValidate className="max-w-sm">
          {/* A hidden username field, so a password manager files the new
              password under the right account. */}
          <input
            type="email"
            name="username"
            autoComplete="username"
            value={account.email ?? ''}
            readOnly
            hidden
          />
          <FieldGroup className="gap-4">
            {hasPassword && (
              <Field data-invalid={fieldError.current ? true : undefined}>
                <FieldLabel htmlFor="current-password">Current password</FieldLabel>
                <PasswordInput
                  id="current-password"
                  autoComplete="current-password"
                  autoFocus
                  value={current}
                  onChange={(event) => setCurrent(event.target.value)}
                  aria-invalid={fieldError.current ? true : undefined}
                />
                {fieldError.current ? (
                  <FieldError>{fieldError.current}</FieldError>
                ) : (
                  account.has_password === null && (
                    <FieldDescription>Leave empty if you have never set one.</FieldDescription>
                  )
                )}
              </Field>
            )}
            <Field data-invalid={fieldError.next ? true : undefined}>
              <FieldLabel htmlFor="new-password">New password</FieldLabel>
              <PasswordInput
                id="new-password"
                autoComplete="new-password"
                autoFocus={!hasPassword}
                value={next}
                onChange={(event) => setNext(event.target.value)}
                aria-invalid={fieldError.next ? true : undefined}
              />
              {fieldError.next ? (
                <FieldError reserve>{fieldError.next}</FieldError>
              ) : (
                <PasswordMeter value={next} email={account.email} />
              )}
            </Field>
            {needsNonce && (
              <Field>
                <FieldLabel>Security code</FieldLabel>
                <CodeInput value={nonce} onChange={setNonce} label="Security code" autoFocus />
                <FieldDescription>
                  Sent to {account.email}.{' '}
                  <button type="button" className="underline" onClick={() => void resendNonce()}>
                    Send another
                  </button>
                </FieldDescription>
              </Field>
            )}
          </FieldGroup>
          <FormNotice notice={notice} className="pt-3" />
          <div className="flex gap-2">
            <Button type="submit" variant="primary" loading={pending}>
              {hasPassword ? 'Change password' : 'Set password'}
            </Button>
            <Button type="button" variant="ghost" onClick={reset}>
              Cancel
            </Button>
          </div>
          {hasPassword && (
            <p className="mt-2 text-xs text-fg-3">Your other devices will be signed out.</p>
          )}
        </form>
      )}
    </SettingsSection>
  )
}
