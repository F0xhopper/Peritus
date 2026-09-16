'use client'

import { useState } from 'react'

import { TopBar } from '@/components/shell/top-bar'
import { Button } from '@/components/ui/button'
import { FieldError, Input, Label } from '@/components/ui/input'
import { Notice } from '@/components/ui/notice'
import { formatNumber } from '@/lib/format'
import type { GrantCreditsResult, Me } from '@/lib/api/types'
import { apiSend, messageFor } from '@/lib/api/client'

/**
 * The operator page: grant or claw back credits by hand.
 *
 * This is the entire billing integration. There is no payment provider, so the
 * whole flow is a founder issuing credits to an account that asked — and the
 * form says so rather than implying an invoice exists somewhere.
 *
 * A negative amount is a clawback and is allowed on purpose (the API takes
 * −100,000 to 100,000), because a mistaken grant has to be reversible.
 */
export function AdminPage({ me }: { me: Me }) {
  const [owner, setOwner] = useState('')
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const [plan, setPlan] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<GrantCreditsResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const parsed = Number(amount)
  const amountValid = amount.trim() !== '' && Number.isInteger(parsed) && parsed !== 0

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!owner.trim() || !amountValid || busy) return
    setBusy(true)
    setResult(null)
    setError(null)
    try {
      const body = await apiSend<GrantCreditsResult>(
        '/api/admin/credits/grant',
        'POST',
        {
          owner: owner.trim(),
          amount: parsed,
          reason: reason.trim() || undefined,
          plan: plan.trim() || undefined,
        },
        'The grant failed.'
      )
      setResult(body)
      setAmount('')
      setReason('')
      setPlan('')
    } catch (err) {
      // An inline row, not a toast: the operator has to be able to read the
      // reason while they fix the form.
      setError(messageFor(err, 'The grant failed.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <TopBar title="Admin" />
      <div className="scroll-col flex-1">
        <div className="mx-auto w-full max-w-[560px] px-4 pt-5 pb-10 md:px-6">
          <h1 className="text-title font-medium text-fg">Admin</h1>
          <p className="mt-1 text-sm text-fg-3">
            Signed in as {me.email ?? me.id}. Credits are issued by hand — there is no payment
            provider behind this form.
          </p>

          <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
            <div>
              <Label htmlFor="owner">Account email or id</Label>
              <Input
                id="owner"
                value={owner}
                onChange={(event) => setOwner(event.target.value)}
                placeholder="someone@example.com or a user uuid"
                autoComplete="off"
                className="mt-1.5"
              />
            </div>

            <div>
              <Label htmlFor="amount">Credits</Label>
              <Input
                id="amount"
                type="number"
                inputMode="numeric"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                placeholder="25"
                className="mt-1.5"
              />
              <FieldError>
                {amount.trim() !== '' && !amountValid ? 'A whole number, and not zero.' : undefined}
              </FieldError>
              <p className="text-xs text-fg-3">Negative claws credits back.</p>
            </div>

            <div>
              <Label htmlFor="reason">Reason</Label>
              <Input
                id="reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Why, for the credit history"
                maxLength={500}
                className="mt-1.5"
              />
            </div>

            <div>
              <Label htmlFor="plan">Move to plan (optional)</Label>
              <Input
                id="plan"
                value={plan}
                onChange={(event) => setPlan(event.target.value)}
                placeholder="free · lab · …"
                autoComplete="off"
                className="mt-1.5"
              />
              <p className="mt-1 text-xs text-fg-3">
                Leave blank to keep the account on its current plan.
              </p>
            </div>

            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={busy}
              disabled={!owner.trim() || !amountValid}
              minWidth={140}
            >
              {parsed < 0 ? 'Claw back' : 'Grant credits'}
            </Button>
          </form>

          {result && (
            <Notice tone="ok" title="Done" className="mt-5">
              <p>
                {result.granted > 0 ? 'Granted' : 'Clawed back'}{' '}
                {formatNumber(Math.abs(result.granted))} credits. New balance:{' '}
                <span className="text-fg">{formatNumber(result.balance)}</span>.
              </p>
              <p className="mt-1 font-mono text-xs text-fg-3">{result.owner_id}</p>
            </Notice>
          )}

          {error && (
            <Notice tone="bad" className="mt-5">
              {error}
            </Notice>
          )}
        </div>
      </div>
    </>
  )
}
