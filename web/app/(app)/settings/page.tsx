import { AccountSettingsPage } from '@/components/settings/account-settings-page'
import { getBilling, getLedger, getMe } from '@/lib/api/data'

export const metadata = { title: 'Settings' }

export default async function SettingsPage() {
  const me = await getMe('/settings')
  const [credits, ledger] = await Promise.all([
    getBilling('/settings').catch(() => null),
    // The ledger only matters when credits are enforced, but fetching it here
    // keeps the page one round trip; it is cheap and bounded at 50 rows.
    getLedger(50, '/settings').catch(() => []),
  ])

  return <AccountSettingsPage me={me} credits={credits} ledger={ledger} />
}
