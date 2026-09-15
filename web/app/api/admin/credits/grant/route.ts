import { forward, guardOrigin, isResponse, jsonBody } from '@/lib/api/route'
import type { GrantCreditsBody } from '@/lib/api/types'

/** Admin-only upstream; a non-admin gets a 404, which the page renders as one. */
export async function POST(request: Request) {
  const blocked = guardOrigin(request)
  if (blocked) return blocked
  const body = await jsonBody<GrantCreditsBody>(request)
  if (isResponse(body)) return body
  return forward('/admin/credits/grant', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}
