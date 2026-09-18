'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { CODE_LENGTH, CodeInput } from '@/components/auth/code-input'
import { FormNotice } from '@/components/auth/auth-parts'
import { SettingsSection } from '@/components/settings/account/section'
import { Button } from '@/components/ui/button'
import { Field, FieldDescription, FieldError, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { apiSend, messageFor } from '@/lib/api/client'
import type { Account } from '@/lib/api/types'
import { z } from '@/lib/validation'

/**
 * Change the sign-in email.
 *
 * Two steps, and nothing changes until the second: the new address gets a
 * code, and only entering it moves the account. With Supabase's "secure email
 * change" the current address gets one too, and both must be entered — the API
 * says which is still outstanding.
 */

const emailSchema = z.string().trim().email('That is not an email address')

type Step =
  { kind: 'idle' } | { kind: 'editing' } | { kind: 'code'; email: string; hint: string | null }

export function EmailSection({ account }: { account: Account }) {
  const router = useRouter()
  const [step, setStep] = useState<Step>({ kind: 'idle' })
  const [draft, setDraft] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const start = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    const parsed = emailSchema.safeParse(draft)
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message ?? 'That is not an email address')
      return
    }
    setPending(true)
    try {
      await apiSend('/api/account/email', 'POST', { email: parsed.data })
      setStep({ kind: 'code', email: parsed.data.toLowerCase(), hint: null })
      setCode('')
    } catch (failure) {
      setError(messageFor(failure, 'Could not start the change. Try again.'))
    } finally {
      setPending(false)
    }
  }

  const confirm = async (value: string) => {
    if (step.kind !== 'code' || value.length !== CODE_LENGTH || pending) return
    setPending(true)
    setNotice(null)
    try {
      const result = await apiSend<{ complete: boolean; message?: string | null }>(
        '/api/account/email/verify',
        'POST',
        { email: step.email, token: value }
      )
      setCode('')
      if (result.complete) {
        setStep({ kind: 'idle' })
        setNotice(null)
        router.refresh()
        return
      }
      setStep({ ...step, hint: result.message ?? 'Now enter the code sent to your other address.' })
    } catch (failure) {
      setCode('')
      setNotice(messageFor(failure, 'That code is wrong or has expired.'))
    } finally {
      setPending(false)
    }
  }

  return (
    <SettingsSection
      id="email"
      title="Email"
      description="Where sign-in codes and resets are sent."
    >
      {step.kind === 'idle' && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-fg">
            {account.email ?? '—'}
            {!account.email_confirmed && (
              <span className="ml-2 text-xs text-warn">unconfirmed</span>
            )}
          </p>
          <Button variant="outline" onClick={() => setStep({ kind: 'editing' })}>
            Change email
          </Button>
          {account.new_email && (
            <p className="w-full text-xs text-fg-3">
              A change to <span className="text-fg-2">{account.new_email}</span> is waiting for its
              code.{' '}
              <button
                type="button"
                className="text-fg underline underline-offset-2"
                onClick={() => {
                  setCode('')
                  setStep({ kind: 'code', email: account.new_email ?? '', hint: null })
                }}
              >
                Enter the code
              </button>
            </p>
          )}
        </div>
      )}

      {step.kind === 'editing' && (
        <form onSubmit={(event) => void start(event)} noValidate>
          <Field>
            <FieldLabel htmlFor="new-email">New email</FieldLabel>
            <Input
              id="new-email"
              type="email"
              inputMode="email"
              autoComplete="email"
              autoFocus
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              aria-invalid={error ? true : undefined}
            />
            {error ? (
              <FieldError>{error}</FieldError>
            ) : (
              <FieldDescription>
                We will send a code to the new address to confirm it.
              </FieldDescription>
            )}
          </Field>
          <div className="mt-3 flex gap-2">
            <Button type="submit" variant="primary" loading={pending}>
              Send code
            </Button>
            <Button type="button" variant="ghost" onClick={() => setStep({ kind: 'idle' })}>
              Cancel
            </Button>
          </div>
        </form>
      )}

      {step.kind === 'code' && (
        <div>
          <p className="text-sm text-fg-2">
            {step.hint ?? (
              <>
                Enter the code we sent to <span className="text-fg">{step.email}</span>.
              </>
            )}
          </p>
          <div className="mt-3 max-w-xs">
            <CodeInput
              value={code}
              onChange={setCode}
              onComplete={(value) => void confirm(value)}
              disabled={pending}
              label="Email change code"
            />
          </div>
          <FormNotice notice={notice} className="pt-3" />
          <div className="flex gap-2">
            <Button
              variant="primary"
              loading={pending}
              disabled={code.length !== CODE_LENGTH}
              onClick={() => void confirm(code)}
            >
              Confirm
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setStep({ kind: 'idle' })
                setNotice(null)
              }}
            >
              Keep {account.email ?? 'current email'}
            </Button>
          </div>
        </div>
      )}
    </SettingsSection>
  )
}
