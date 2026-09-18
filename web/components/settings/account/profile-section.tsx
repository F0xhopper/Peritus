'use client'

import { useState } from 'react'

import { UserAvatar } from '@/components/identity/user-avatar'
import { SettingsSection } from '@/components/settings/account/section'
import { Button } from '@/components/ui/button'
import { Field, FieldDescription, FieldError, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { useApiAction } from '@/hooks/use-api-action'
import { apiSend } from '@/lib/api/client'
import type { Account } from '@/lib/api/types'

/** The picture and display name. Used in the app's chrome; never shown to other people. */
export function ProfileSection({ account }: { account: Account }) {
  const [name, setName] = useState(account.name ?? '')
  const [error, setError] = useState<string | null>(null)
  const dirty = name.trim() !== (account.name ?? '')

  const save = useApiAction((value: string) => apiSend('/api/account', 'PATCH', { name: value }), {
    success: 'Name saved.',
    onError: (message) => setError(message),
  })

  return (
    <SettingsSection id="profile" title="Profile">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          setError(null)
          if (name.trim().length > 120) {
            setError('Keep it under 120 characters.')
            return
          }
          void save.run(name.trim())
        }}
      >
        <Field>
          <FieldLabel htmlFor="profile-name">Name</FieldLabel>
          <div className="flex items-center gap-2">
            {/* Google's picture when the account has one; it is not uploaded
                or changed here, so there is no control for it. */}
            <UserAvatar
              name={account.name}
              email={account.email}
              avatarUrl={account.avatar_url}
              size={32}
            />
            <Input
              id="profile-name"
              autoComplete="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Your name"
              className="flex-1"
            />
            <Button type="submit" variant="secondary" loading={save.pending} disabled={!dirty}>
              Save
            </Button>
          </div>
          {error ? (
            <FieldError>{error}</FieldError>
          ) : (
            <FieldDescription>Only you see this.</FieldDescription>
          )}
        </Field>
      </form>
    </SettingsSection>
  )
}
