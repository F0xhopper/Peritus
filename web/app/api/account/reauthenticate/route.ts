import { forward, guardOrigin } from '@/lib/api/route'

/** Email a code that authorises a sensitive change. */
export async function POST(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  return forward('/auth/account/reauthenticate', { method: 'POST' })
}
