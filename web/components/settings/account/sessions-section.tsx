'use client'

import { Laptop, Smartphone, SquareTerminal, HelpCircle } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { SettingsSection } from '@/components/settings/account/section'
import { Button } from '@/components/ui/button'
import { Notice } from '@/components/ui/notice'
import { RelativeTime } from '@/components/ui/relative-time'
import { useApiAction } from '@/hooks/use-api-action'
import { apiVoid, messageFor } from '@/lib/api/client'
import { describeUserAgent, type DeviceLabel } from '@/lib/user-agent'
import type { SignInSession } from '@/lib/api/types'

/**
 * Where this account is signed in, and a way to end each one.
 *
 * Ending another device's session deletes it and its refresh tokens; that
 * device is signed out at its next refresh — within the hour an access token
 * lives. This device signs out through the ordinary sign-out, which also
 * clears its cookies.
 */
const ICONS: Record<DeviceLabel['kind'], typeof Laptop> = {
  desktop: Laptop,
  phone: Smartphone,
  terminal: SquareTerminal,
  unknown: HelpCircle,
}

export function SessionsSection({ sessions }: { sessions: SignInSession[] | null }) {
  const [signingOut, setSigningOut] = useState<'local' | 'global' | null>(null)
  const others = sessions?.filter((session) => !session.current) ?? []

  const revoke = useApiAction(
    (id: string) =>
      apiVoid(`/api/account/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
    { success: 'Signed out of that device.' }
  )
  const revokeOthers = useApiAction(
    () => apiVoid('/api/auth/logout?scope=others', { method: 'POST' }),
    { success: 'Signed out of every other device.' }
  )

  const signOut = async (scope: 'local' | 'global') => {
    setSigningOut(scope)
    try {
      await apiVoid(`/api/auth/logout?scope=${scope}`, { method: 'POST' })
    } catch (error) {
      // The cookies are cleared on the response either way; say so only if
      // the request itself never arrived.
      toast.error(messageFor(error, 'Could not reach Peritus; signing out here anyway.'))
    }
    // A full navigation on purpose: `router.push` keeps the React tree and its
    // caches alive, so the previous account's data would still be on screen
    // behind the login page.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- a deliberate full reload
    window.location.assign('/login')
  }

  return (
    <SettingsSection
      id="sessions"
      title="Where you're signed in"
      description="Sign out of any device you don't recognise, then change your password."
    >
      {sessions === null ? (
        <Notice tone="info">This server cannot list sessions.</Notice>
      ) : (
        <ul className="divide-y divide-border-soft rounded-card border border-border-soft bg-panel">
          {sessions.map((session) => {
            const device = describeUserAgent(session.user_agent)
            const Icon = ICONS[device.kind]
            return (
              <li key={session.id} className="flex items-center gap-3 px-3 py-2.5">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-raised">
                  <Icon className="size-4 text-fg-2" aria-hidden="true" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-fg">
                    {device.label}
                    {session.current && (
                      <span className="ml-2 rounded-chip bg-ok/12 px-1.5 py-0.5 text-xs text-ok">
                        This device
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-fg-3">
                    Signed in <RelativeTime iso={session.created_at} />
                    {session.last_active_at && (
                      <>
                        {' · active '}
                        <RelativeTime iso={session.last_active_at} />
                      </>
                    )}
                  </p>
                </div>
                {!session.current && (
                  <Button
                    size="sm"
                    variant="outline"
                    loading={revoke.pending}
                    onClick={() => void revoke.run(session.id)}
                    aria-label={`Sign out of ${device.label}`}
                  >
                    Sign out
                  </Button>
                )}
              </li>
            )
          })}
        </ul>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <Button
          variant="outline"
          loading={signingOut === 'local'}
          onClick={() => void signOut('local')}
        >
          Sign out
        </Button>
        {others.length > 0 && (
          <Button
            variant="outline"
            loading={revokeOthers.pending}
            onClick={() => void revokeOthers.run()}
          >
            Sign out of other devices
          </Button>
        )}
        <Button
          variant="outline"
          loading={signingOut === 'global'}
          onClick={() => void signOut('global')}
        >
          Sign out everywhere
        </Button>
      </div>
    </SettingsSection>
  )
}
