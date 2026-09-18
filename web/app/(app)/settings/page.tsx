import { AccountSettingsPage } from '@/components/settings/account-settings-page'
import { getAccount, getBilling, getLedger, getMe, getSessions } from '@/lib/api/data'

export const metadata = { title: 'Settings' }

export default async function SettingsPage({
  searchParams,
}: {
  searchParams: Promise<{ linked?: string; auth_error?: string }>
}) {
  const params = await searchParams
  const me = await getMe('/settings')
  const [account, sessions, credits, ledger] = await Promise.all([
    getAccount('/settings'),
    getSessions('/settings'),
    getBilling('/settings').catch(() => null),
    // The ledger only matters when credits are enforced, but fetching it here
    // keeps the page one round trip; it is cheap and bounded at 50 rows.
    getLedger(50, '/settings').catch(() => []),
  ])

  const flash = params.auth_error
    ? { tone: 'bad' as const, message: params.auth_error.slice(0, 200) }
    : params.linked === 'google'
      ? { tone: 'ok' as const, message: 'Google is linked. You can sign in with it now.' }
      : null

  return (
    <AccountSettingsPage
      me={me}
      account={account}
      sessions={sessions}
      credits={credits}
      ledger={ledger}
      flash={flash}
    />
  )
}
