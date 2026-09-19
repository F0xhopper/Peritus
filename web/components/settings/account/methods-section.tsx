'use client'

import { Mail } from 'lucide-react'
import { useState } from 'react'

import { GoogleMark } from '@/components/auth/google-mark'
import { SettingsSection } from '@/components/settings/account/section'
import { Button } from '@/components/ui/button'
import { DateText } from '@/components/ui/relative-time'
import { useApiAction } from '@/hooks/use-api-action'
import { apiVoid } from '@/lib/api/client'
import { cn } from '@/lib/cn'
import type { Account, Identity } from '@/lib/api/types'

/**
 * The ways into this account.
 *
 * Email is always there — an emailed code works for every account. Google is
 * linked by signing in with a Google account on the same address (Supabase
 * links it automatically), or from here with "Link Google". Unlinking is
 * offered only while another way remains; the API refuses the last one anyway.
 */
export function MethodsSection({ account }: { account: Account }) {
  const google = account.identities.find((identity) => identity.provider === 'google')
  const email = account.identities.find((identity) => identity.provider === 'email')
  const canUnlink = account.identities.length > 1
  const [confirming, setConfirming] = useState(false)

  const unlink = useApiAction(
    (identity: Identity) =>
      apiVoid(`/api/account/identities/${encodeURIComponent(identity.id)}`, { method: 'DELETE' }),
    { success: 'Google unlinked.', onSuccess: () => setConfirming(false) }
  )

  return (
    <SettingsSection
      id="sign-in"
      title="Sign-in methods"
      description="Any of these signs you in to the same account."
    >
      <ul className="divide-y divide-border-soft rounded-card border border-border-soft bg-panel">
        <MethodRow
          icon={<Mail className="size-4 text-fg-2" aria-hidden="true" />}
          name="Email"
          detail={
            account.has_password
              ? 'Password, or a code sent to your email'
              : 'A code sent to your email'
          }
          since={email?.created_at ?? account.created_at}
        />
        <MethodRow
          icon={<GoogleMark className="size-4" />}
          name="Google"
          detail={google ? (google.email ?? 'Linked') : 'Not linked'}
          since={google?.created_at ?? null}
          action={
            google ? (
              canUnlink ? (
                confirming ? (
                  <span className="flex gap-1.5">
                    <Button
                      size="sm"
                      variant="danger"
                      loading={unlink.pending}
                      onClick={() => void unlink.run(google)}
                    >
                      Unlink
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                      Keep
                    </Button>
                  </span>
                ) : (
                  <Button size="sm" variant="outline" onClick={() => setConfirming(true)}>
                    Unlink
                  </Button>
                )
              ) : null
            ) : (
              // A navigation: linking is the same redirect dance as signing in.
              <a
                href="/api/auth/google/link?next=%2Fsettings%3Flinked%3Dgoogle%23sign-in"
                className={cn(
                  'inline-flex h-(--icon-btn-sm) items-center rounded-chip border border-border px-2',
                  'text-xs font-medium text-fg-2 transition-colors hover:bg-raised hover:text-fg'
                )}
              >
                Link Google
              </a>
            )
          }
        />
      </ul>
    </SettingsSection>
  )
}

function MethodRow({
  icon,
  name,
  detail,
  since,
  action,
}: {
  icon: React.ReactNode
  name: string
  detail: string
  since: string | null
  action?: React.ReactNode
}) {
  return (
    <li className="flex items-center gap-3 px-3 py-2.5">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-raised">
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm text-fg">{name}</p>
        <p className="truncate text-xs text-fg-3">
          {detail}
          {since && (
            <>
              {' · since '}
              <DateText iso={since} />
            </>
          )}
        </p>
      </div>
      {action}
    </li>
  )
}
