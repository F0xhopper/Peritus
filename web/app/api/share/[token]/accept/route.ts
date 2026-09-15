import { forward, guardOrigin } from '@/lib/api/route'

interface Ctx {
  params: Promise<{ token: string }>
}

/**
 * Open a share link as the signed-in user: records a grant and returns the
 * slug to go to. A visitor with no session gets a 401, which the share page
 * never sends — it offers sign-in instead.
 */
export async function POST(request: Request, { params }: Ctx) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const { token } = await params
  return forward(`/share/${encodeURIComponent(token)}/accept`, { method: 'POST' })
}
