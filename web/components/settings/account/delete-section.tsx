'use client'

import { useState } from 'react'

import { SettingsSection } from '@/components/settings/account/section'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Field, FieldDescription, FieldError, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { apiSend, messageFor } from '@/lib/api/client'
import type { Account } from '@/lib/api/types'

/**
 * Delete the account, for real.
 *
 * Typing the email is the confirmation — not a checkbox, which a hurried click
 * satisfies. The dialog cannot be dismissed by the backdrop mid-confirm. The
 * operator account is refused by the API and is not offered the button.
 */
export function DeleteSection({ account }: { account: Account }) {
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const email = account.email ?? ''
  const matches = typed.trim().toLowerCase() === email.toLowerCase() && email !== ''

  const remove = async () => {
    setPending(true)
    setError(null)
    try {
      await apiSend('/api/account', 'DELETE', { confirm_email: typed.trim() })
      // The cookies are gone with the response; a full navigation drops every
      // cached page of the account that no longer exists.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- a deliberate full reload
      window.location.assign('/?account=deleted')
    } catch (failure) {
      setError(messageFor(failure, 'Could not delete the account. Nothing was removed.'))
      setPending(false)
    }
  }

  return (
    <SettingsSection
      id="delete"
      title="Delete account"
      description="Permanently removes your account, your experts, their sources and graphs, your chats, share links and credits. This cannot be undone."
      className="mt-12 border-t border-border-soft pt-6"
    >
      {account.is_admin ? (
        <p className="text-sm text-fg-3">The operator account cannot be deleted from here.</p>
      ) : (
        <Button
          variant="danger"
          onClick={() => {
            setTyped('')
            setError(null)
            setOpen(true)
          }}
        >
          Delete account…
        </Button>
      )}

      <Dialog
        open={open}
        onOpenChange={(next) => !pending && setOpen(next)}
        title="Delete your account?"
        description="Everything you own in Peritus is deleted at once. Experts shared with others stop working for them too."
        disablePointerDismissal
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={pending}
              disabled={!matches}
              onClick={() => void remove()}
            >
              Delete forever
            </Button>
          </div>
        }
      >
        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (matches) void remove()
          }}
        >
          <Field>
            <FieldLabel htmlFor="confirm-delete">
              Type <span className="font-mono">{email}</span> to confirm
            </FieldLabel>
            <Input
              id="confirm-delete"
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              aria-invalid={error ? true : undefined}
            />
            {error ? (
              <FieldError>{error}</FieldError>
            ) : (
              <FieldDescription>Your sign-in email, exactly.</FieldDescription>
            )}
          </Field>
        </form>
      </Dialog>
    </SettingsSection>
  )
}
