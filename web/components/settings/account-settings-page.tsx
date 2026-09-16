'use client'

import { LogOut, Monitor, Moon, Sun } from 'lucide-react'
import Link from 'next/link'
import { useTheme } from 'next-themes'
import { useState, useSyncExternalStore } from 'react'

import { CreditLedger } from '@/components/settings/credit-ledger'
import { TopBar } from '@/components/shell/top-bar'
import { Button } from '@/components/ui/button'
import { Segmented } from '@/components/ui/segmented'
import { cn } from '@/lib/cn'
import { formatNumber, humanise } from '@/lib/format'
import type { CreditState, LedgerEntry, Me } from '@/lib/api/types'
import { apiVoid } from '@/lib/api/client'

/**
 * The account page.
 *
 * **The credits section is absent — not empty, not disabled — when the API is
 * not enforcing credits.** A balance that means nothing is worse than no
 * balance, and a greyed-out "Upgrade" would be a promise the product cannot
 * keep: there is no checkout, so the only remedy anywhere in this app is to ask
 * (web-production.md, rule 3).
 */
const REQUEST_EMAIL = 'credits@peritus.app'

export function AccountSettingsPage({
  me,
  credits,
  ledger,
}: {
  me: Me
  credits: CreditState | null
  ledger: LedgerEntry[]
}) {
  const { theme, setTheme } = useTheme()
  // The saved theme lives in localStorage, which the server cannot read: it
  // rendered "System" checked and the client "Light", a hydration mismatch on
  // every visit by anyone who had picked a theme. Hydrate as the server did,
  // then show the real choice.
  const hydrated = useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false
  )
  const [signingOut, setSigningOut] = useState(false)
  const showCredits = credits?.credits_enforced === true

  const signOut = async () => {
    setSigningOut(true)
    try {
      await apiVoid('/api/auth/logout', { method: 'POST' })
    } catch {
      // Deliberately ignored: the cookies are cleared on the response either
      // way, and the reload below is what actually ends the session locally.
    }
    // A full navigation on purpose, which is why the rule is disabled rather
    // than obeyed: `router.push` keeps the React tree and its caches alive, so
    // the previous account's data would still be on screen behind the login
    // page. A reload is also what makes `proxy.ts` re-read the cleared cookies.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- a deliberate full reload
    window.location.assign('/login')
  }

  return (
    <>
      <TopBar title="Settings" />
      <div className="scroll-col flex-1">
        <div className="mx-auto w-full max-w-[560px] px-4 pt-5 pb-10 md:px-6">
          <h1 className="text-title font-medium text-fg">Settings</h1>

          <section className="mt-8">
            <h2 className="text-lg font-medium text-fg">Account</h2>
            <dl className="mt-3 space-y-2 text-sm">
              <Row label="Email">{me.email ?? '—'}</Row>
              <Row label="Account id">
                <span className="font-mono text-xs">{me.id}</span>
              </Row>
              {me.is_admin && (
                <Row label="Role">
                  <span className="text-fg">
                    Operator ·{' '}
                    <Link href="/admin" className="underline-offset-2 hover:underline">
                      admin tools
                    </Link>
                  </span>
                </Row>
              )}
            </dl>
          </section>

          <section className="mt-10">
            <h2 className="text-lg font-medium text-fg">Appearance</h2>
            <p className="mt-1 text-sm text-fg-3">
              Dark is the design; light is derived from the same tokens.
            </p>
            <Segmented
              label="Theme"
              className="mt-3"
              value={(hydrated ? (theme ?? 'system') : 'system') as 'system' | 'light' | 'dark'}
              onChange={setTheme}
              options={[
                { value: 'system', label: 'System' },
                { value: 'light', label: 'Light' },
                { value: 'dark', label: 'Dark' },
              ]}
            />
            <p className="mt-2 flex items-center gap-3 text-xs text-fg-3">
              <span className="inline-flex items-center gap-1">
                <Monitor className="size-3" /> follows the OS
              </span>
              <span className="inline-flex items-center gap-1">
                <Sun className="size-3" /> light
              </span>
              <span className="inline-flex items-center gap-1">
                <Moon className="size-3" /> dark
              </span>
            </p>
          </section>

          {showCredits && (
            <section id="credits" className="mt-10 scroll-mt-16">
              <h2 className="text-lg font-medium text-fg">Credits</h2>
              <dl className="mt-3 space-y-2 text-sm">
                <Row label="Plan">
                  <span className="text-fg">{credits.plan.display_name}</span>
                  {credits.plan.description && (
                    <span className="ml-1.5 text-xs text-fg-3">{credits.plan.description}</span>
                  )}
                </Row>
                <Row label="Balance">
                  <span className="text-fg">{formatNumber(credits.balance)}</span>
                </Row>
                {credits.held > 0 && (
                  <Row label="Reserved">
                    <span className="text-warn">{formatNumber(credits.held)}</span>
                    <span className="ml-1.5 text-xs text-fg-3">by a running build</span>
                  </Row>
                )}
                <Row label="Used">
                  <span className="text-fg-2">{formatNumber(credits.consumed)}</span>
                  <span className="ml-1.5 text-xs text-fg-3">
                    of {formatNumber(credits.granted)} granted
                  </span>
                </Row>
              </dl>

              <h3 className="mt-6 text-label tracking-[0.04em] text-fg-3 uppercase">
                What a build costs
              </h3>
              <ul className="mt-2 space-y-1 text-sm">
                {credits.tiers.map((tier) => (
                  <li key={tier.tier} className="flex items-baseline justify-between gap-2">
                    <span className={cn(tier.included_in_plan ? 'text-fg-2' : 'text-fg-3')}>
                      {humanise(tier.tier)}
                      {!tier.included_in_plan && (
                        <span className="ml-1.5 text-xs text-warn">not on your plan</span>
                      )}
                    </span>
                    <span className="font-mono text-xs text-fg-3">
                      {tier.credit_cost} {tier.credit_cost === 1 ? 'credit' : 'credits'}
                    </span>
                  </li>
                ))}
              </ul>

              {/* No checkout exists. The only remedy is to ask. */}
              <a
                href={`mailto:${REQUEST_EMAIL}?subject=${encodeURIComponent('Credit request')}&body=${encodeURIComponent(`Account: ${me.email ?? me.id}\nPlan: ${credits.plan.name}\nBalance: ${credits.balance}\n\nI would like more credits because…`)}`}
                className="mt-4 inline-flex h-(--row-h) items-center rounded-row border border-border px-3 text-sm text-fg-2 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
              >
                Request credits
              </a>
              <p className="mt-1.5 text-xs text-fg-3">
                Credits are issued by hand while billing is in private beta. There is no checkout.
              </p>

              {ledger.length > 0 && (
                <>
                  <h3 className="mt-8 text-label tracking-[0.04em] text-fg-3 uppercase">History</h3>
                  <CreditLedger entries={ledger} className="mt-2" />
                </>
              )}
            </section>
          )}

          <section className="mt-12 border-t border-border-soft pt-6">
            <Button variant="outline" size="md" loading={signingOut} onClick={() => void signOut()}>
              <LogOut className="size-3.5" />
              Sign out everywhere
            </Button>
            <p className="mt-1.5 text-xs text-fg-3">
              Revokes every session for this account, on every device.
            </p>
          </section>

          <p className="mt-10 text-xs text-fg-3">
            <Link href="/privacy" className="transition-colors hover:text-fg-3">
              Privacy
            </Link>
            <span aria-hidden="true" className="mx-2">
              ·
            </span>
            <Link href="/terms" className="transition-colors hover:text-fg-3">
              Terms
            </Link>
          </p>
        </div>
      </div>
    </>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3">
      <dt className="w-24 shrink-0 text-fg-3">{label}</dt>
      <dd className="min-w-0 flex-1 text-fg-2">{children}</dd>
    </div>
  )
}

function noopSubscribe() {
  return () => {}
}
